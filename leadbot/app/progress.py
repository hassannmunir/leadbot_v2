"""Progress reporting shared by the CLI and browser UI."""

from __future__ import annotations

from collections.abc import Callable

ProgressCallback = Callable[[float, str], None]


def report(progress: int, message: str) -> None:
    """Emit the machine-readable progress format consumed by the UI."""
    print(f"PROGRESS {max(0, min(100, int(progress)))} {message}", flush=True)


def overall_progress(query_index: int, total_queries: int, fraction: float) -> int:
    """Map one query's 0-1 progress into the overall 5-95 run range."""
    if total_queries <= 0:
        return 5
    return int(5 + 90 * (query_index + fraction) / total_queries)


def format_duration(seconds: float) -> str:
    """Format elapsed seconds as a compact human-readable duration."""
    total_seconds = max(0, int(seconds))
    hours, remainder = divmod(total_seconds, 3600)
    minutes, seconds = divmod(remainder, 60)
    if hours:
        return f"{hours}h {minutes}m {seconds}s"
    if minutes:
        return f"{minutes}m {seconds}s"
    return f"{seconds}s"
