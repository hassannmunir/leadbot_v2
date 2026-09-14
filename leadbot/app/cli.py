"""Command-line application composition."""

from __future__ import annotations

import argparse
import time

from dotenv import load_dotenv

from leadbot.app.config import build_runtime, load_config, validate_queries
from leadbot.app.pipeline import LeadPipeline
from leadbot.app.progress import format_duration, overall_progress, report


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="LeadBot: free, compliant local-business lead collector"
    )
    parser.add_argument("--config", default="config.json")
    return parser


def run(config_path: str) -> None:
    """Run all configured queries using shared runtime services."""
    load_dotenv()
    started_at = time.perf_counter()
    report(1, "Starting up...")
    config = load_config(config_path)
    queries = validate_queries(config)
    guard, quota, niche_map, storage = build_runtime(config)
    pipeline = LeadPipeline(config, guard, quota, niche_map, storage)

    total_added = 0
    try:
        for query_index, query in enumerate(queries):
            def progress_callback(fraction: float, message: str, index=query_index) -> None:
                report(overall_progress(index, len(queries), fraction), message)

            total_added += pipeline.collect_for_query(query, progress_callback)
    except KeyboardInterrupt:
        elapsed = format_duration(time.perf_counter() - started_at)
        report(100, f"Stopped by user. {total_added} new lead(s) were already saved before stopping.")
        print(f"Run summary: runtime {elapsed}; new leads saved {total_added}.", flush=True)
        return

    elapsed = format_duration(time.perf_counter() - started_at)
    report(100, f"Done. {total_added} new lead(s) added across all queries this run.")
    print(f"Run summary: runtime {elapsed}; new leads saved {total_added}.", flush=True)


def main() -> None:
    args = build_parser().parse_args()
    run(args.config)
