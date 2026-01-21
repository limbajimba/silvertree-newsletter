# Implementation Plan: Executive Summary Bullets + Deep Research Agent

## Issue 1: Executive Summary Not Multi-Bulleted

### Root Cause
In `email_composer.py`, the `FULL_COMPOSE_PROMPT` (line 91) specifies:
```
"executive_summary": "3-5 sentences"
```

This tells the LLM to return a paragraph, not bullet points. The `_format_executive_summary_as_list()` function (line 1187) can handle bullets, but the LLM isn't producing them.

### Fix
Update `FULL_COMPOSE_PROMPT` line 91 to request bullet points:
```python
"executive_summary": "3-5 bullet points, each starting with • character, one actionable insight per bullet"
```

**File:** `src/silvertree_newsletter/agents/email_composer.py`
**Line:** ~91

---

## Issue 2: Deep Research Agent for Carve-Out Analysis

### Current State
The `CarveOutResearchAgent` (carve_out_research_agent.py):
- Only uses data from already-collected news items
- No active web search capability
- Just reformats existing data into markdown
- Produces shallow analysis because it lacks real research

### Proposed Architecture: Deep Research Agent

#### Design Principles
1. **Active Research** - Use Perplexity API to search for information about target companies
2. **Multi-Query Strategy** - Generate 4-6 targeted queries per carve-out opportunity
3. **Rich Context** - Provide sector playbooks and SilverTree portfolio thesis
4. **Structured Output** - Verified units, separation analysis, strategic fit

#### Implementation Plan

##### Step 1: Create Research Query Builder
Add a new tool `tools/carveout_query_builder.py` that generates targeted search queries:

```python
def build_carveout_research_queries(
    target_company: str,
    potential_units: list[str],
    sector: str | None = None,
) -> list[SearchQuery]:
    """Generate research queries for a carve-out opportunity."""
    queries = []

    # Company structure queries
    queries.append(f"{target_company} business units divisions segments structure")
    queries.append(f"{target_company} organizational structure subsidiaries")

    # Financial/size queries
    queries.append(f"{target_company} revenue breakdown by segment products")
    queries.append(f"{target_company} market share industry position")

    # For each potential unit
    for unit in potential_units[:3]:
        queries.append(f"{target_company} {unit} competitors market size")

    # M&A history
    queries.append(f"{target_company} acquisition history M&A deals")

    # Ownership
    queries.append(f"{target_company} ownership private equity investors")

    return queries
```

##### Step 2: Enhance CarveOutResearchAgent with Perplexity Integration

Modify `agents/carve_out_research_agent.py`:

```python
@dataclass
class CarveOutResearchAgent:
    """Generate a detailed carve-out research dossier with active web research."""

    gemini_api_key: str
    perplexity_api_key: str  # NEW
    model: str = "gemini-2.5-pro"
    perplexity_model: str = "sonar"
    requests_per_minute: int = 0
    max_sources: int = 20
    max_full_text_chars: int = 4000
    max_research_queries: int = 6  # NEW: queries per carve-out

    async def research_company(
        self,
        target_company: str,
        potential_units: list[str],
        sector: str | None,
    ) -> dict:
        """Active research using Perplexity."""
        queries = build_carveout_research_queries(target_company, potential_units, sector)

        client = PerplexityClient(
            api_key=self.perplexity_api_key,
            model=self.perplexity_model,
            recency_filter="month",  # Broader timeframe for research
        )

        research_results = {}
        for query in queries[:self.max_research_queries]:
            results = await client.search(SearchQuery(query_text=query))
            research_results[query] = results

        return self._synthesize_research(research_results)
```

##### Step 3: Enhanced Dossier Generation Prompt

Update `CARVE_OUT_RESEARCH_SYSTEM_PROMPT` to be more comprehensive:

