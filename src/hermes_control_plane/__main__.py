from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .runner import doctor, run_pipeline, load_toml
from .server import HermesServer


def parse_args(argv: list[str]) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Hermes control-plane CLI.")
    subparsers = parser.add_subparsers(dest="command", required=True)

    doctor_cmd = subparsers.add_parser("doctor", help="Validate Hermes profile configuration.")
    doctor_cmd.add_argument("--config", type=Path, required=True)
    doctor_cmd.add_argument("--profile", default=None)

    pipeline_cmd = subparsers.add_parser("pipeline", help="Run a Hermes pipeline.")
    pipeline_cmd.add_argument("--config", type=Path, required=True)
    pipeline_cmd.add_argument("--task", type=Path, required=True)
    pipeline_cmd.add_argument("--pipeline", default="default")
    pipeline_cmd.add_argument("--profile", default=None)


    serve_cmd = subparsers.add_parser("serve", help="Start Hermes server for Feishu events.")
    serve_cmd.add_argument("--config", type=Path, required=True)
    serve_cmd.add_argument("--host", default="0.0.0.0")
    serve_cmd.add_argument("--port", type=int, default=8765)
    serve_cmd.add_argument("--mode", choices=["http", "websocket", "ws"], default="websocket",
                          help="Server mode: http (webhook+tunnel) or websocket (no tunnel needed). Default: websocket")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv or sys.argv[1:])
    if args.command == "doctor":
        report = doctor(args.config, args.profile)
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
    if args.command == "pipeline":
        run_dir = run_pipeline(args.config, args.task, args.pipeline, args.profile)
        print(f"Hermes run complete: {run_dir}")
        return 0
    if args.command == "serve":
        import logging
        logging.basicConfig(
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        )
        cfg = load_toml(args.config)
        mode = args.mode
        if mode == "ws":
            mode = "websocket"
        server = HermesServer(args.config, cfg, host=args.host, port=args.port)
        server.run(mode=mode)
        return 0
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
