# SilverTree Newsletter

Automated M&A and Market Signals Tracking Tool for SilverTree Equity.

## Overview

This tool continuously monitors market activity relevant to SilverTree Equity portfolio companies and their competitors. It collects and summarizes key signals weekly and delivers them as an email newsletter.

## Features

- **Portfolio & Competitor Tracking**: Monitors SilverTree portfolio companies and their competitors
- **Multi-Source News Collection**: Aggregates from industry RSS feeds and Perplexity search (including GP Bullhound via domain filtering)
- **AI-Powered Analysis**: Uses LLMs to analyze relevance and impact of news items
- **Carve-out Detection**: Automatically identifies potential carve-out opportunities from M&A deals
- **Weekly Newsletter**: Generates comprehensive weekly summaries (email sending TBD)

## Setup

1. Create and activate virtual environment:
```bash
python3 -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
```

2. Install dependencies:
```bash
pip install -e ".[dev]"
```

3. Configure environment:
```bash
cp .env.example .env
# Edit .env with your API keys
```

4. Run the newsletter generator:
```bash
python -m silvertree_newsletter.main
```

## Configuration

Configure the application via environment variables in `.env`:

- `GEMINI_API_KEY`: LLM provider API key (Gemini)
- `SENDGRID_API_KEY`: For sending emails
- `TO_EMAIL`: Newsletter recipient email
- `PERPLEXITY_API_KEY`: For search aggregation
- `SOURCES_CATALOG_PATH`: Unified source list (RSS + domains)
- See `.env.example` for all options

## Architecture

Built with:
- **LangGraph**: Workflow orchestration
- **Pydantic**: Data validation and settings
- **SendGrid**: Email delivery

## Workflow

1. Load portfolio companies and competitors
2. Collect news from configured sources
3. Triage for relevance
4. Fetch full-text for relevant items
5. Analyze news for relevance and impact
6. Detect carve-out opportunities
7. Generate newsletter content
8. Send email via SendGrid (future)

## Development

Run tests:
```bash
pytest
```

Code formatting and linting:
```bash
ruff check .
ruff format .
mypy .
```
