# Carve-Out Research Agent - Email Formatting Enhancements

## Overview

The deep research carve-out agent is **fully functional end-to-end**. This document outlines the enhancements made to the email formatting to better showcase the research findings.

## Current System Architecture

### 1. Carve-Out Research Agent (`src/silvertree_newsletter/agents/carve_out_research_agent.py`)

**Purpose**: Generates comprehensive research dossiers for carve-out opportunities using Gemini API.

**Key Features**:
- Analyzes carve-out opportunities with full context from source articles
- Generates structured markdown reports with:
  - Deal Summary (2-3 sentences)
  - Deal Overview (detailed description)
  - Potential Carve-Out Assets
  - Separation Complexity (low/medium/high)
  - Separation Drivers (data, people, contracts, etc.)
  - Estimated Timeline
  - Strategic Fit Analysis
  - What SilverTree Would Do
  - Risks and Constraints
  - Diligence Questions
  - Next Steps
  - Confidence Level

**Configuration** (`src/silvertree_newsletter/config.py`):
```python
carve_out_research_enabled: bool = True
carve_out_research_model: str = "gemini-2.5-pro"
carve_out_research_max_sources: int = 4
```

### 2. Workflow Integration (`src/silvertree_newsletter/workflow/nodes.py`)

**Node: `carve_out_research_node` (line 755-814)**:
- Triggered when carve-out opportunities are identified
- Generates markdown dossier for each opportunity
- Stores report in workflow state
- Includes progress callbacks for monitoring

**Node: `compose_node` (line 821-858)**:
- Creates the newsletter email with enhanced carve-out note
- Passes carve-out data to email composer

**Node: `save_output_node` (line 865-903)**:
- Saves HTML newsletter
- Saves markdown dossier as `carveout_dossier_{timestamp}.md`

**Node: `send_email_node` (line 910-995)**:
- Sends email via SMTP
- **Attaches markdown dossier as file**

### 3. Email Composer (`src/silvertree_newsletter/agents/email_composer.py`)

**Enhanced Email Rendering** (lines 932-1004):

#### Before:
- Basic bullet-point layout
- Minimal information shown
- Generic "attached" note

#### After (Enhanced):
- **Card-based layout** with subtle borders and backgrounds
- **Prominent company headers** with priority badges
- **Structured detail rows** with labeled fields:
  - Units (with overflow indicator for 3+ items)
  - Strategic Fit rationale
  - Recommended Action
  - Source link
- **Enhanced visual hierarchy**
- **Hover effects** for better interactivity
- **Descriptive attachment note**

## Visual Design Enhancements

### CSS Improvements (lines 333-415)

#### Carve-Out Card Design
```css
.carveout-item {
    background: #FAFBFC;              /* Subtle background */
    border: 1px solid #E5E7EB;        /* Clean border */
    border-left: 4px solid #C41E3A;   /* Red accent stripe */
    padding: 18px 20px;
    transition: box-shadow 0.2s ease; /* Smooth hover */
}

.carveout-item:hover {
    box-shadow: 0 2px 8px rgba(0, 0, 0, 0.08);
}
```

#### Priority Tags
```css
.priority-high {
    background: #C41E3A;              /* SilverTree red */
    color: white;
    box-shadow: 0 2px 4px rgba(196, 30, 58, 0.2);
}

.priority-medium {
    background: #E67E22;              /* Orange */
    color: white;
    box-shadow: 0 2px 4px rgba(230, 126, 34, 0.2);
}
```

#### Detail Labels
```css
.detail-label {
    font-weight: 600;
    color: #0F2A4A;                   /* SilverTree navy */
    font-size: 12px;
    text-transform: uppercase;
    letter-spacing: 0.3px;
    min-width: 140px;                 /* Aligned columns */
}
```

#### Information Note
```css
.carveout-note {
    background: #F8F9FA;
    border-left: 3px solid #C41E3A;
    padding: 12px 16px;
    font-style: italic;
}
```

## Enhanced Attachment Note

**Location**: `src/silvertree_newsletter/workflow/nodes.py` (lines 832-840)

