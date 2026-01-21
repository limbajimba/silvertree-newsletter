# Google Deep Research Agent Implementation Summary

## Overview
Successfully implemented a Google Gemini Deep Research agent using the Interactions API to generate comprehensive, structured carve-out dossiers with PDF output for email attachment.

**Implementation Date:** January 21, 2026
**Status:** ✅ Complete

---

## Components Created

### 1. Portfolio Context Files (`config/portfolio_context/`)
**Generator Script:** `scripts/generate_portfolio_context.py`

Auto-generated 8 structured markdown files from configuration:
- `xtel.md` - CPG Trade Promotion Management
- `thesis.md` - Higher Education SIS
- `orbus_software.md` - Enterprise Architecture
- `salesmanago.md` - Marketing Automation + CDP
- `ignite_group.md` - R&D Tax Credits & Grants
- `fenergo.md` - KYC/CLM Platforms
- `tally_group.md` - Utilities Customer Systems
- `mhance.md` - Microsoft Dynamics Partners

Each file contains:
- Company overview and strategic thesis
- Competitive landscape analysis
- Ideal carve-out profile (ARR range, geography, product lines)
- Integration constraints
- Carve-out screening criteria (positive/negative signals)

**Usage:**
```bash
python scripts/generate_portfolio_context.py
```

### 2. Portfolio Context Loader (`src/silvertree_newsletter/tools/portfolio_context_files.py`)

Functions:
- `load_portfolio_context_file(company_id)` - Load single company context
- `load_all_portfolio_contexts()` - Load all contexts as dict
- `get_portfolio_context_for_company(name, contexts)` - Smart lookup with variations
- `get_relevant_portfolio_contexts(company_names)` - Batch loader

### 3. Deep Research Agent (`src/silvertree_newsletter/agents/deep_research_agent.py`)

**Key Features:**
- Uses `google.genai` Interactions API with `deep-research-pro-preview-12-2025` model
- Async background execution with polling (30s interval, 45min timeout)
- Structured JSON output schema via response_schema parameter
- Comprehensive research reports for M&A carve-out analysis

**Output Schema:**
```json
{
  "target_company_overview": {
    "name": "string",
    "description": "string",
    "ownership": "string",
    "estimated_revenue": "string"
  },
  "verified_business_units": [
    {
      "unit_name": "string",
      "products_services": "string",
      "estimated_size": "string",
      "carveout_fit": "string"
    }
  ],
  "separation_analysis": {
    "complexity": "low|medium|high|unknown",
    "drivers": ["data", "people", "contracts", ...],
    "entanglement_risks": ["risk1", "risk2", ...],
    "timeline": "string"
  },
  "strategic_fit": {
    "portfolio_company": "string",
    "thesis_alignment": "string",
    "recommendation": "string"
  },
  "comparable_deals": [
    {
      "deal": "string",
      "valuation_context": "string"
    }
  ],
  "risks": ["risk1", "risk2", ...],
  "diligence_questions": ["q1", "q2", ...],
  "next_steps": ["step1", "step2", ...],
  "confidence": "low|medium|high"
}
```

**Methods:**
- `research_carve_out(carve_out, portfolio_context)` - Single carve-out research
- `generate_report_async(carve_outs, portfolio_contexts, on_progress)` - Batch research with progress tracking

### 4. PDF Generator Service (`src/silvertree_newsletter/services/pdf_generator.py`)

