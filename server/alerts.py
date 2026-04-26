"""
Alert system — notifies on pipeline failures or important events.

Supports Slack webhook and/or email (SendGrid).
Configure via environment variables:
  ALERT_SLACK_WEBHOOK=https://hooks.slack.com/services/...
  ALERT_EMAIL=you@company.com (uses SENDGRID_API_KEY)
"""

import os
import httpx
from datetime import datetime


def send_alert(title: str, message: str, level: str = "error"):
    """Send an alert via configured channels. Level: info, warning, error."""
    slack_url = os.getenv("ALERT_SLACK_WEBHOOK")
    alert_email = os.getenv("ALERT_EMAIL")

    sent = []

    if slack_url:
        try:
            _send_slack(slack_url, title, message, level)
            sent.append("slack")
        except Exception as e:
            print(f"[ALERT] Slack failed: {e}")

    if alert_email:
        try:
            _send_email_alert(alert_email, title, message)
            sent.append("email")
        except Exception as e:
            print(f"[ALERT] Email failed: {e}")

    if not sent:
        print(f"[ALERT] No alert channels configured. {level.upper()}: {title} — {message}")

    return sent


def pipeline_success(county: str, leads_scored: int, enriched: int, geocoded: int):
    send_alert(
        "Pipeline completed",
        f"County: {county}\n"
        f"Leads scored: {leads_scored:,}\n"
        f"Enriched: {enriched}\n"
        f"Geocoded: {geocoded}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}",
        level="info",
    )


def pipeline_failure(county: str, error: str):
    send_alert(
        "Pipeline FAILED",
        f"County: {county}\n"
        f"Error: {error}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M')}\n"
        f"Action: Check logs on the VM",
        level="error",
    )


def _send_slack(webhook_url: str, title: str, message: str, level: str):
    emoji = {"info": ":white_check_mark:", "warning": ":warning:", "error": ":rotating_light:"}.get(level, ":bell:")
    color = {"info": "#22c55e", "warning": "#f59e0b", "error": "#ef4444"}.get(level, "#999999")

    payload = {
        "attachments": [{
            "color": color,
            "blocks": [
                {
                    "type": "header",
                    "text": {"type": "plain_text", "text": f"{emoji} {title}"}
                },
                {
                    "type": "section",
                    "text": {"type": "mrkdwn", "text": message}
                },
            ],
        }],
    }

    resp = httpx.post(webhook_url, json=payload, timeout=10)
    resp.raise_for_status()


def _send_email_alert(to_email: str, title: str, message: str):
    api_key = os.getenv("SENDGRID_API_KEY")
    from_email = os.getenv("SENDGRID_FROM_EMAIL", "alerts@allcountyboulder.com")
    if not api_key:
        return

    resp = httpx.post(
        "https://api.sendgrid.com/v3/mail/send",
        headers={"Authorization": f"Bearer {api_key}", "Content-Type": "application/json"},
        json={
            "personalizations": [{"to": [{"email": to_email}]}],
            "from": {"email": from_email, "name": "All County Pipeline"},
            "subject": f"[ACPM] {title}",
            "content": [{"type": "text/plain", "value": message}],
        },
        timeout=10,
    )
    resp.raise_for_status()
