"""Portfolio context file loader.

Loads portfolio company context markdown files for deep research prompts.
These files contain detailed company information, strategic thesis,
competitive landscape, and carve-out profiles.
"""

from __future__ import annotations

import logging
from pathlib import Path

logger = logging.getLogger(__name__)


def load_portfolio_context_file(
    company_id: str,
    context_dir: str | Path | None = None,
) -> str | None:
    """Load a single portfolio company context file.

    Args:
        company_id: The company ID (e.g., "xtel", "fenergo", "orbus-software")
        context_dir: Directory containing context files. Defaults to config/portfolio_context.

    Returns:
        The markdown content of the context file, or None if not found.
    """
    if context_dir is None:
        # Default to config/portfolio_context relative to project root
        context_dir = Path(__file__).parent.parent.parent.parent / "config" / "portfolio_context"
    else:
        context_dir = Path(context_dir)

    if not context_dir.exists():
        logger.warning(f"Portfolio context directory not found: {context_dir}")
        return None

    # Normalize company_id for filename lookup
    normalized_id = company_id.lower().replace("-", "_").replace(" ", "_")

    # Try different file name variations
    possible_names = [
        f"{normalized_id}.md",
        f"{company_id.lower()}.md",
        f"{company_id.lower().replace('_', '-')}.md",
    ]

    for filename in possible_names:
        file_path = context_dir / filename
        if file_path.exists():
            try:
                content = file_path.read_text(encoding="utf-8")
                logger.debug(f"Loaded portfolio context for {company_id} from {filename}")
                return content
            except Exception as e:
                logger.error(f"Error reading portfolio context file {file_path}: {e}")
                return None

    logger.warning(f"Portfolio context file not found for company: {company_id}")
    return None


def load_all_portfolio_contexts(
    context_dir: str | Path | None = None,
) -> dict[str, str]:
    """Load all portfolio company context files.

    Args:
        context_dir: Directory containing context files. Defaults to config/portfolio_context.

    Returns:
        Dictionary mapping company_id to markdown content.
    """
    if context_dir is None:
        context_dir = Path(__file__).parent.parent.parent.parent / "config" / "portfolio_context"
    else:
        context_dir = Path(context_dir)

    if not context_dir.exists():
        logger.warning(f"Portfolio context directory not found: {context_dir}")
        return {}

    contexts: dict[str, str] = {}

    for file_path in context_dir.glob("*.md"):
        company_id = file_path.stem  # Filename without extension
        try:
            content = file_path.read_text(encoding="utf-8")
            contexts[company_id] = content
            logger.debug(f"Loaded portfolio context: {company_id}")
        except Exception as e:
            logger.error(f"Error reading portfolio context file {file_path}: {e}")

    logger.info(f"Loaded {len(contexts)} portfolio context files")
    return contexts


def get_portfolio_context_for_company(
    company_name: str,
    contexts: dict[str, str] | None = None,
    context_dir: str | Path | None = None,
) -> str | None:
    """Get portfolio context for a company by name.

    This function handles company name variations and tries to find the best match.

    Args:
        company_name: The company name (e.g., "XTEL", "Fenergo", "Orbus Software")
        contexts: Pre-loaded contexts dict. If None, loads from disk.
        context_dir: Directory containing context files.

    Returns:
        The markdown content of the context file, or None if not found.
    """
    # Normalize company name to ID format
    normalized = company_name.lower().replace(" ", "_").replace("-", "_")

    # If contexts are provided, search in them
    if contexts:
        # Try exact match first
        if normalized in contexts:
            return contexts[normalized]

        # Try partial match
        for company_id, content in contexts.items():
            if normalized in company_id or company_id in normalized:
                return content

        return None

    # Otherwise, load from file
    return load_portfolio_context_file(normalized, context_dir)


def get_relevant_portfolio_contexts(
    company_names: list[str],
    context_dir: str | Path | None = None,
) -> dict[str, str]:
    """Load portfolio contexts for a list of company names.

    Args:
        company_names: List of company names to load contexts for.
        context_dir: Directory containing context files.

    Returns:
        Dictionary mapping company names to their context content.
    """
    # Load all contexts once
    all_contexts = load_all_portfolio_contexts(context_dir)

    result: dict[str, str] = {}
    for name in company_names:
        context = get_portfolio_context_for_company(name, all_contexts)
        if context:
            result[name] = context

    return result
