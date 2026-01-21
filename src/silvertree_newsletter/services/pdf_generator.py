"""PDF Generator Service using WeasyPrint.

Generates SilverTree-branded PDF dossiers from markdown content.
"""

from __future__ import annotations

import logging
from datetime import datetime
from pathlib import Path

logger = logging.getLogger(__name__)


# SilverTree-branded PDF stylesheet
SILVERTREE_PDF_CSS = """
@page {
    size: A4;
    margin: 2cm 2.5cm;
    @top-right {
        content: "SilverTree Equity - Carve-Out Dossier";
        font-family: 'Helvetica Neue', Arial, sans-serif;
        font-size: 9pt;
        color: #666;
    }
    @bottom-center {
        content: "Page " counter(page) " of " counter(pages);
        font-family: 'Helvetica Neue', Arial, sans-serif;
        font-size: 9pt;
        color: #666;
    }
    @bottom-right {
        content: "Confidential";
        font-family: 'Helvetica Neue', Arial, sans-serif;
        font-size: 9pt;
        color: #C41E3A;
    }
}

body {
    font-family: 'Georgia', 'Times New Roman', serif;
    font-size: 11pt;
    line-height: 1.6;
    color: #1a1a1a;
}

h1 {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    color: #0F2A4A;
    font-size: 24pt;
    font-weight: 700;
    margin-top: 0;
    margin-bottom: 20pt;
    padding-bottom: 10pt;
    border-bottom: 3px solid #0F2A4A;
}

h2 {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    color: #0F2A4A;
    font-size: 16pt;
    font-weight: 600;
    margin-top: 24pt;
    margin-bottom: 12pt;
    padding-bottom: 6pt;
    border-bottom: 1px solid #d0d0d0;
    page-break-after: avoid;
}

h3 {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    color: #333;
    font-size: 12pt;
    font-weight: 600;
    margin-top: 16pt;
    margin-bottom: 8pt;
    page-break-after: avoid;
}

h4 {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    color: #444;
    font-size: 11pt;
    font-weight: 600;
    margin-top: 12pt;
    margin-bottom: 6pt;
}

p {
    margin-top: 0;
    margin-bottom: 10pt;
    text-align: justify;
}

ul, ol {
    margin-top: 0;
    margin-bottom: 12pt;
    padding-left: 24pt;
}

li {
    margin-bottom: 6pt;
}

table {
    width: 100%;
    border-collapse: collapse;
    margin: 16pt 0;
    font-size: 10pt;
}

th {
    background-color: #0F2A4A;
    color: white;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-weight: 600;
    text-align: left;
    padding: 10pt 12pt;
    border: 1px solid #0F2A4A;
}

td {
    padding: 8pt 12pt;
    border: 1px solid #d0d0d0;
    vertical-align: top;
}

tr:nth-child(even) {
    background-color: #f8f9fa;
}

strong, b {
    font-weight: 600;
    color: #0F2A4A;
}

em, i {
    font-style: italic;
}

a {
    color: #0F2A4A;
    text-decoration: none;
}

a:hover {
    text-decoration: underline;
}

code {
    font-family: 'Monaco', 'Consolas', monospace;
    font-size: 9pt;
    background-color: #f4f4f4;
    padding: 2pt 4pt;
    border-radius: 3pt;
}

pre {
    background-color: #f4f4f4;
    padding: 12pt;
    border-radius: 4pt;
    font-size: 9pt;
    overflow-x: auto;
    white-space: pre-wrap;
}

hr {
    border: none;
    border-top: 1px solid #d0d0d0;
    margin: 20pt 0;
}

blockquote {
    border-left: 4px solid #0F2A4A;
    margin: 16pt 0;
    padding: 12pt 16pt;
    background-color: #f8f9fa;
    font-style: italic;
}

.priority-high {
    color: #C41E3A;
    font-weight: 600;
}

.priority-medium {
    color: #E67E22;
    font-weight: 600;
}

.confidence-high {
    color: #27AE60;
}

.confidence-medium {
    color: #E67E22;
}

.confidence-low {
    color: #C41E3A;
}

.section-header {
    background-color: #0F2A4A;
    color: white;
    padding: 8pt 12pt;
    margin: 16pt 0 12pt 0;
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 11pt;
    font-weight: 600;
    text-transform: uppercase;
    letter-spacing: 1pt;
}

.callout {
    background-color: #FEF3E7;
    border-left: 4px solid #E67E22;
    padding: 12pt 16pt;
    margin: 16pt 0;
}

.callout-alert {
    background-color: #FBEAEA;
    border-left: 4px solid #C41E3A;
}

.callout-success {
    background-color: #E8F5E9;
    border-left: 4px solid #27AE60;
}

.cover-page {
    text-align: center;
    padding-top: 40%;
}

.cover-title {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 32pt;
    font-weight: 700;
    color: #0F2A4A;
    margin-bottom: 16pt;
}

.cover-subtitle {
    font-family: 'Helvetica Neue', Arial, sans-serif;
    font-size: 14pt;
    color: #666;
    text-transform: uppercase;
    letter-spacing: 2pt;
}

.cover-date {
    font-family: 'Georgia', serif;
    font-size: 12pt;
    color: #888;
    margin-top: 24pt;
}

.toc {
    page-break-after: always;
}

.toc h2 {
    border-bottom: none;
}

.toc ul {
    list-style: none;
    padding-left: 0;
}

.toc li {
    margin-bottom: 8pt;
    padding-bottom: 8pt;
    border-bottom: 1px dotted #d0d0d0;
}

.toc a {
    text-decoration: none;
}
"""


