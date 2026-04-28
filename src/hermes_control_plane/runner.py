from __future__ import annotations

import json
import os
import re
import shutil
import subprocess
import tempfile
import textwrap
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

try:
    import tomllib
except ModuleNotFoundError:  # pragma: no cover
    tomllib = None

from .feishu import FeishuNotifier, render_run_message


def _build_subprocess_env() -> dict[str, str]:
    """Return an env dict for subprocess calls with proxy + GitHub token injected.

    Codex runs in a non-interactive shell, so ~/.bashrc is not sourced.
    We explicitly inject HTTP proxy and GITHUB_TOKEN so Codex can access
    GitHub API, install packages, etc.
    """
    env = os.environ.copy()
    # Proxy — Clash on Windows host, WSL2 mirrored networking
    proxy = "http://127.0.0.1:7897"
    env.setdefault("http_proxy", proxy)
    env.setdefault("https_proxy", proxy)
    env.setdefault("HTTP_PROXY", proxy)
    env.setdefault("HTTPS_PROXY", proxy)
    # GitHub token from bashrc if not already set
    if not env.get("GITHUB_TOKEN"):
        # Try to source the token from ~/.bashrc
        import re as _re
        try:
            bashrc = Path.home() / ".bashrc"
            if bashrc.exists():
                for line in bashrc.read_text(encoding="utf-8").splitlines():
                    m = _re.search(r"export\s+GITHUB_TOKEN\s*=\s*[\"']?(\S+)", line)
                    if m:
                        env["GITHUB_TOKEN"] = m.group(1)
                        break
        except Exception:
            pass
    return env



STAGE_SCHEMAS = {
    "planner": {
        "summary": "string",
        "steps": [
            {
                "id": "string",
                "goal": "string",
                "owner": "codex|claude|hermes",
                "acceptance": "string",
                "notes": "string",
            }
        ],
        "risks": ["string"],
        "handoff_notes": ["string"],
    },
    "executor": {
        "status": "completed|blocked|partial",
        "summary": "string",
        "changed_files": ["string"],
        "commands_run": ["string"],
        "open_questions": ["string"],
        "next_steps": ["string"],
    },
    "reviewer": {
        "verdict": "pass|needs-work",
        "summary": "string",
        "findings": [
            {
                "severity": "high|medium|low",
                "file": "string",
                "issue": "string",
                "recommendation": "string",
            }
        ],
        "residual_risks": ["string"],
        "recommended_next_steps": ["string"],
    },
}


def utc_timestamp() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H-%M-%SZ")


def load_toml(path: Path) -> dict[str, Any]:
    if tomllib is None:
        raise RuntimeError("Python 3.11+ is required because tomllib is unavailable.")
    return tomllib.loads(path.read_text(encoding="utf-8"))


def load_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, ensure_ascii=False, indent=2) + "\n", encoding="utf-8")


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def write_notification_result(run_dir: Path, event: str, result: dict[str, Any]) -> None:
    write_json(run_dir / "notifications" / f"{event}.json", result)


def shorten(text: str, limit: int) -> str:
    if len(text) <= limit:
        return text
    return text[: limit - 13].rstrip() + "\n\n[truncated]"


def normalize_task(task: dict[str, Any], task_path: Path) -> dict[str, Any]:
    normalized = dict(task)
    normalized.setdefault("id", task_path.stem)
    normalized.setdefault("intent", "implement")
    normalized.setdefault("goal", "")
    normalized.setdefault("cwd", str(Path.cwd()))
    normalized.setdefault("constraints", [])
    normalized.setdefault("context_files", [])
    normalized.setdefault("notes", [])
    return normalized


def resolve_run_root(config: dict[str, Any]) -> Path:
    return Path(config.get("hermes", {}).get("runs_root", str(Path.home() / ".hermes" / "runs")))


def resolve_shared_context_paths(config: dict[str, Any]) -> tuple[list[Path], int]:
    hermes_cfg = config.get("hermes", {})
    paths = [Path(path) for path in hermes_cfg.get("shared_context_files", [])]
    char_limit = int(hermes_cfg.get("context_file_char_limit", 8000))
    return paths, char_limit