```python
CARVE_OUT_RESEARCH_SYSTEM_PROMPT = """You are a senior private equity associate preparing a carve-out research dossier.

## Your Research Sources:
1. News articles about the deal (provided)
2. Active web research about the target company (provided)
3. SilverTree sector playbook and carve-out criteria (provided)

## Analysis Framework:
Use the carve-out screening heuristics:
- Strong positive signals: seller is conglomerate doing portfolio pruning, "non-core" language, distinct P&L units
- Strong negative signals: single-product company, operational entanglement, regulatory complexity

## Required Output (JSON):
{
  "deal_summary": "2-3 sentences about the deal",
  "target_company_overview": {
    "description": "What the company does",
    "ownership": "Current owner(s), PE/strategic",
    "estimated_size": "Revenue/employees if available"
  },
  "verified_business_units": [
    {
      "unit_name": "Name",
      "products_services": ["list"],
      "markets_geographies": ["list"],
      "estimated_size": "ARR/revenue/employees if known",
      "carve_out_fit": "Why this unit fits SilverTree thesis"
    }
  ],
  "separation_analysis": {
    "complexity": "low|medium|high",
    "key_drivers": ["data", "people", "contracts", "infrastructure", "regulatory"],
    "entanglement_risks": ["specific risks"],
    "estimated_timeline_months": "range"
  },
  "strategic_fit_assessment": {
    "relevant_portfolio_company": "Which SilverTree company this relates to",
    "thesis_alignment": "How this fits portfolio company thesis",
    "what_silvertree_would_do": "bolt-on|platform add-on|stand-alone"
  },
  "valuation_context": {
    "comparable_deals": ["recent deals in the space"],
    "market_multiples": "if available"
  },
  "risks": ["key risks"],
  "diligence_questions": ["specific questions to validate"],
  "recommended_next_steps": ["actions"],
  "confidence": "low|medium|high",
  "research_gaps": ["what we couldn't find"]
}
"""
```

##### Step 4: Update Workflow Node

Modify `carve_out_research_node` in `workflow/nodes.py`:

```python
async def carve_out_research_node(state: NewsletterState) -> dict:
    """Generate deep research dossiers for carve-out opportunities."""
    from silvertree_newsletter.agents.carve_out_research_agent import CarveOutResearchAgent

    carve_outs = state.get("carve_out_opportunities", [])
    if not carve_outs or not settings.carve_out_research_enabled:
        return {"carve_out_research_report": None}

    # Load context
    prompt_context = load_prompt_context(...)
    companies, _ = load_company_context(...)

    agent = CarveOutResearchAgent(
        gemini_api_key=settings.gemini_api_key,
        perplexity_api_key=settings.perplexity_api_key,  # Reuse existing key
        model=settings.carve_out_research_model,
        requests_per_minute=settings.llm_requests_per_minute,
    )

    # Generate dossiers with active research
    report = await agent.generate_report_async(
        carve_outs,
        context_builder=build_context,
        on_progress=progress,
    )

    return {"carve_out_research_report": report}
```

##### Step 5: Enhanced Context Builder

Update `build_carveout_context_for_research()` in `prompt_context_loader.py` to include:

```python
def build_carveout_context_for_research(
    portfolio_company: str | None,
    competitors: list[str],
    prompt_context: dict,
) -> str:
    """Build rich context for carve-out research."""
    lines = []

    # 1. Global carve-out heuristics
    lines.append("## Carve-Out Screening Heuristics")
    positives = carveout.get("strong_positive_signals")
    negatives = carveout.get("strong_negative_signals")

    # 2. Portfolio company thesis (if matched)
    if matched_company:
        lines.append(f"## SilverTree Portfolio Company: {company.name}")
        lines.append(f"Core Thesis: {company.core_thesis}")
        lines.append(f"Strategic Priority: {company.current_strategic_priority}")

    # 3. Sector-specific ideal carve-out profile
    if sector_playbook:
        lines.append("## Ideal Carve-Out Profile for This Sector")
        lines.append(f"Asset Type: {ideal.asset_type}")
        lines.append(f"Size Preference: {ideal.size_preference}")
        lines.append(f"Product Lines of Interest: {ideal.product_lines_of_interest}")
        lines.append(f"Integration Constraints: {ideal.integration_constraints}")

    return "\n".join(lines)
```

