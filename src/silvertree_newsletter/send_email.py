"""Send an existing HTML newsletter via SMTP."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from silvertree_newsletter.config import settings
from silvertree_newsletter.services.email_sender import SmtpEmailSender


def _split_emails(value: str) -> list[str]:
    if not value:
        return []
    cleaned = value.replace(";", ",")
    return [email.strip() for email in cleaned.split(",") if email.strip()]


def _read_html(path: Path) -> str:
    try:
        return path.read_text(encoding="utf-8")
    except FileNotFoundError:
        raise
    except Exception as exc:  # pragma: no cover - unexpected decode issues
        raise RuntimeError(f"Failed to read HTML: {exc}") from exc


def _build_subject(path: Path, provided: str | None) -> str:
    if provided:
        return provided
    return f"SilverTree Newsletter (Test): {path.stem}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Send an existing HTML newsletter via SMTP.",
    )
    parser.add_argument(
        "html_path",
        help="Path to the HTML file to send.",
    )
    parser.add_argument(
        "--subject",
        default="",
        help="Override email subject (optional).",
    )
    parser.add_argument(
        "--to",
        dest="to_email",
        default="",
        help="Override recipients (comma-separated).",
    )
    parser.add_argument(
        "--from",
        dest="from_email",
        default="",
        help="Override sender address.",
    )
    parser.add_argument(
        "--reply-to",
        dest="reply_to",
        default="",
        help="Optional reply-to address.",
    )
    parser.add_argument(
        "--force",
        action="store_true",
        help="Send even if SEND_EMAIL is false.",
    )
    args = parser.parse_args()

    if not settings.send_email and not args.force:
        print("SEND_EMAIL is false. Set SEND_EMAIL=true or pass --force.", file=sys.stderr)
        return 2

    html_path = Path(args.html_path)
    if not html_path.exists():
        print(f"HTML file not found: {html_path}", file=sys.stderr)
        return 2

    try:
        html = _read_html(html_path)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 2

    from_email = (args.from_email or settings.from_email).strip()
    to_emails = _split_emails(args.to_email or settings.to_email)
    if not from_email or not to_emails:
        print("FROM_EMAIL or TO_EMAIL not configured.", file=sys.stderr)
        return 2

    if not settings.smtp_username or not settings.smtp_password:
        print("SMTP credentials missing. Set SMTP_USERNAME/SMTP_PASSWORD.", file=sys.stderr)
        return 2

    sender = SmtpEmailSender(
        host=settings.smtp_host,
        port=settings.smtp_port,
        username=settings.smtp_username,
        password=settings.smtp_password,
        use_tls=settings.smtp_use_tls,
        use_ssl=settings.smtp_use_ssl,
        timeout_seconds=settings.smtp_timeout_seconds,
    )

    result = sender.send_html(
        subject=_build_subject(html_path, args.subject),
        html=html,
        from_email=from_email,
        to_emails=to_emails,
        reply_to=args.reply_to or None,
    )

    if result.success:
        print(f"Email sent to {len(to_emails)} recipient(s).")
        return 0

    print(f"Email send failed: {result.error or 'unknown error'}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