def render_context_blocks(paths: list[Path], char_limit: int) -> str:
    blocks = []
    for path in paths:
        if not path.exists():
            blocks.append(f"### Missing Context File\nPath: `{path}`\n")
            continue
        content = path.read_text(encoding="utf-8", errors="replace")
        blocks.append(
            "\n".join(
                [
                    f"### Context File: {path}",
                    "",
                    "```text",
                    shorten(content, char_limit),
                    "```",
                ]
            )
        )
    return "\n\n".join(blocks)


def resolve_requested_artifact_path(
    run_dir: Path,
    stage: str,
    final_artifact_path: Path,
    agent_name: str,
) -> Path:
    # Codex commonly runs with a workspace-write sandbox that allows temp writes
    # but not arbitrary home-directory paths such as ~/.hermes/runs.
    if agent_name == "codex":
        return Path(tempfile.gettempdir()) / "hermes-stage-artifacts" / run_dir.name / stage / "result.json"
    return final_artifact_path


def render_stage_prompt(
    stage: str,
    task: dict[str, Any],
    artifact_path: Path,
    shared_context: str,
    prior_artifacts: dict[str, dict[str, Any]],
    artifact_transport: str = "file",
) -> str:
    schema = json.dumps(STAGE_SCHEMAS[stage], ensure_ascii=False, indent=2)
    task_blob = json.dumps(task, ensure_ascii=False, indent=2)
    prior_blocks = []
    for label, data in prior_artifacts.items():
        prior_blocks.append(
            "\n".join(
                [
                    f"### Prior Artifact: {label}",
                    "",
                    "```json",
                    json.dumps(data, ensure_ascii=False, indent=2),
                    "```",
                ]
            )
        )
    prior_text = "\n\n".join(prior_blocks) if prior_blocks else "None."

    stage_objectives = {
        "planner": "Create a concrete execution plan and handoff for the executor.",
        "executor": "Execute the task against the workspace and report the real implementation outcome.",
        "reviewer": "Review the outcome with emphasis on correctness, regression risk, and missing tests.",
    }

    if artifact_transport == "stdout_json":
        output_contract = textwrap.dedent(
            f"""
            ## Output Contract

            Return exactly one valid JSON document in your final response.

            Use this schema:

            ```json
            {schema}
            ```

            Rules:
            - The final response must be raw JSON only.
            - Do not include markdown fences.
            - Do not include commentary before or after the JSON.
            - Keep secrets out of the output.
            """
        ).strip()
    else:
        output_contract = textwrap.dedent(
            f"""
            ## Output Contract

            Write exactly one valid JSON document to:
            `{artifact_path}`

            Use this schema:

            ```json
            {schema}
            ```

            Rules:
            - The artifact file is the primary output.
            - Keep stdout brief.
            - Do not include markdown fences in the JSON file.
            - Keep secrets out of the output.
            """
        ).strip()

    return textwrap.dedent(
        f"""
        Hermes stage: {stage}
        Objective: {stage_objectives[stage]}

        Working directory: {task["cwd"]}
        Required artifact path: {artifact_path}

        ## Task

        ```json
        {task_blob}
        ```

        ## Shared Context

        {shared_context or "None."}

        ## Prior Artifacts

        {prior_text}

        {output_contract}
        """
    ).strip() + "\n"


def strip_markdown_fences(text: str) -> str:
    stripped = text.strip()
    if stripped.startswith("```"):
        stripped = re.sub(r"^```[a-zA-Z0-9_-]*\s*", "", stripped)
        stripped = re.sub(r"\s*```$", "", stripped)
    return stripped.strip()


