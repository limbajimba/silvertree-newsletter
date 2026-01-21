# SilverTree Newsletter

Automated M&A and Market Signals Tracking Tool for SilverTree Equity.

## Overview

This tool continuously monitors market activity relevant to SilverTree Equity portfolio companies and their competitors. It collects and summarizes key signals weekly and delivers them as an email newsletter.

## Features

- **Portfolio & Competitor Tracking**: Monitors SilverTree portfolio companies and their competitors
- **Multi-Source News Collection**: Aggregates from industry RSS feeds and Perplexity search (including GP Bullhound via domain filtering)
- **AI-Powered Analysis**: Uses LLMs to analyze relevance and impact of news items
- **Carve-out Detection**: Automatically identifies potential carve-out opportunities from M&A deals
- **Carve-Out Dossiers**: Optional deep-research dossiers for carve-outs, attached to the email
- **Weekly Newsletter**: Generates comprehensive weekly summaries and emails via SMTP (Gmail)

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

To send an existing HTML file (test without running the pipeline):
```bash
python -m silvertree_newsletter.send_email data/news_results/newsletter_YYYYMMDD_HHMMSS.html
```

## Configuration

Configure the application via environment variables in `.env`:

- `GEMINI_API_KEY`: LLM provider API key (Gemini)
- `SEND_EMAIL`: Enable/disable SMTP email sending
- `FROM_EMAIL`: Sender email (Gmail)
- `TO_EMAIL`: Newsletter recipient email(s), comma-separated
- `SMTP_USERNAME` / `SMTP_PASSWORD`: Gmail SMTP credentials (app password recommended)
- `SMTP_HOST` / `SMTP_PORT`: SMTP server connection settings
- `SMTP_USE_TLS`: Enable STARTTLS (recommended)
- `PERPLEXITY_API_KEY`: For search aggregation
- `SOURCES_CATALOG_PATH`: Unified source list (RSS + domains)
- See `.env.example` for all options

### Email Configuration (Gmail)

To send newsletters via Gmail, you need to configure SMTP with an **App Password**:

1. **Enable 2-Factor Authentication**:
   - Go to https://myaccount.google.com/security
   - Enable 2-Step Verification if not already enabled

2. **Generate Gmail App Password**:
   - Go to https://myaccount.google.com/apppasswords
   - Select "Mail" as the app
   - Select "Other" as the device and name it "SilverTree Newsletter"
   - Click "Generate"
   - Copy the 16-character password (e.g., `abcd efgh ijkl mnop`)

3. **Update `.env` file**:
   ```bash
   SEND_EMAIL=true
   FROM_EMAIL=your-email@gmail.com
   TO_EMAIL=recipient@example.com
   SMTP_HOST=smtp.gmail.com
   SMTP_PORT=587
   SMTP_USERNAME=your-email@gmail.com
   SMTP_PASSWORD=abcdefghijklmnop  # 16-character App Password (no spaces)
   SMTP_USE_TLS=true
   SMTP_USE_SSL=false
   ```

**Note**: The system uses `certifi` for SSL certificate verification to ensure secure SMTP connections work correctly on all platforms (especially macOS).

## Architecture

Built with:
- **LangGraph**: Workflow orchestration
- **Pydantic**: Data validation and settings
- **SMTP (Gmail)**: Email delivery

## Workflow

1. Load portfolio companies and competitors
2. Collect news from configured sources
3. Triage for relevance
4. Fetch full-text for relevant items
5. Analyze news for relevance and impact
6. Detect carve-out opportunities
7. Generate carve-out research dossier (optional)
8. Generate newsletter content
9. Send email via SMTP (Gmail)

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
