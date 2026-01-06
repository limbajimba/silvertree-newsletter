"""Main entry point for the SilverTree Newsletter application."""

import asyncio
import logging
import structlog

from silvertree_newsletter.config import settings
from silvertree_newsletter.workflow import run_newsletter_workflow

logger = structlog.get_logger()


def _resolve_log_level(level_name: str) -> int:
    return getattr(logging, level_name.upper(), logging.INFO)


async def run_newsletter_generation() -> None:
    """Run a single newsletter generation cycle."""
    logger.info("Starting newsletter generation")

    result = await run_newsletter_workflow()
    metrics = result.get("metrics", {})

    logger.info(
        "Newsletter generation complete",
        metrics=metrics,
        errors=result.get("errors", []),
        output_path=metrics.get("output_path"),
    )


def main() -> None:
    """Main entry point."""
    log_level = _resolve_log_level(settings.log_level)
    logging.basicConfig(level=log_level)

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

    logger.info("SilverTree Newsletter starting", debug=settings.debug)
    asyncio.run(run_newsletter_generation())


if __name__ == "__main__":
    main()