def parse_stdout_artifact(agent_name: str, stdout: str) -> dict[str, Any] | None:
    text = stdout.strip()
    if not text:
        return None

    if agent_name == "claude":
        try:
            envelope = json.loads(text)
            result = envelope.get("result", "")
            if not isinstance(result, str) or not result.strip():
                return None
            # Claude often prepends text before the JSON artifact.
            # Strip markdown fences first, then find JSON boundary.
            cleaned = strip_markdown_fences(result)
            # Find the first '{' that starts a JSON object
            json_start = cleaned.find("{")
            if json_start < 0:
                return None
            # Find matching closing brace
            candidate = cleaned[json_start:]
            try:
                return json.loads(candidate)
            except json.JSONDecodeError:
                # Try to find the last '}' to trim trailing text
                last_brace = candidate.rfind("}")
                if last_brace > 0:
                    try:
                        return json.loads(candidate[: last_brace + 1])
                    except json.JSONDecodeError:
                        pass
            return None
        except Exception:
            return None

    try:
        return json.loads(strip_markdown_fences(text))
    except Exception:
        return None


def run_agent(
    agent_name: str,
    agent_cfg: dict[str, Any],
    stage: str,
    task: dict[str, Any],
    run_dir: Path,
    prompt: str,
    requested_artifact_path: Path,
    final_artifact_path: Path,
) -> dict[str, Any]:
    stage_dir = run_dir / stage
    stage_dir.mkdir(parents=True, exist_ok=True)

    append_prompt_as = agent_cfg.get("append_prompt_as", "arg")
    timeout_seconds = int(agent_cfg.get("timeout_seconds", 3600))
    artifact_transport = agent_cfg.get("artifact_transport", "file")
    run_cwd = agent_cfg.get("run_cwd") or task["cwd"]
    command_line = list(agent_cfg.get("command", []))
    if not command_line:
        raise RuntimeError(f"Agent '{agent_name}' has no command configured.")

    stdin_text = None
    if append_prompt_as == "arg":
        command_line.append(prompt)
    elif append_prompt_as == "stdin":
        stdin_text = prompt
    else:
        raise RuntimeError(f"Unsupported append_prompt_as: {append_prompt_as}")

    requested_artifact_path.parent.mkdir(parents=True, exist_ok=True)

    write_text(stage_dir / "prompt.txt", prompt)
    write_json(
        stage_dir / "invocation.json",
        {
            "agent": agent_name,
            "stage": stage,
            "cwd": task["cwd"],
            "run_cwd": run_cwd,
            "command_line": command_line,
            "append_prompt_as": append_prompt_as,
            "timeout_seconds": timeout_seconds,
            "requested_artifact_path": str(requested_artifact_path),
            "final_artifact_path": str(final_artifact_path),
            "artifact_transport": artifact_transport,
        },
    )

    completed = subprocess.run(
        command_line,
        cwd=run_cwd,
        input=stdin_text,
        text=True,
        capture_output=True,
        timeout=timeout_seconds,
        env=_build_subprocess_env(),
        check=False,
    )

    write_text(stage_dir / "stdout.txt", completed.stdout)
    write_text(stage_dir / "stderr.txt", completed.stderr)

    artifact_json = None
    artifact_error = None

    if artifact_transport == "stdout_json":
        artifact_json = parse_stdout_artifact(agent_name, completed.stdout)
        if artifact_json is not None:
            write_json(final_artifact_path, artifact_json)
        else:
            artifact_error = "unable-to-parse-stdout-json"
    else:
        if not final_artifact_path.exists() and requested_artifact_path.exists():
            final_artifact_path.parent.mkdir(parents=True, exist_ok=True)
            shutil.copy2(requested_artifact_path, final_artifact_path)

    artifact_exists = final_artifact_path.exists()
    if artifact_exists and artifact_json is None:
        try:
            artifact_json = json.loads(final_artifact_path.read_text(encoding="utf-8"))
        except Exception as exc:  # pragma: no cover
            artifact_error = str(exc)

    result = {
        "agent": agent_name,
        "stage": stage,
        "returncode": completed.returncode,
        "artifact_path": str(final_artifact_path),
        "requested_artifact_path": str(requested_artifact_path),
        "artifact_exists": artifact_exists,
        "artifact_parse_error": artifact_error,
        "stdout_path": str(stage_dir / "stdout.txt"),
        "stderr_path": str(stage_dir / "stderr.txt"),
    }
    if artifact_json is not None:
        result["artifact"] = artifact_json

    write_json(stage_dir / "stage_result.json", result)
    return result