**Features:**
- Uses `weasyprint` + `markdown` libraries
- SilverTree-branded styling (navy headers #0F2A4A, clean tables)
- Professional PDF layout with cover page, headers, footers
- Page numbering and confidentiality footer

**Functions:**
- `markdown_to_html(content)` - Convert markdown to HTML
- `markdown_to_pdf(content, output_path, title)` - Generate styled PDF
- `generate_carveout_pdf(content, output_dir, timestamp)` - Generate timestamped PDF
- `html_to_pdf(html_content, output_path, title)` - Direct HTML to PDF conversion

**Styling:**
- SilverTree navy (#0F2A4A) for headers and branding
- Alert red (#C41E3A) for priority indicators
- Professional serif font (Georgia) for body text
- Sans-serif (Helvetica Neue) for headers and labels
- Tables with alternating row colors
- Responsive page breaks

### 5. Configuration Updates (`src/silvertree_newsletter/config.py`)

New settings added:
```python
# Deep Research (Google Gemini Interactions API)
carve_out_deep_research_enabled: bool = True
deep_research_poll_interval: int = 30  # seconds
deep_research_max_wait_minutes: int = 45
deep_research_high_priority_only: bool = True  # Cost optimization
portfolio_context_dir: str = "config/portfolio_context"
```

**Environment Variables (.env.example):**
```bash
CARVE_OUT_DEEP_RESEARCH_ENABLED=true
DEEP_RESEARCH_POLL_INTERVAL=30
DEEP_RESEARCH_MAX_WAIT_MINUTES=45
DEEP_RESEARCH_HIGH_PRIORITY_ONLY=true
PORTFOLIO_CONTEXT_DIR=config/portfolio_context
```

### 6. Workflow Integration (`src/silvertree_newsletter/workflow/`)

**State Updates (`state.py`):**
```python
carve_out_research_pdf_path: str | None  # PDF dossier path
carve_out_deep_research_data: list[dict]  # Structured research data
```

**Node Updates (`nodes.py`):**

1. **`carve_out_research_node` (now async):**
   - Filters to high-priority carve-outs when deep research enabled
   - Loads portfolio contexts from markdown files
   - Calls `DeepResearchCarveOutAgent.generate_report_async()`
   - Falls back to standard `CarveOutResearchAgent` if deep research fails
   - Returns structured data and markdown report

2. **`save_output_node`:**
   - Saves markdown report
   - Generates PDF via `generate_carveout_pdf()`
   - Returns PDF path for email attachment

3. **`send_email_node`:**
   - Attaches PDF to email (prefers PDF over markdown)
   - Falls back to markdown if PDF generation fails

4. **`compose_node`:**
   - Updates carve-out note to mention "PDF dossier" or "research report"
   - Includes attachment notice in email body

### 7. Email Updates

**Carve-Out Display (`agents/email_composer.py`):**
- Existing carve-out section already well-formatted
- Enhanced with PDF attachment notice via compose_node
- Summary includes:
  - Target company with priority badge
  - Potential business units (top 3)
  - Strategic fit rationale
  - Recommended action
  - Source links

**Email Attachment:**
- PDF dossier automatically attached when available
- Fallback to markdown if PDF generation fails
- Note in email body: "A comprehensive PDF dossier covering X opportunities is attached"

---

## Dependencies Added

**pyproject.toml:**
```toml
"weasyprint>=62.0",
"markdown>=3.5.0",
```

**Installation:**
```bash
pip install weasyprint markdown
```

---

## Implementation Flow

```
Carve-Out Opportunities Identified
           ↓
Filter to High-Priority (if configured)
           ↓
Load Portfolio Context Files
           ↓
Deep Research Agent (async)
   - Create interaction with deep-research-pro model
   - Send research prompt with portfolio context
   - Poll every 30s (max 45 min)
   - Parse structured JSON response
           ↓
Generate Markdown Report
           ↓
Generate PDF from Markdown
           ↓
Attach PDF to Email
```

---

## Report Format (Concise & Structured)

Each carve-out entry includes:
- **Header:** Company name, priority badge, confidence level
- **Target Overview:** Description, ownership, revenue (3-4 bullets)
- **Verified Business Units:** Bulleted list with size/fit (max 5)
- **Separation Analysis:** Table (complexity, drivers, timeline) + entanglement risks
- **Strategic Fit:** Portfolio company, thesis alignment, recommendation
- **Comparable Deals:** 2-3 recent deals with valuation context
- **Key Risks:** Bulleted (max 5)
- **Diligence Questions:** Bulleted (max 5)
- **Next Steps:** Bulleted (max 3)
- **Sources:** Links to original articles
- **Confidence Level:** Low/Medium/High

---

## Cost Considerations

**Deep Research API Pricing:**
- Estimated cost: $2-5 per deep research task
- Weekly cost (1-3 high-priority carve-outs): $5-15/week
- Annual cost estimate: ~$250-780/year

**Cost Optimization:**
- `DEEP_RESEARCH_HIGH_PRIORITY_ONLY=true` - Only research high-priority opportunities
- Fallback to standard research if deep research fails
- No cost incurred for standard research (uses existing Gemini Pro calls)

---

## Verification Plan

✅ 1. **Unit test** portfolio context loading
✅ 2. **Test** deep research agent with single carve-out (manual run)
✅ 3. **Test** PDF generation from sample markdown
⏳ 4. **End-to-end test** full workflow with `--dry-run` flag
⏳ 5. **Verify** email attachment arrives correctly

---

## Usage Instructions

### Generate Portfolio Context Files
```bash
python scripts/generate_portfolio_context.py
```

### Run Newsletter Workflow
```bash
# With deep research enabled (default)
python -m silvertree_newsletter.main

# Disable deep research (use standard research only)
CARVE_OUT_DEEP_RESEARCH_ENABLED=false python -m silvertree_newsletter.main

# High-priority carve-outs only (default)
DEEP_RESEARCH_HIGH_PRIORITY_ONLY=true python -m silvertree_newsletter.main
```

### Test PDF Generation
```python
from silvertree_newsletter.services.pdf_generator import markdown_to_pdf

content = """
# Test Dossier
## Company Overview
Test content here...
"""

markdown_to_pdf(
    content=content,
    output_path="test_dossier.pdf",
    title="Test Carve-Out Dossier"
)
```

---

## Design Decisions

1. **Research Scope:** High-priority carve-outs only by default (cost optimization)
2. **Context Files:** Auto-generate from existing JSON config (single source of truth)
3. **Output Format:** PDF attachment + summary in email body (professional + scannable)
4. **Fallback Strategy:** Standard research if deep research fails (reliability)
5. **Async Execution:** Background polling for deep research (non-blocking)
6. **Structured Output:** JSON schema enforcement for consistent data extraction

---

## File Structure

```
silvertree-newsletter/
├── config/
│   ├── portfolio_context/           # ✨ NEW
│   │   ├── xtel.md
│   │   ├── thesis.md
│   │   ├── orbus_software.md
│   │   ├── salesmanago.md
│   │   ├── ignite_group.md
│   │   ├── fenergo.md
│   │   ├── tally_group.md
│   │   └── mhance.md
│   ├── silvertree_companies_competitors.json
│   └── prompt_context.json
├── scripts/
│   └── generate_portfolio_context.py  # ✨ NEW
├── src/silvertree_newsletter/
│   ├── agents/
│   │   ├── deep_research_agent.py     # ✨ NEW
│   │   ├── carve_out_research_agent.py
│   │   └── email_composer.py          # ✅ Updated
│   ├── services/
│   │   ├── pdf_generator.py           # ✨ NEW
│   │   └── email_sender.py
│   ├── tools/
│   │   ├── portfolio_context_files.py # ✨ NEW
│   │   └── prompt_context_loader.py
│   ├── workflow/
│   │   ├── nodes.py                   # ✅ Updated
│   │   └── state.py                   # ✅ Updated
│   └── config.py                      # ✅ Updated
├── .env.example                       # ✅ Updated
├── pyproject.toml                     # ✅ Updated
└── DEEP_RESEARCH_IMPLEMENTATION.md    # ✨ NEW (this file)
```

---

## Next Steps

1. **Test Deep Research Integration:**
   ```bash
   # Run with a test carve-out scenario
   python test_deep_research.py
   ```

2. **Generate Sample PDF:**
   ```bash
   python -c "from silvertree_newsletter.services.pdf_generator import generate_carveout_pdf; \
   generate_carveout_pdf('# Test\\n\\nSample content', 'data', 'test_20260121')"
   ```

3. **End-to-End Workflow Test:**
   ```bash
   SEND_EMAIL=false python -m silvertree_newsletter.main
   ```

4. **Review Generated Outputs:**
   - Check `data/carveout_dossier_*.md` for markdown report
   - Check `data/carveout_dossier_*.pdf` for PDF output
   - Verify PDF styling and branding

5. **Monitor Costs:**
   - Track deep research API usage in Gemini console
   - Adjust `DEEP_RESEARCH_HIGH_PRIORITY_ONLY` if needed
   - Consider adding budget alerts

---

## Troubleshooting

### PDF Generation Fails
**Issue:** `weasyprint package not available - cannot generate PDF`

**Solution:**
```bash
pip install weasyprint
# On macOS, may need additional dependencies:
brew install cairo pango gdk-pixbuf libffi
```

### Deep Research Times Out
**Issue:** Research exceeds 45-minute timeout

**Solution:**
- Increase `DEEP_RESEARCH_MAX_WAIT_MINUTES` in .env
- Or reduce complexity of research prompt
- Or fall back to standard research

### No Portfolio Context Found
**Issue:** `Portfolio context file not found for company: xtel`

**Solution:**
```bash
# Regenerate portfolio context files
python scripts/generate_portfolio_context.py
```

### Deep Research API Errors
**Issue:** Gemini API errors or rate limits

**Solution:**
- Check `GEMINI_API_KEY` is valid
- Verify API quota and billing in Google Cloud Console
- Reduce concurrent requests if rate-limited
- Falls back to standard research automatically

---

## Future Enhancements

1. **Enhanced Deep Research:**
   - Add web search results to prompt context
   - Include financial data from public sources
   - Integrate with deal databases (Pitchbook, Crunchbase)

2. **PDF Improvements:**
   - Add charts and visualizations
   - Include company logos
   - Generate comparison tables across multiple carve-outs

3. **Cost Optimization:**
   - Cache research results for similar companies
   - Implement incremental research (update existing dossiers)
   - Add cost tracking and reporting

4. **Interactive Features:**
   - Generate interactive HTML dossiers
   - Add clickable source references
   - Include embedded videos/presentations

---

## Success Criteria

✅ **Implemented:**
- [x] Portfolio context files auto-generated
- [x] Deep research agent with Interactions API
- [x] Structured JSON output parsing
- [x] PDF generation with SilverTree branding
- [x] Email attachment integration
- [x] Workflow integration with fallback
- [x] Cost optimization (high-priority only)
- [x] Configuration and documentation

⏳ **To Verify:**
- [ ] End-to-end workflow test
- [ ] Email attachment delivery
- [ ] PDF rendering quality
- [ ] Deep research accuracy
- [ ] Cost monitoring

---

## References

- [Google Gemini Interactions API Documentation](https://ai.google.dev/api/interactions)
- [WeasyPrint Documentation](https://doc.courtbouillon.org/weasyprint/)
- [Python Markdown Documentation](https://python-markdown.github.io/)
- SilverTree Equity Investment Thesis (Internal)
- Carve-Out Screening Playbooks (Internal)

---

**Implementation Complete:** ✅ January 21, 2026
