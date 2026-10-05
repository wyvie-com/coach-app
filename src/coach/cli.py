"""Command line entry point. Thin on purpose: parse, call a module, print counts or statuses."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from coach import credentials, settings
from coach.hevy.client import HevyClient, HevyError
from coach.hevy.pull import format_summary, pull
from coach.hevy.store import PullStore

#: Pull directories are named by the local date of the pull.
LOCAL_ZONE = ZoneInfo("Australia/Melbourne")


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


def _pull(args: argparse.Namespace) -> int:
    client = HevyClient(settings.hevy_credential(), page_size=args.page_size)
    try:
        summary = pull(client, PullStore(args.root), today=datetime.now(LOCAL_ZONE).date())
    except HevyError as exc:
        print(f"pull failed: {exc}", file=sys.stderr)
        return 1
    finally:
        client.close()
    print(format_summary(summary))
    return 0


def build_parser() -> argparse.ArgumentParser:
    """Build the parser. Subcommands are added slice by slice."""
    parser = argparse.ArgumentParser(prog="coach", description="A personal AI training coach.")
    sub = parser.add_subparsers(dest="command", required=True)
    check = sub.add_parser(
        "check-credentials",
        help="One request to each API; prints HTTP statuses and the Hevy route, nothing else.",
    )
    check.set_defaults(func=_check_credentials)
    pull_cmd = sub.add_parser(
        "pull", help="Fetch every workout page from Hevy into private/hevy/<date>/; prints counts."
    )
    pull_cmd.add_argument("--root", type=Path, default=Path("private/hevy"))
    pull_cmd.add_argument("--page-size", type=int, default=10, help="1 to 10 (Hevy's maximum)")
    pull_cmd.set_defaults(func=_pull)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