def run_pipeline(config_path: Path, task_path: Path, pipeline_name: str, profile_name: str | None) -> Path:
    config = load_toml(config_path)
    task = normalize_task(load_json(task_path), task_path)
    profile = profile_name or config.get("hermes", {}).get("default_profile", "wsl2")
    pipelines = config.get("pipelines", {})
    if pipeline_name not in pipelines:
        raise RuntimeError(f"Pipeline '{pipeline_name}' not found.")
    profile_cfg = config.get("profiles", {}).get(profile, {})
    if not profile_cfg:
        raise RuntimeError(f"Profile '{profile}' not found.")
    notifier = FeishuNotifier.from_config(config)

    run_dir = resolve_run_root(config) / f"{utc_timestamp()}-{task['id']}"
    run_dir.mkdir(parents=True, exist_ok=True)
    write_json(run_dir / "task.json", task)

    shared_paths, char_limit = resolve_shared_context_paths(config)
    task_context_paths = [Path(path) for path in task.get("context_files", [])]
    shared_context = render_context_blocks(shared_paths + task_context_paths, char_limit)

    # Build stage order from pipeline config.
    # Pipelines may omit planner or reviewer (e.g. fast_implement has only executor).
    stage_order = []
    for stage_key, stage_label in [("planner", "planner"), ("executor", "executor"), ("reviewer", "reviewer")]:
        if stage_key in pipelines[pipeline_name]:
            stage_order.append((stage_label, pipelines[pipeline_name][stage_key]))
    prior_artifacts: dict[str, dict[str, Any]] = {}
    run_summary = {
        "task_id": task["id"],
        "cwd": task["cwd"],
        "pipeline": pipeline_name,
        "profile": profile,
        "run_dir": str(run_dir),
        "status": "running",
        "stages": [],
        "notifications": [],
    }

    if notifier:
        started_result = notifier.send_text(
            "run_started",
            render_run_message(
                event="run_started",
                task_id=task["id"],
                goal=task["goal"],
                run_dir=run_dir,
                pipeline=pipeline_name,
                profile=profile,
                prefix=notifier.message_prefix,
            ),
        )
        run_summary["notifications"].append(started_result)
        write_notification_result(run_dir, "run_started", started_result)

    try:
        for stage, agent_name in stage_order:
            agent_cfg = profile_cfg.get(agent_name)
            if not agent_cfg or not agent_cfg.get("enabled", False):
                raise RuntimeError(f"Agent '{agent_name}' is not enabled in profile '{profile}'.")
            final_artifact_path = run_dir / stage / "result.json"
            requested_artifact_path = resolve_requested_artifact_path(
                run_dir=run_dir,
                stage=stage,
                final_artifact_path=final_artifact_path,
                agent_name=agent_name,
            )
            prompt = render_stage_prompt(
                stage,
                task,
                requested_artifact_path,
                shared_context,
                prior_artifacts,
                artifact_transport=agent_cfg.get("artifact_transport", "file"),
            )
            result = run_agent(
                agent_name,
                agent_cfg,
                stage,
                task,
                run_dir,
                prompt,
                requested_artifact_path,
                final_artifact_path,
            )
            run_summary["stages"].append(result)
            if result.get("artifact"):
                prior_artifacts[stage] = result["artifact"]
    except Exception as exc:
        run_summary["status"] = "failed"
        run_summary["error"] = str(exc)
        if notifier:
            failed_result = notifier.send_text(
                "run_failed",
                render_run_message(
                    event="run_failed",
                    task_id=task["id"],
                    goal=task["goal"],
                    run_dir=run_dir,
                    pipeline=pipeline_name,
                    profile=profile,
                    summary=str(exc),
                    prefix=notifier.message_prefix,
                ),
            )
            run_summary["notifications"].append(failed_result)
            write_notification_result(run_dir, "run_failed", failed_result)
        write_json(run_dir / "run_summary.json", run_summary)
        raise

    reviewer_artifact = prior_artifacts.get("reviewer", {})
    reviewer_verdict = reviewer_artifact.get("verdict")
    if reviewer_verdict == "needs-work" and notifier:
        review_result = notifier.send_text(
            "review_needs_work",
            render_run_message(
                event="review_needs_work",
                task_id=task["id"],
                goal=task["goal"],
                run_dir=run_dir,
                pipeline=pipeline_name,
                profile=profile,
                summary=reviewer_artifact.get("summary"),
                prefix=notifier.message_prefix,
            ),
        )
        run_summary["notifications"].append(review_result)
        write_notification_result(run_dir, "review_needs_work", review_result)

    run_summary["status"] = "completed"
    completion_summary = None
    executor_artifact = prior_artifacts.get("executor", {})
    if executor_artifact:
        completion_summary = executor_artifact.get("summary")
    elif reviewer_artifact:
        completion_summary = reviewer_artifact.get("summary")

    if notifier:
        completed_result = notifier.send_text(
            "run_completed",
            render_run_message(
                event="run_completed",
                task_id=task["id"],
                goal=task["goal"],
                run_dir=run_dir,
                pipeline=pipeline_name,
                profile=profile,
                summary=completion_summary,
                prefix=notifier.message_prefix,
            ),
        )
        run_summary["notifications"].append(completed_result)
        write_notification_result(run_dir, "run_completed", completed_result)

    write_json(run_dir / "run_summary.json", run_summary)
    return run_dir


