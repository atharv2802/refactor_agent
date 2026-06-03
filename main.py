"""CLI entry point.

    python main.py text  --claims sample_claims.json
    python main.py eval  [--scenario NAME] [--verbose]
    python main.py server [--host 0.0.0.0] [--port 8000]
    python main.py parse-837 sample_claim.837

Run from the repository root so the ``server`` and ``evals`` packages import.
"""

from __future__ import annotations

import argparse
import json
import logging
import sys


def _cmd_text(args: argparse.Namespace) -> int:
    from server.text_mode import run_text_mode

    run_text_mode(args.claims)
    return 0


def _cmd_eval(args: argparse.Namespace) -> int:
    from evals.runner import run_evals

    ok = run_evals(scenario=args.scenario, verbose=args.verbose)
    return 0 if ok else 1


def _cmd_server(args: argparse.Namespace) -> int:
    import uvicorn

    uvicorn.run(
        "server.app:app", host=args.host, port=args.port, reload=args.reload
    )
    return 0


def _cmd_parse_837(args: argparse.Namespace) -> int:
    from pathlib import Path

    from server.edi import parse_837

    claims = parse_837(Path(args.path).read_text(encoding="utf-8"))
    print(json.dumps([c.model_dump() for c in claims], indent=2, default=str))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Claim Status Voice Agent")
    parser.add_argument(
        "--log-level", default="WARNING", help="Python log level (default WARNING)."
    )
    sub = parser.add_subparsers(dest="command", required=True)

    p_text = sub.add_parser("text", help="Interactive terminal conversation.")
    p_text.add_argument("--claims", default="sample_claims.json")
    p_text.set_defaults(func=_cmd_text)

    p_eval = sub.add_parser("eval", help="Run scripted evaluation scenarios.")
    p_eval.add_argument("--scenario", default=None, help="Run a single scenario by name.")
    p_eval.add_argument("--verbose", action="store_true", help="Print full transcripts.")
    p_eval.set_defaults(func=_cmd_eval)

    p_server = sub.add_parser("server", help="Run the FastAPI voice/web server.")
    p_server.add_argument("--host", default="0.0.0.0")
    p_server.add_argument("--port", type=int, default=8000)
    p_server.add_argument("--reload", action="store_true")
    p_server.set_defaults(func=_cmd_server)

    p_parse = sub.add_parser("parse-837", help="Parse an 837 file to ClaimInfo JSON.")
    p_parse.add_argument("path")
    p_parse.set_defaults(func=_cmd_parse_837)

    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    logging.basicConfig(
        level=getattr(logging, args.log_level.upper(), logging.WARNING),
        format="%(levelname)s %(name)s: %(message)s",
    )
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
