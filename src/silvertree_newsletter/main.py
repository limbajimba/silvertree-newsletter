"""Main entry point for the SilverTree Newsletter application."""

import asyncio
import argparse
import logging
import structlog
from datetime import datetime

from silvertree_newsletter.config import settings
from silvertree_newsletter.workflow import run_newsletter_workflow

logger = structlog.get_logger()


def _resolve_log_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


async def run_newsletter_generation(thread_id: str = "default", resume: bool = False) -> None:
    """Run a single newsletter generation cycle.

    Args:
        thread_id: Unique identifier for this workflow run
        resume: If True, resume from last checkpoint; if False, start fresh
    """
    logger.info("Starting newsletter generation", thread_id=thread_id, resume=resume)

    result = await run_newsletter_workflow(thread_id=thread_id, resume=resume)
    metrics = result.get("metrics", {})

    logger.info(
        "Newsletter generation complete",
        metrics=metrics,
        errors=result.get("errors", []),
        output_path=metrics.get("output_path"),
    )


def main() -> None:
    """Main entry point."""
    parser = argparse.ArgumentParser(description="SilverTree Newsletter Generator")
    parser.add_argument(
        "--resume",
        action="store_true",
        help="Resume from last checkpoint instead of starting fresh",
    )
    parser.add_argument(
        "--thread-id",
        default=None,
        help="Thread ID for this workflow run. Default: 'latest' when using --resume, timestamped otherwise",
    )
    args = parser.parse_args()

    # Determine thread_id based on resume flag
    if args.thread_id is not None:
        thread_id = args.thread_id
    elif args.resume:
        # Use consistent thread_id for resume to find previous checkpoint
        thread_id = "latest"
    else:
        # Fresh run with timestamped id (or use "latest" if you want to overwrite)
        thread_id = "latest"  # Using "latest" allows easy resume without specifying thread_id
    args.thread_id = thread_id

    log_level = _resolve_log_level(settings.log_level)
    logging.basicConfig(level=log_level)

    # Suppress verbose Google SDK and httpx logging
    logging.getLogger("google_genai.models").setLevel(logging.WARNING)
    logging.getLogger("httpx").setLevel(logging.WARNING)

    structlog.configure(
        processors=[
            structlog.stdlib.filter_by_level,
            structlog.stdlib.add_logger_name,
            structlog.stdlib.add_log_level,
            structlog.processors.TimeStamper(fmt="iso"),
            structlog.dev.ConsoleRenderer(),
        ],
        wrapper_class=structlog.stdlib.BoundLogger,
        context_class=dict,
        logger_factory=structlog.stdlib.LoggerFactory(),
        cache_logger_on_first_use=True,
    )

    logger.info("SilverTree Newsletter starting", debug=settings.debug, thread_id=args.thread_id, resume=args.resume)
    asyncio.run(run_newsletter_generation(thread_id=args.thread_id, resume=args.resume))


if __name__ == "__main__":
    main()
