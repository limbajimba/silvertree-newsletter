# Configuration Files

This directory contains all configuration and reference data files for the SilverTree Market Intelligence System.

## Files

| File | Purpose |
|------|---------|
| `silvertree_companies_competitors.json` | Portfolio companies and competitor cluster definitions |
| `prompt_context.json` | LLM prompt templates and relevance scoring thresholds |
| `sources_catalog.json` | RSS feeds, domain sources, and trusted domains catalog |
| `sources_catalog.min.json` | Minified version of sources catalog |
| `COMPANIES_AND_COMPETITORS.md` | Human-readable reference of tracking scope |

## Usage

These files are loaded by the application at runtime via `config.py`. Paths are configurable via environment variables.

**Note**: No sensitive data (API keys, credentials) should be stored in these files. Use `.env` for secrets.
