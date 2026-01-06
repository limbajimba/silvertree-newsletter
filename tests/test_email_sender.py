from unittest.mock import patch

from silvertree_newsletter.services.email_sender import SmtpEmailSender


def test_send_html_uses_tls_and_login() -> None:
    sender = SmtpEmailSender(
        host="smtp.gmail.com",
        port=587,
        username="user@example.com",
        password="app-password",
        use_tls=True,
        use_ssl=False,
    )

    with patch("silvertree_newsletter.services.email_sender.smtplib.SMTP") as smtp_cls:
        smtp = smtp_cls.return_value.__enter__.return_value
        result = sender.send_html(
            subject="Test Subject",
            html="<p>Hello</p>",
            from_email="from@example.com",
            to_emails=["to@example.com"],
        )

    assert result.success is True
    smtp.starttls.assert_called_once()
    smtp.login.assert_called_once_with("user@example.com", "app-password")
    smtp.send_message.assert_called_once()


def test_send_html_requires_credentials() -> None:
    sender = SmtpEmailSender(
        host="smtp.gmail.com",
        port=587,
        username="",
        password="",
        use_tls=True,
        use_ssl=False,
    )

    result = sender.send_html(
        subject="Test Subject",
        html="<p>Hello</p>",
        from_email="from@example.com",
        to_emails=["to@example.com"],
    )

    assert result.success is False
    assert result.error is not None