def doctor(config_path: Path, profile_name: str | None) -> dict[str, Any]:
    config = load_toml(config_path)
    profile = profile_name or config.get("hermes", {}).get("default_profile", "wsl2")
    profile_cfg = config.get("profiles", {}).get(profile, {})
    if not profile_cfg:
        raise RuntimeError(f"Profile '{profile}' not found.")

    report = {
        "profile": profile,
        "agents": {},
        "feishu": {},
    }
    for agent_name, agent_cfg in profile_cfg.items():
        command = list(agent_cfg.get("command", []))
        if not command:
            report["agents"][agent_name] = {"ok": False, "reason": "missing-command"}
            continue

        executable = command[0]
        if "/" in executable or "\\" in executable:
            candidate = Path(executable)
            resolved_executable = str(candidate) if candidate.exists() else None
        else:
            resolved_executable = shutil.which(executable)

        doctor_command = list(agent_cfg.get("doctor_command", []))
        doctor_check = None
        if resolved_executable and doctor_command:
            try:
                completed = subprocess.run(
                    doctor_command,
                    text=True,
                    capture_output=True,
                    timeout=15,
                    env=_build_subprocess_env(),
                    check=False,
                )
                doctor_check = {
                    "returncode": completed.returncode,
                    "stdout": completed.stdout.strip(),
                    "stderr": completed.stderr.strip(),
                }
            except Exception as exc:  # pragma: no cover
                doctor_check = {
                    "returncode": -1,
                    "stdout": "",
                    "stderr": str(exc),
                }

        ok = bool(resolved_executable) and (doctor_check is None or doctor_check["returncode"] == 0)
        report["agents"][agent_name] = {
            "ok": ok,
            "command": command,
            "executable": executable,
            "resolved_executable": resolved_executable,
            "reason": None if resolved_executable else "executable-not-found",
        }
        if doctor_check is not None:
            report["agents"][agent_name]["doctor_check"] = doctor_check

    feishu_cfg = config.get("feishu", {})
    if feishu_cfg.get("enabled", False):
        webhook_cfg = feishu_cfg.get("webhook", {})
        url_env = webhook_cfg.get("url_env", "FEISHU_WEBHOOK_URL")
        secret_env = webhook_cfg.get("secret_env", "FEISHU_WEBHOOK_SECRET")
        report["feishu"] = {
            "enabled": True,
            "mode": feishu_cfg.get("mode", "webhook"),
            "url_env": url_env,
            "url_present": bool(os.environ.get(url_env)),
            "secret_env": secret_env,
            "secret_present": bool(os.environ.get(secret_env)),
            "notify_on": feishu_cfg.get("notify_on")
            or feishu_cfg.get("events", {}).get("notify_on"),
        }
    else:
        report["feishu"] = {"enabled": False}

    return report