def markdown_to_html(content: str) -> str:
    """Convert markdown content to HTML.

    Args:
        content: Markdown content string

    Returns:
        HTML string
    """
    try:
        import markdown
        from markdown.extensions.tables import TableExtension
        from markdown.extensions.fenced_code import FencedCodeExtension
        from markdown.extensions.toc import TocExtension

        md = markdown.Markdown(
            extensions=[
                TableExtension(),
                FencedCodeExtension(),
                TocExtension(permalink=False),
                "markdown.extensions.nl2br",
            ]
        )
        html = md.convert(content)
        return html
    except ImportError:
        logger.warning("markdown package not available, returning raw content in pre tags")
        return f"<pre>{content}</pre>"


def markdown_to_pdf(
    content: str,
    output_path: str | Path,
    title: str = "Carve-Out Research Dossier",
) -> bool:
    """Convert markdown content to PDF with SilverTree branding.

    Args:
        content: Markdown content to convert
        output_path: Path for the output PDF file
        title: Document title for the cover page

    Returns:
        True if successful, False otherwise
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        logger.error("weasyprint package not available - cannot generate PDF")
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Convert markdown to HTML
    html_content = markdown_to_html(content)

    # Build full HTML document
    now = datetime.now()
    full_html = f"""
    <!DOCTYPE html>
    <html>
    <head>
        <meta charset="utf-8">
        <title>{title}</title>
    </head>
    <body>
        <div class="cover-page">
            <div class="cover-title">SilverTree Equity</div>
            <div class="cover-subtitle">{title}</div>
            <div class="cover-date">{now.strftime('%B %d, %Y')}</div>
        </div>
        <div style="page-break-before: always;"></div>
        {html_content}
    </body>
    </html>
    """

    try:
        html_doc = HTML(string=full_html)
        css = CSS(string=SILVERTREE_PDF_CSS)
        html_doc.write_pdf(str(output_path), stylesheets=[css])
        logger.info(f"Generated PDF: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        return False


def generate_carveout_pdf(
    content: str,
    output_dir: str | Path,
    timestamp: str | None = None,
) -> str | None:
    """Generate a timestamped carve-out dossier PDF.

    Args:
        content: Markdown content for the dossier
        output_dir: Directory to save the PDF
        timestamp: Optional timestamp string (defaults to current time)

    Returns:
        Path to the generated PDF, or None if generation failed
    """
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True)

    if timestamp is None:
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")

    output_path = output_dir / f"carveout_dossier_{timestamp}.pdf"

    success = markdown_to_pdf(
        content=content,
        output_path=output_path,
        title="Carve-Out Research Dossier",
    )

    if success:
        return str(output_path)
    return None


def html_to_pdf(
    html_content: str,
    output_path: str | Path,
    title: str = "Document",
) -> bool:
    """Convert HTML content directly to PDF.

    Args:
        html_content: HTML content to convert
        output_path: Path for the output PDF file
        title: Document title

    Returns:
        True if successful, False otherwise
    """
    try:
        from weasyprint import HTML, CSS
    except ImportError:
        logger.error("weasyprint package not available - cannot generate PDF")
        return False

    output_path = Path(output_path)
    output_path.parent.mkdir(parents=True, exist_ok=True)

    # Wrap content in full HTML document if needed
    if not html_content.strip().lower().startswith("<!doctype") and not html_content.strip().lower().startswith("<html"):
        html_content = f"""
        <!DOCTYPE html>
        <html>
        <head>
            <meta charset="utf-8">
            <title>{title}</title>
        </head>
        <body>
            {html_content}
        </body>
        </html>
        """

    try:
        html_doc = HTML(string=html_content)
        css = CSS(string=SILVERTREE_PDF_CSS)
        html_doc.write_pdf(str(output_path), stylesheets=[css])
        logger.info(f"Generated PDF: {output_path}")
        return True
    except Exception as e:
        logger.error(f"Failed to generate PDF: {e}")
        return False
