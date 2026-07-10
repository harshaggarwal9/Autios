"""
scripts/export_dataset.py
──────────────────────────
CLI script to export the accumulated DatasetRecord rows to JSONL or CSV,
without needing a running FastAPI server.

Paper connection (§IV — Dataset Creation):
  Produces the training dataset 𝒟 in JSONL format (one prompt/completion
  pair per line) ready for direct use with:
    - HuggingFace Trainer:  datasets.load_dataset("json", data_files="...")
    - OpenAI fine-tuning:   minor key renaming (prompt→messages, etc.)
    - Vertex AI:            compatible with supervised tuning input format

Usage:
    python scripts/export_dataset.py [OPTIONS]

Options (all optional):
    --format        jsonl|csv       Export format (default: jsonl)
    --output        PATH            Output file path (default: stdout)
    --scenario-tag  STR             Filter to a specific scenario_tag
    --sop-only                      Export SOP tasks only
    --unexpected-only               Export unexpected tasks only
    --limit         INT             Max records to export
    --stats                         Print dataset statistics and exit

Examples:
    python scripts/export_dataset.py --stats
    python scripts/export_dataset.py --output dataset.jsonl
    python scripts/export_dataset.py --format csv --output dataset.csv
    python scripts/export_dataset.py --scenario-tag inspection_station --sop-only
    python scripts/export_dataset.py --limit 100 --output sample.jsonl
"""

import argparse
import asyncio
import json
import logging
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from config.settings import get_settings
from dataset.exporter import DatasetExporter
from db.session import get_session_factory, init_db

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-8s %(name)s: %(message)s",
)
logger = logging.getLogger("export_dataset")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Export the LLM4IAS dataset to JSONL or CSV."
    )
    parser.add_argument(
        "--format",
        choices=["jsonl", "csv"],
        default="jsonl",
        help="Export format (default: jsonl).",
    )
    parser.add_argument(
        "--output",
        default=None,
        help="Output file path. Omit to write to stdout.",
    )
    parser.add_argument(
        "--scenario-tag",
        default=None,
        help="Filter to a specific scenario_tag.",
    )
    parser.add_argument(
        "--sop-only",
        action="store_true",
        default=False,
        help="Export SOP tasks only.",
    )
    parser.add_argument(
        "--unexpected-only",
        action="store_true",
        default=False,
        help="Export unexpected tasks only.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=None,
        help="Maximum number of records to export.",
    )
    parser.add_argument(
        "--stats",
        action="store_true",
        default=False,
        help="Print dataset statistics and exit without exporting.",
    )
    return parser.parse_args()


def print_stats(stats: dict) -> None:
    print()
    print("=" * 50)
    print("  Dataset Statistics")
    print("=" * 50)
    print(f"  Total records:      {stats['total_records']}")
    print(f"  SOP records:        {stats['sop_records']}")
    print(f"  Unexpected records: {stats['unexpected_records']}")
    print()
    print("  Task type breakdown:")
    for task_type, count in stats["task_type_counts"].items():
        print(f"    {task_type:<30} {count}")
    print()
    print("  Scenario tag breakdown:")
    for tag, count in stats["scenario_tag_counts"].items():
        print(f"    {tag:<30} {count}")
    print("=" * 50)
    print(f"  Exported at: {stats['exported_at']}")
    print()


async def main() -> None:
    args = parse_args()

    if args.sop_only and args.unexpected_only:
        logger.error("--sop-only and --unexpected-only are mutually exclusive.")
        sys.exit(1)

    sop_only: bool | None = None
    if args.sop_only:
        sop_only = True
    elif args.unexpected_only:
        sop_only = False

    settings = get_settings()
    logger.info("Connecting to database...")
    init_db(settings.database_url, echo=False)

    exporter = DatasetExporter()

    async with get_session_factory()() as db:

        # ── Stats mode ─────────────────────────────────────────────────────────
        if args.stats:
            stats = await exporter.export_stats(db)
            print_stats(stats)
            return

        # ── Export mode ────────────────────────────────────────────────────────
        logger.info(
            "Exporting dataset (format=%s, scenario=%s, sop_only=%s, limit=%s)...",
            args.format, args.scenario_tag, sop_only, args.limit,
        )

        if args.format == "jsonl":
            content = await exporter.export_jsonl(
                db,
                scenario_tag=args.scenario_tag,
                sop_only=sop_only,
                limit=args.limit,
            )
            record_count = len([l for l in content.splitlines() if l.strip()])
        else:
            content = await exporter.export_csv(
                db,
                scenario_tag=args.scenario_tag,
                sop_only=sop_only,
                limit=args.limit,
            )
            # Subtract 1 for header row
            record_count = max(0, len(content.splitlines()) - 1)

    if args.output:
        output_path = Path(args.output)
        output_path.write_text(content, encoding="utf-8")
        logger.info(
            "Exported %d record(s) to '%s' (%s format).",
            record_count, output_path, args.format,
        )
    else:
        sys.stdout.write(content)
        sys.stdout.flush()
        logger.info(
            "Exported %d record(s) to stdout (%s format).",
            record_count, args.format,
        )


if __name__ == "__main__":
    asyncio.run(main())