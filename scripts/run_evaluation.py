import argparse
import asyncio
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_settings
from db.session import get_session_factory, init_db
from evaluation.engine import EvaluationEngine, EvaluationSummary
from llm.client import GeminiClient

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("run_evaluation")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Run an LLM4IAS evaluation pass from the CLI."
    )
    parser.add_argument(
        "--run-name",
        default="cli_run",
        help="Human-readable label for this evaluation run.",
    )
    parser.add_argument(
        "--scenario-tag",
        default=None,
        help="Filter test cases to this scenario_tag.",
    )
    parser.add_argument(
        "--max-cases",
        type=int,
        default=None,
        help="Maximum number of test cases to evaluate.",
    )
    parser.add_argument(
        "--sop-only",
        action="store_true",
        default=False,
        help="Only evaluate SOP tasks.",
    )
    parser.add_argument(
        "--unexpected-only",
        action="store_true",
        default=False,
        help="Only evaluate unexpected tasks.",
    )
    parser.add_argument(
        "--no-reasons",
        action="store_true",
        default=False,
        help="Skip Gemini-as-judge plausibility scoring (faster).",
    )
    return parser.parse_args()


def print_summary(summary: EvaluationSummary) -> None:
    

    def fmt_pct(v: float | None) -> str:
        return f"{v * 100:.1f}%" if v is not None else "N/A"

    def fmt_score(v: float | None) -> str:
        return f"{v:.2f}/5.00" if v is not None else "N/A"

    print()
    print("=" * 60)
    print(f"  Evaluation Run: {summary.run_name}")
    print(f"  Model:          {summary.model_name}")
    print(f"  Run ID:         {summary.run_id}")
    print("=" * 60)
    print(f"  Total cases:      {summary.total_cases}")
    print(f"  SOP cases:        {summary.sop_cases}")
    print(f"  Unexpected cases: {summary.unexpected_cases}")
    print(f"  Parse failures:   {summary.parse_failure_count}")
    print()
    print("  ── Correctness Rate (Table II, Metric 1) ──────────────")
    print(f"  All:        {fmt_pct(summary.correctness_rate_all)}")
    print(f"  SOP:        {fmt_pct(summary.correctness_rate_sop)}")
    print(f"  Unexpected: {fmt_pct(summary.correctness_rate_unexpected)}")
    print()
    print("  ── Reason Plausibility (Table II, Metric 2) ───────────")
    print(f"  All:        {fmt_score(summary.avg_reason_plausibility_all)}")
    print(f"  SOP:        {fmt_score(summary.avg_reason_plausibility_sop)}")
    print(f"  Unexpected: {fmt_score(summary.avg_reason_plausibility_unexpected)}")
    print("=" * 60)
    print(f"  Results saved to DB (run_id={summary.run_id})")
    print()


async def main() -> None:
    args = parse_args()
    settings = get_settings()

    if not settings.gemini_api_key:
        logger.error(
            "GEMINI_API_KEY is not set. Add it to .env or set the environment variable."
        )
        sys.exit(1)


    sop_only: bool | None = None
    if args.sop_only and args.unexpected_only:
        logger.error("--sop-only and --unexpected-only are mutually exclusive.")
        sys.exit(1)
    elif args.sop_only:
        sop_only = True
    elif args.unexpected_only:
        sop_only = False

    logger.info("Connecting to database...")
    init_db(settings.database_url, echo=False)

    try:
        llm_client = GeminiClient()
    except (ValueError, ImportError) as exc:
        logger.error("Failed to initialise GeminiClient: %s", exc)
        sys.exit(1)

    engine = EvaluationEngine(
        llm_client=llm_client,
        session_factory=get_session_factory(),
    )

    logger.info(
        "Starting evaluation run '%s' (scenario=%s, max=%s, sop_only=%s, "
        "score_reasons=%s).",
        args.run_name, args.scenario_tag, args.max_cases,
        sop_only, not args.no_reasons,
    )

    summary = await engine.run_evaluation(
        run_name=args.run_name,
        scenario_tag=args.scenario_tag,
        sop_only=sop_only,
        max_cases=args.max_cases,
        score_reasons=not args.no_reasons,
    )

    print_summary(summary)


if __name__ == "__main__":
    asyncio.run(main())