#### Implementation Order

1. **Quick Fix (5 min):** Fix executive summary bullet points in `email_composer.py`

2. **Phase 1 - Query Builder:** Create `tools/carveout_query_builder.py` with query generation logic

3. **Phase 2 - Async Agent:** Refactor `CarveOutResearchAgent` to be async and integrate Perplexity

4. **Phase 3 - Enhanced Prompt:** Update system prompt for comprehensive dossier generation

5. **Phase 4 - Context Enhancement:** Enhance `build_carveout_context_for_research()` with portfolio thesis

6. **Phase 5 - Workflow Update:** Make `carve_out_research_node` async

#### Config Changes Needed

Add to `config.py`:
```python
carve_out_research_max_queries: int = 6
carve_out_research_lookback_days: int = 30
```

#### Expected Output Improvement

**Before (current dossier):**
```
## Anthology (high priority)
- Deal headline: Ellucian acquires Anthology
- Potential units: Learning Management System, CRM Solutions
- Initial rationale: ...

### Deal Summary
unknown

### Potential Carve-Out Assets
- unknown
```

**After (deep research dossier):**
```
## Anthology (high priority)
- Deal headline: Ellucian acquires Anthology
- Verified units: 14 identified business units

### Target Company Overview
Anthology is a leading provider of EdTech solutions formed through the merger of
Campus Management and Blackboard. Owned by Veritas Capital and Providence Equity.
Estimated revenue: $800M+ ARR across multiple product lines.

### Verified Business Units
1. **Blackboard Learn (LMS)**
   - Products: Blackboard Learn Ultra, Blackboard Original
   - Markets: Higher Ed (3,000+ institutions), K-12, Corporate
   - Estimated size: ~$300M ARR
   - Carve-out fit: Strong fit for EdTech-focused PE; competes with Canvas

2. **Student Success & Retention**
   - Products: Starfish, Student Affairs
   - Markets: US Higher Ed primarily
   - Estimated size: ~$80M ARR
   - Carve-out fit: Adjacent to SIS space, could bolt onto Thesis

3. **CRM & Advancement**
   - Products: Encompass CRM, Anthology Fundraising
   - Markets: Higher Ed advancement offices
   - Estimated size: ~$60M ARR
   - Carve-out fit: Potential standalone or bolt-on

### Separation Analysis
- Complexity: HIGH
- Key drivers: Shared infrastructure, common identity layer, intermingled contracts
- Entanglement risks: Single sign-on across products, bundled enterprise deals
- Timeline: 12-18 months for clean separation

### Strategic Fit Assessment
- Relevant portfolio company: Thesis (Higher Ed SIS)
- Thesis alignment: LMS/Student Success modules could strengthen Thesis value prop
- Recommendation: Pursue Student Success module as bolt-on

### Valuation Context
- Comparable: Instructure (Canvas) sold for $2B (6x revenue)
- Market multiples: EdTech 4-7x ARR depending on growth

### Diligence Questions
1. What % of contracts are bundled multi-product deals?
2. Can Student Success be separated from core SIS integration?
3. What is customer overlap between LMS and SIS products?
```

---

## Summary of Changes

| File | Change |
|------|--------|
| `email_composer.py:91` | Change "3-5 sentences" to bullet format |
| `carve_out_research_agent.py` | Add Perplexity integration, async methods |
| `tools/carveout_query_builder.py` | NEW: Query generation for research |
| `tools/prompt_context_loader.py` | Enhance context with portfolio thesis |
| `workflow/nodes.py` | Make carve_out_research_node async |
| `config.py` | Add new settings for research |