**Before**:
```python
"Detailed carve-out dossier attached."
```

**After**:
```python
"A comprehensive research dossier covering {N} {opportunity/opportunities} is attached. "
"Each dossier includes deal overview, separation complexity analysis, strategic fit "
"assessment, diligence questions, and recommended next steps."
```

This provides context about what's in the attachment and encourages readers to review it.

## Complete End-to-End Flow

```
1. RSS Collection → Raw News Items
   ↓
2. Triage Agent → Identifies carve-out potential
   ↓
3. Analysis Agent → Creates CarveOutOpportunity objects
   ↓
4. Carve-Out Research Agent → Generates detailed markdown dossier
   ↓
5. Email Composer → Creates HTML email with enhanced carve-out section
   ↓
6. Save Output → Saves both HTML and markdown files
   ↓
7. Send Email → Emails newsletter with attached dossier
```

## Testing

### Manual Testing Approach

To test the enhanced formatting:

1. **Run the workflow with real data**:
   ```bash
   python -m silvertree_newsletter.main
   ```

2. **Check the output directory**:
   ```bash
   ls -la output/
   # Look for:
   # - newsletter_{timestamp}.html
   # - carveout_dossier_{timestamp}.md
   ```

3. **Review the HTML in a browser**:
   ```bash
   open output/newsletter_LATEST.html
   ```

4. **Verify the markdown dossier**:
   ```bash
   cat output/carveout_dossier_LATEST.md
   ```

### What to Verify

**In the HTML Email**:
- [ ] Carve-out section appears with "Carve-Out Opportunities" header
- [ ] Red accent label for the section
- [ ] Each carve-out appears as a card with:
  - [ ] Company name in bold
  - [ ] Priority tag (HIGH/MEDIUM) with appropriate color
  - [ ] Units listed (max 3 shown inline)
  - [ ] Strategic fit rationale
  - [ ] Recommended action
  - [ ] Source link
- [ ] Hover effect works on cards
- [ ] Descriptive note about attachment appears above cards

**In the Markdown Dossier**:
- [ ] Contains all carve-out opportunities
- [ ] Each has comprehensive sections (Deal Summary, Overview, etc.)
- [ ] Proper markdown formatting
- [ ] Sources linked correctly

## Configuration Options

**Enable/Disable Research**:
```bash
# In .env file
CARVE_OUT_RESEARCH_ENABLED=true
```

**Change Model**:
```bash
CARVE_OUT_RESEARCH_MODEL=gemini-2.5-pro
```

**Adjust Sources**:
```bash
CARVE_OUT_RESEARCH_MAX_SOURCES=4
```

## Benefits of the Enhancements

1. **Better Scannability**: Card-based layout makes it easy to quickly review opportunities
2. **Clear Prioritization**: Visual priority tags immediately show what's most important
3. **More Context**: Inline display of strategic fit and recommended actions
4. **Professional Design**: Consistent with overall newsletter brand and style
5. **Actionable**: Direct links to sources and clear next steps
6. **Comprehensive**: Detailed dossier attached for deep analysis

## Next Steps (Optional Future Enhancements)

1. **Interactive Elements**: Add expandable sections in email for more details
2. **Visual Analytics**: Include charts/graphs in the dossier (separation timeline, complexity score)
3. **Executive Summary**: Add a one-sentence summary at the top of each card
4. **Confidence Indicators**: Show confidence level with visual indicator (dots/stars)
5. **Comparative Analysis**: If multiple carve-outs, show side-by-side comparison table

## Files Modified

- `src/silvertree_newsletter/agents/email_composer.py`:
  - Lines 333-415: Enhanced CSS styling
  - Lines 932-1004: Updated `_render_html` method with new carve-out layout
- `src/silvertree_newsletter/workflow/nodes.py`:
  - Lines 832-840: Improved carve-out attachment note

## Conclusion

The carve-out research agent is **fully functional** and the email formatting has been **significantly enhanced** to better showcase the research findings. The system generates comprehensive dossiers, displays them beautifully in the email, and attaches detailed reports for deeper analysis.

The enhancements maintain SilverTree's professional brand while improving information density and scannability.
