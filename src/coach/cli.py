"""Command line entry point. Thin on purpose: parse, call a module, print counts or statuses."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence

from coach import credentials, settings


def _check_credentials(_: argparse.Namespace) -> int:
    results: list[credentials.CheckResult] = []
    try:
        client = credentials.build_anthropic_client(settings.anthropic_api_key())
    except settings.MissingCredentialError as exc:
        results.append(credentials.CheckResult("anthropic", None, str(exc)))
    else:
        results.append(credentials.check_anthropic(client))
    results.append(credentials.check_hevy(settings.hevy_credential()))
    print(credentials.render(results))
    return 0 if all(r.ok for r in results) else 1


def build_parser() -> argparse.ArgumentParser:
    """Build the parser. Subcommands are added slice by slice."""
    parser = argparse.ArgumentParser(prog="coach", description="A personal AI training coach.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser(
        "check-credentials",
        help="One request to each API; prints HTTP statuses and the Hevy route, nothing else.",
    )
    check.set_defaults(func=_check_credentials)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
