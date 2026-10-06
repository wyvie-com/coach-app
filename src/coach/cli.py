"""Command line entry point. Thin on purpose: parse, call a module, print counts or statuses."""

from __future__ import annotations

import argparse
import sys
from collections.abc import Sequence
from datetime import datetime
from pathlib import Path
from zoneinfo import ZoneInfo

from coach import credentials, settings
from coach.evals.batch import BatchRunner
from coach.evals.cases import CASES
from coach.evals.checks import run_data_checks
from coach.evals.harness import ensure_credentials, estimate_usd, run_eval
from coach.evals.report import render_markdown as render_eval
from coach.evals.rescore import rescore
from coach.figures import format_table, week_figures
from coach.hevy.client import HevyClient, HevyError
from coach.hevy.pull import format_summary, pull
from coach.hevy.store import PullStore
from coach.model import WeekId, Workout, from_raw_pages
from coach.review.client import build_client
from coach.review.loop import run_review
from coach.review.output import render_markdown, write_run

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


def _load(args: argparse.Namespace) -> tuple[list[Workout], WeekId, str] | None:
    """Workouts from the latest pull and the requested week, or None with a message printed."""
    store = PullStore(args.root)
    pulled = store.latest()
    if pulled is None:
        print(f"no pull found under {args.root}; run `coach pull` first", file=sys.stderr)
        return None
    today = datetime.now(LOCAL_ZONE).date()
    week = WeekId.parse(args.week) if args.week else WeekId.of_date(today).shift(-1)
    return from_raw_pages(store.read_pages(pulled)), week, pulled.isoformat()


def _figures(args: argparse.Namespace) -> int:
    loaded = _load(args)
    if loaded is None:
        return 1
    workouts, week, pulled = loaded
    figures = week_figures(workouts, week)
    print(f"pull {pulled}  workouts {len(workouts)}")
    print(format_table(figures))
    print()
    print(figures.model_dump_json(indent=2))
    return 0


def _review(args: argparse.Namespace) -> int:
    loaded = _load(args)
    if loaded is None:
        return 1
    workouts, week, pulled = loaded
    try:
        client = build_client(settings.anthropic_api_key())
    except settings.MissingCredentialError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    model = args.model or settings.review_model()
    figures = week_figures(workouts, week)
    run = run_review(client, model, figures, workouts)
    checks = run_data_checks(figures, run, workouts)
    directory = write_run(args.out, figures, run, checks)
    print(f"pull {pulled}  week {week}  model {model}")
    print(render_markdown(figures, run, checks))
    print(f"written to {directory}")
    return 0 if run.outcome == "ok" else 1


def _rescore(args: argparse.Namespace) -> int:
    print(rescore(args.trials, allow_differences=not args.strict_grounding).render())
    return 0


def _eval(args: argparse.Namespace) -> int:
    try:
        client = build_client(settings.anthropic_api_key())
        ensure_credentials(client)
    except (settings.MissingCredentialError, RuntimeError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    cases = CASES
    if args.cases:
        wanted = set(args.cases.split(","))
        cases = [c for c in CASES if c.name in wanted]
        unknown = wanted - {c.name for c in cases}
        if unknown:
            print(f"unknown cases: {', '.join(sorted(unknown))}", file=sys.stderr)
            return 1
    models = args.model or [settings.review_model()]
    estimate = estimate_usd(cases=len(cases), trials=args.trials, models=len(models))
    if args.batch:
        estimate *= 0.5
    print(
        f"estimated spend about ${estimate:.2f} for {len(cases)} cases x {args.trials} trials "
        f"x {len(models)} model(s)"
        + ("; Message Batches at half price" if args.batch else "")
        + (f"; budget cap ${args.budget_usd:.2f}" if args.budget_usd is not None else "")
    )
    runner = (
        BatchRunner(client.messages.batches, poll_seconds=args.poll_seconds, log=print)
        if args.batch
        else None
    )
    stamp = datetime.now(LOCAL_ZONE).strftime("%Y%m%dT%H%M%S")
    out_dir = args.out / stamp
    report = run_eval(
        cases=cases,
        models=models,
        trials=args.trials,
        review_client=lambda _model: client,
        grader_client=client,
        grader_model=args.grader_model,
        out_dir=out_dir,
        log=print,
        budget_usd=args.budget_usd,
        batch=runner,
    )
    print()
    print(render_eval(report).split("## Cases")[0])
    print(f"written to {out_dir}")
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
    figures_cmd = sub.add_parser(
        "figures", help="Compute one ISO week's figures from the latest pull; no model call."
    )
    figures_cmd.add_argument("--week", help="ISO week such as 2026-W40; default is last week")
    figures_cmd.add_argument("--root", type=Path, default=Path("private/hevy"))
    figures_cmd.add_argument(
        "--dry-run",
        action="store_true",
        help="Accepted for symmetry with the brief; figures never call a model.",
    )
    figures_cmd.set_defaults(func=_figures)
    review_cmd = sub.add_parser(
        "review", help="Have Claude review one ISO week; writes out/<week>/ and prints the review."
    )
    review_cmd.add_argument("--week", help="ISO week such as 2026-W40; default is last week")
    review_cmd.add_argument(
        "--model", help=f"Model id; default COACH_MODEL or {settings.DEFAULT_MODEL}"
    )
    review_cmd.add_argument("--root", type=Path, default=Path("private/hevy"))
    review_cmd.add_argument("--out", type=Path, default=Path("out"))
    review_cmd.set_defaults(func=_review)
    eval_cmd = sub.add_parser(
        "eval", help="Run the evaluation suite; writes out/eval/<timestamp>/."
    )
    eval_cmd.add_argument(
        "--model",
        action="append",
        help="Review model; repeat for a side-by-side report. Default: COACH_MODEL or Haiku.",
    )
    eval_cmd.add_argument("--trials", type=int, default=3)
    eval_cmd.add_argument("--grader-model", default=settings.DEFAULT_MODEL)
    eval_cmd.add_argument("--cases", help="Comma-separated case names; default all sixteen")
    eval_cmd.add_argument("--out", type=Path, default=Path("out/eval"))
    eval_cmd.add_argument(
        "--budget-usd",
        type=float,
        help="Stop after the trial that takes the run's spend past this.",
    )
    eval_cmd.add_argument(
        "--batch",
        action="store_true",
        help="Run through the Message Batches API: half price, results in rounds, no hurry",
    )
    eval_cmd.add_argument(
        "--poll-seconds", type=float, default=30.0, help="How often to check a batch (default 30)"
    )
    eval_cmd.set_defaults(func=_eval)
    rescore_cmd = sub.add_parser(
        "rescore", help="Re-run the code checks over a stored trials.jsonl; no model call."
    )
    rescore_cmd.add_argument("trials", type=Path)
    rescore_cmd.add_argument(
        "--strict-grounding",
        action="store_true",
        help="Score kg_grounded as it was before differences were allowed.",
    )
    rescore_cmd.set_defaults(func=_rescore)
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    """Run the CLI and return the exit code."""
    args = build_parser().parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    sys.exit(main())
