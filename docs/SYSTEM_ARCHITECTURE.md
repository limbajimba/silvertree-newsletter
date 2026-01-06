# SilverTree Market Intelligence System
## System Architecture Documentation

**Document Version**: 1.0
**Last Updated**: January 2026
**Classification**: Internal Use Only

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [System Overview](#2-system-overview)
3. [Pipeline Architecture](#3-pipeline-architecture)
4. [Multi-Agent Architecture](#4-multi-agent-architecture)
5. [Data Models](#5-data-models)
6. [Configuration & Operations](#6-configuration--operations)
7. [Appendix](#7-appendix)

---

## 1. Executive Summary

### Purpose

The SilverTree Market Intelligence System is an automated pipeline that monitors M&A activity, competitive movements, and market signals across SilverTree Equity's portfolio sectors. It generates weekly email newsletters with PE-grade analysis, relevance explanations, and carve-out opportunity detection.

### Key Capabilities

| Capability | Description |
|------------|-------------|
| **Automated News Collection** | Aggregates news from 7 RSS feeds + AI-powered web search |
| **Intelligent Triage** | LLM-driven categorization and relevance scoring |
| **Deep Analysis** | PE-grade strategic analysis with carve-out screening |
| **Automated Reporting** | Weekly HTML newsletter delivered via SMTP (Gmail) |

### Coverage Metrics

| Metric | Value |
|--------|-------|
| Portfolio Companies Tracked | 8 |
| Competitor Clusters | 7 |
| Competitors Monitored | 75+ |
| Data Sources | 36 (7 RSS + 29 domain searches) |
| Processing Throughput | 100-200 items/week |

### High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────┐
│                    DATA COLLECTION LAYER                            │
│  ┌─────────────┐  ┌─────────────┐  ┌─────────────────────────────┐  │
│  │  RSS Feeds  │  │  Perplexity │  │  Full-Text Content Fetcher  │  │
│  │  (7 feeds)  │  │  (AI Search)│  │  (URL extraction)           │  │
│  └──────┬──────┘  └──────┬──────┘  └──────────────┬──────────────┘  │
└─────────┼────────────────┼───────────────────────┼──────────────────┘
          │                │                       │
          ▼                ▼                       ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    PROCESSING LAYER (LangGraph)                     │
│  ┌────────┐  ┌────────┐  ┌──────────┐  ┌────────┐  ┌─────────────┐  │
│  │ Triage │→ │ Dedupe │→ │ Enrich   │→ │Analyze │→ │   Curate    │  │
│  │ Agent  │  │ Agent  │  │ Content  │  │ Agent  │  │   Filter    │  │
│  └────────┘  └────────┘  └──────────┘  └────────┘  └─────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
          │
          ▼
┌─────────────────────────────────────────────────────────────────────┐
│                    OUTPUT LAYER                                     │
│  ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────────┐  │
│  │ Email Composer  │→ │  HTML Template  │→ │   SMTP Delivery    │  │
│  │     Agent       │  │   Generation    │  │                     │  │
│  └─────────────────┘  └─────────────────┘  └─────────────────────┘  │
└─────────────────────────────────────────────────────────────────────┘
```

---

## 2. System Overview

### 2.1 Business Context

SilverTree Equity requires systematic monitoring of:

- **Portfolio company developments** — News about owned companies
- **Competitive intelligence** — Movements by competitors in each portfolio sector
- **M&A deal flow** — Industry transactions that may signal opportunities
- **Carve-out opportunities** — Non-core business units that may be available for acquisition

Manual monitoring across 8 portfolio companies and 75+ competitors is not scalable. This system automates the collection, filtering, analysis, and reporting process.

### 2.2 Technology Stack

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Orchestration** | LangGraph | Multi-stage workflow with state management |
| **LLM Provider** | Google Gemini | Triage, analysis, composition agents |
| **Search API** | Perplexity AI | AI-powered news discovery |
| **Data Validation** | Pydantic | Type-safe data models |
| **Email Delivery** | SMTP (Gmail) | Newsletter distribution |
| **Async HTTP** | httpx | Parallel content fetching |
| **RSS Parsing** | feedparser | Industry news feeds |
| **Logging** | structlog | Structured observability |

### 2.3 Key Design Principles

1. **Parallel Processing** — RSS and search collection run simultaneously
2. **Progressive Filtering** — Each stage reduces noise; expensive analysis only on relevant items
3. **PE Specialization** — Carve-out detection built into analysis prompts
4. **Rate Limiting** — Respects API quotas with exponential backoff
5. **Graceful Degradation** — Pipeline continues if individual sources fail

---

## 3. Pipeline Architecture

### 3.1 LangGraph Workflow

The system is implemented as a LangGraph state machine with conditional routing:

```
                        ┌─────────────────┐
                        │   INITIALIZE    │
                        │ Load context,   │
                        │ company data    │
                        └────────┬────────┘
                                 │
                 ┌───────────────┼───────────────┐
                 │               │               │
                 ▼               ▼               │
          ┌──────────┐   ┌──────────────┐       │
          │COLLECT   │   │COLLECT       │       │
          │RSS       │   │SEARCH        │       │
          │(parallel)│   │(parallel)    │       │
          └────┬─────┘   └──────┬───────┘       │
               │                │               │
               └────────┬───────┘               │
                        ▼                       │
                 ┌──────────────┐               │
                 │   TRIAGE     │               │
                 │  (LLM agent) │               │
                 └──────┬───────┘               │
                        │                       │
                        ▼                       │
                 ┌──────────────┐               │
                 │   DEDUPE     │               │
                 │  (LLM agent) │               │
                 └──────┬───────┘               │
                        │                       │
              ┌─────────┴─────────┐             │
              │                   │             │
     (relevant items?)    (no relevant items)   │
              │                   │             │
              ▼                   │             │
       ┌──────────────┐           │             │
       │FETCH FULL    │           │             │
       │CONTENT       │           │             │
       └──────┬───────┘           │             │
              │                   │             │
              ▼                   │             │
       ┌──────────────┐           │             │
       │   ANALYZE    │           │             │
       │  (LLM agent) │           │             │
       └──────┬───────┘           │             │
              │                   │             │
              ▼                   │             │
       ┌──────────────┐           │             │
       │   CURATE     │           │             │
       │  (filter)    │           │             │
       └──────┬───────┘           │             │
              │                   │             │
              └─────────┬─────────┘             │
                        │                       │
                        ▼                       │
                 ┌──────────────┐               │
                 │   COMPOSE    │               │
                 │  (LLM agent) │               │
                 └──────┬───────┘               │
                        │                       │
                        ▼                       │
                 ┌──────────────┐               │
                 │    SAVE      │               │
                 │ (HTML + JSON)│               │
                 └──────┬───────┘               │
                        │                       │
                        ▼                       │
                      END                       │
```

### 3.2 Stage-by-Stage Breakdown

#### Stage 1: Data Collection

**Purpose**: Aggregate raw news from multiple sources

| Source Type | Implementation | Output |
|-------------|----------------|--------|
| RSS Feeds | `RSSCollector` class | RawNewsItem objects |
| Perplexity Search | `PerplexityClient` class | RawNewsItem objects |

**RSS Collection**:
- Fetches from 7 configured feeds in parallel
- Filters items within 7-day lookback window
- Maximum 30 items per feed
- Extracts: title, summary (500 chars), URL, published date

**Perplexity Search**:
- Generates dynamic queries per company/cluster
- Query types: Portfolio, Competitor, Industry, Domain-restricted
- Rate limited: 50 RPM (Tier 0/1), exponential backoff on 429 errors
- Extracts citations as news items

#### Stage 2: Triage

**Purpose**: Fast categorization and relevance filtering

**Implementation**: `TriageAgent` (Gemini 2.5-flash)
- Processes ALL items in parallel (4 workers, 60 RPM)
- Per-item classification:

| Field | Values |
|-------|--------|
| `is_relevant` | true / false |
| `category` | portfolio, competitor, major_deal, industry, not_relevant |
| `deal_type` | ma_acquisition, ma_merger, divestiture, fundraising, ipo, partnership, product_launch, personnel_change, strategic_update, not_a_deal |
| `relevance_level` | high, medium, low |
| `related_portfolio_company` | Exact company name or null |
| `confidence` | 0-100 score |

**Filtering Rules**:
- Discards: job postings, listicles, marketing pages, educational content
- Keeps: Direct company news, competitor moves, M&A deals, strategic partnerships

#### Stage 3: Deduplication

**Purpose**: Remove duplicate stories from different sources

**Implementation**: `DedupeAgent` (Gemini-powered)
- Groups items by normalized URL (strips tracking parameters)
- Runs on triaged relevant items to reduce downstream duplication
- For duplicates, LLM selects "best" version based on:
  - Source credibility
  - Summary completeness
  - Primary vs. aggregator source

#### Stage 4: Full-Text Enrichment

**Purpose**: Extract complete article text for deeper analysis

**Implementation**: `ContentFetcher` (async HTTP)
- Fetches top 60 relevant items (prioritizes trusted domains)
- Concurrent requests: 6 max, 60 RPM rate limit
- Extracts clean text: 200-4000 characters
- Smart parsing: prioritizes `<article>` and `<main>` tags

#### Stage 5: Deep Analysis

**Purpose**: PE-grade strategic analysis with carve-out detection

**Implementation**: `AnalysisAgent` (Gemini 2.5-pro)
- Processes only RELEVANT items (3 workers, 60 RPM)
- Uses full-text content when available

**Output Fields**:

| Field | Description |
|-------|-------------|
| `why_it_matters` | 2-3 sentence summary of significance |
| `strategic_implications` | Broader market/competitive context |
| `impact_on_silvertree` | Direct relevance to portfolio |
| `competitive_threat_level` | high/medium/low (for competitor news) |
| `signal_score` | 0-100 actionability score |
| `evidence` | Key phrases supporting analysis |

**Carve-Out Screening** (for M&A deals):

| Field | Values |
|-------|--------|
| `carve_out_potential` | high, medium, low, none, n/a |
| `carve_out_target_units` | List of potential acquisition targets |
| `carve_out_rationale` | Why these units may be available |

**Carve-Out Signals Detected**:
- "Non-core" divisions mentioned explicitly
- "Rationalization" or "streamlining" language
- Product lines outside acquirer's strategic focus
- Geographic units that don't fit integration plans
- Legacy products being deprioritized

#### Stage 6: Curation

**Purpose**: Quality filtering to create high-signal newsletter

**Implementation**: Python-based filtering (no LLM)

**Filtering Logic**:

| Criterion | Threshold |
|-----------|-----------|
| Minimum signal score | 55/100 |
| Max portfolio items | 8 total, 3 per company |
| Max competitor items | 20 total, 5 per cluster |
| Max deal items | 12 total, 5 per sector |

**Exception**: Carve-out opportunities (high/medium potential) always included regardless of caps.

#### Stage 7: Newsletter Composition

**Purpose**: Assemble final newsletter with executive summary

**Implementation**: `EmailComposerAgent` (Gemini 2.5-pro)

**Tasks**:
1. Generate 3-5 sentence executive summary highlighting key themes
2. Group items into sections:
   - Portfolio Company Signals
   - Competitive Intelligence
   - Major Deals & Market Activity
   - Carve-Out Opportunities (if any)
3. Merge duplicate events across sources
4. Render HTML with SilverTree branding (green #1a5f2a)

#### Stage 8: Output & Delivery

**Purpose**: Save outputs and prepare for email

**Implementation**: File writer
- HTML file: `newsletter_YYYYMMDD_HHMMSS.html`
- JSON summary: `summary_YYYYMMDD_HHMMSS.json`

**Email Delivery** (optional):
- Provider: SMTP (Gmail)
- From: Configured sender address (Gmail)
- To: Configured recipients

---

## 4. Multi-Agent Architecture

### 4.1 Agent Overview

The system employs four specialized LLM agents, each optimized for a specific task:

```
┌─────────────────────────────────────────────────────────────────────┐
│                        AGENT ARCHITECTURE                           │
├─────────────────────────────────────────────────────────────────────┤
│                                                                     │
│  ┌───────────────┐   ┌───────────────┐   ┌───────────────────────┐  │
│  │ DEDUPE AGENT  │   │ TRIAGE AGENT  │   │    ANALYSIS AGENT     │  │
│  │               │   │               │   │                       │  │
│  │ Model: Flash  │   │ Model: Flash  │   │ Model: Pro            │  │
│  │ Speed: Fast   │   │ Speed: Fast   │   │ Speed: Moderate       │  │
│  │ Parallel: No  │   │ Parallel: Yes │   │ Parallel: Yes         │  │
│  │ Workers: 1    │   │ Workers: 4    │   │ Workers: 3            │  │
│  └───────────────┘   └───────────────┘   └───────────────────────┘  │
│                                                                     │
│  ┌─────────────────────────────────────────────────────────────┐    │
│  │                    EMAIL COMPOSER AGENT                      │    │
│  │                                                              │    │
│  │ Model: Pro    │ Speed: Moderate    │ Parallel: No           │    │
│  │                                                              │    │
│  │ Tasks: Executive summary, section assembly, HTML generation  │    │
│  └─────────────────────────────────────────────────────────────┘    │
│                                                                     │
└─────────────────────────────────────────────────────────────────────┘
```

### 4.2 Triage Agent

**Purpose**: Fast categorization to filter noise before expensive analysis

**Model**: Gemini 2.5-flash (optimized for speed)

**Input**: Single news item + portfolio context

**Output**: Structured JSON with:
- Category assignment
- Deal type classification
- Entity linking (portfolio company, competitors)
- Confidence score

**Design Rationale**: Must process 100+ items quickly. Uses cheaper/faster model. Parallel execution with 4 workers.

### 4.3 Analysis Agent

**Purpose**: In-depth PE-grade analysis for investment relevance

**Model**: Gemini 2.5-pro (optimized for quality)

**Input**: Relevant news item + full portfolio context + full-text content

**Output**: Written analysis sections including:
- "Why It Matters" (2-3 sentences)
- Strategic implications
- Carve-out assessment (for M&A deals)
- Signal strength score with evidence

**Design Rationale**: Quality over speed. Only processes pre-filtered relevant items. Uses premium model for nuanced analysis.

### 4.4 Email Composer Agent

**Purpose**: Assemble coherent newsletter from analyzed items

**Model**: Gemini 2.5-pro

**Input**: All analyzed items grouped by category

**Output**:
- Executive summary paragraph
- Structured HTML email sections
- Source attribution

**Design Rationale**: Requires synthesis across multiple items. Single invocation (not parallel).

### 4.5 Agent Prompt Design Philosophy

All agents receive:
1. **Portfolio context** — Company names, sectors, competitors for entity matching
2. **Role definition** — Clear statement of agent's specific purpose
3. **Output schema** — Exact JSON structure expected
4. **Quality guidelines** — PE-grade analysis standards, evidence requirements

---

## 5. Data Models

### 5.1 Data Flow Diagram

```
┌──────────────┐    ┌──────────────┐    ┌──────────────┐    ┌──────────────┐
│ RawNewsItem  │───▶│ TriagedItem  │───▶│ AnalyzedItem │───▶│ Newsletter   │
│              │    │              │    │              │    │   Item       │
│ • title      │    │ • raw_item   │    │ • triaged_   │    │ • headline   │
│ • summary    │    │ • is_relevant│    │   item       │    │ • summary    │
│ • source     │    │ • category   │    │ • why_it_    │    │ • impact     │
│ • source_url │    │ • deal_type  │    │   matters    │    │ • signal_    │
│ • published_ │    │ • relevance_ │    │ • strategic_ │    │   score      │
│   date       │    │   level      │    │   implic...  │    │ • sources[]  │
│ • full_text  │    │ • related_   │    │ • carve_out_ │    │              │
│              │    │   portfolio_ │    │   potential  │    │              │
│              │    │   company    │    │ • signal_    │    │              │
│              │    │ • confidence │    │   score      │    │              │
└──────────────┘    └──────────────┘    └──────────────┘    └──────────────┘
```

### 5.2 Categorization Taxonomy

#### Item Categories

| Category | Definition | Example |
|----------|------------|---------|
| `portfolio` | Direct news about SilverTree portfolio companies | "Fenergo raises $50M Series C" |
| `competitor` | News about tracked competitors | "LeanIX acquired by SAP" |
| `major_deal` | M&A/fundraising in relevant sectors | "$2B fintech merger announced" |
| `industry` | Broader sector trends | "RegTech spending up 30% YoY" |
| `not_relevant` | Filtered out | Job postings, listicles |

#### Deal Types

| Type | Description |
|------|-------------|
| `ma_acquisition` | One company acquiring another |
| `ma_merger` | Merger of equals |
| `divestiture` | Company selling business unit |
| `fundraising` | Venture/growth equity round |
| `ipo` | Public offering |
| `partnership` | Strategic alliance |
| `product_launch` | New product/feature release |
| `personnel_change` | Executive appointment/departure |
| `strategic_update` | Strategy shift announcement |
| `not_a_deal` | Not a transaction |

#### Carve-Out Potential

| Level | Criteria |
|-------|----------|
| `high` | Clear non-core unit, strategic fit for SilverTree |
| `medium` | Possible opportunity, worth monitoring |
| `low` | Unlikely but noted |
| `none` | No carve-out potential detected |
| `n/a` | Not an M&A deal |

---

## 6. Configuration & Operations

### 6.1 Environment Variables

| Variable | Purpose | Default |
|----------|---------|---------|
| `GEMINI_API_KEY` | LLM provider authentication | Required |
| `PERPLEXITY_API_KEY` | Search API authentication | Required |
| `SEND_EMAIL` | Enable SMTP delivery | `false` |
| `FROM_EMAIL` | Newsletter sender address | `newsletter@silvertree-equity.com` |
| `TO_EMAIL` | Recipients (comma-separated) | `romil@silvertree-equity.com` |
| `SMTP_HOST` | SMTP server hostname | `smtp.gmail.com` |
| `SMTP_PORT` | SMTP port | `587` |
| `SMTP_USERNAME` | SMTP username | Required |
| `SMTP_PASSWORD` | SMTP password (app password) | Required |
| `SMTP_USE_TLS` | Use STARTTLS | `true` |
| `SMTP_USE_SSL` | Use SSL | `false` |

### 6.2 Tunable Parameters

#### Collection Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `search_lookback_days` | 7 | Days of news to search |
| `rss_max_items_per_feed` | 30 | Max items from each RSS feed |
| `perplexity_max_items` | 8 | Results per search query |
| `perplexity_rpm` | 50 | Perplexity rate limit (Tier 0/1) |

#### Processing Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `triage_max_workers` | 4 | Parallel triage processors |
| `analysis_max_workers` | 3 | Parallel analysis processors |
| `llm_requests_per_minute` | 60 | Gemini rate limit |
| `max_full_text_items` | 60 | Items to fetch full text |

#### Curation Settings

| Parameter | Default | Description |
|-----------|---------|-------------|
| `min_signal_score` | 55 | Minimum score for inclusion |
| `max_portfolio_items` | 8 | Portfolio section cap |
| `max_competitor_items` | 10 | Competitive section cap |
| `max_deal_items` | 12 | Deals section cap |
| `max_items_per_company` | 3 | Per-company cap |
| `max_items_per_cluster` | 5 | Per-cluster cap |

### 6.3 Scheduling

| Setting | Default | Description |
|---------|---------|-------------|
| `newsletter_day` | Monday | Day of week for newsletter |
| `newsletter_hour` | 08:00 | Hour to send (24h format) |

### 6.4 Running the System

```bash
# Activate virtual environment
source .venv/bin/activate

# Run newsletter generation
python -m silvertree_newsletter.main

# Output location
# HTML: data/news_results/newsletter_YYYYMMDD_HHMMSS.html
# JSON: data/news_results/summary_YYYYMMDD_HHMMSS.json
```

---

## 7. Appendix

### 7.1 Technology Dependencies

```
langgraph>=0.2.0          # Workflow orchestration
langchain-google-genai    # Gemini LLM provider
pydantic>=2.0             # Data validation
httpx>=0.25               # Async HTTP client
feedparser>=6.0           # RSS parsing
structlog>=23.0           # Structured logging
smtplib (stdlib)          # SMTP email delivery
```

### 7.2 API Integrations

#### Google Gemini

| Model | Use Case | RPM Limit |
|-------|----------|-----------|
| gemini-2.5-flash | Triage, Deduplication | 60 |
| gemini-2.5-pro | Analysis, Composition | 60 |

#### Perplexity AI

| Model | Use Case | RPM Limit |
|-------|----------|-----------|
| sonar | News search | 50 (Tier 0/1), 500 (Tier 2) |

### 7.3 File Structure

```
silvertree-newsletter/
├── src/silvertree_newsletter/
│   ├── agents/
│   │   ├── triage_agent.py      # Fast categorization
│   │   ├── analysis_agent.py    # Deep analysis
│   │   ├── email_composer.py    # Newsletter assembly
│   │   └── dedupe_agent.py      # Deduplication
│   ├── services/
│   │   ├── rss_collector.py     # RSS feed parsing
│   │   ├── perplexity.py        # Search API client
│   │   └── content_fetcher.py   # Full-text extraction
│   ├── workflow/
│   │   ├── state.py             # LangGraph state schema
│   │   ├── nodes.py             # Node implementations
│   │   └── graph.py             # Workflow definition
│   ├── models/
│   │   └── schemas.py           # Pydantic data models
│   ├── config.py                # Settings management
│   └── main.py                  # Entry point
├── silvertree_companies_competitors.json  # Portfolio data
├── prompt_context.json          # LLM prompts & thresholds
├── sources_catalog.json         # Data source catalog
└── data/news_results/           # Output directory
```

### 7.4 Error Handling

| Error Type | Handling |
|------------|----------|
| RSS feed timeout | Log warning, continue with other feeds |
| Perplexity rate limit | Exponential backoff (2^attempt seconds) |
| Gemini rate limit | Queue with rate limiter |
| Content fetch failure | Skip item, use summary only |
| Empty results | Generate "no news" newsletter |

---

*Document maintained by SilverTree Technology Team*
