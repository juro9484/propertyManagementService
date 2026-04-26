"""
Alert system — notifies on pipeline failures or important events.

Supports Gmail SMTP (no third-party service needed) and/or Slack webhook.
Configure via environment variables:
  ALERT_EMAIL_TO=you@gmail.com
  ALERT_GMAIL_USER=yourbot@gmail.com
  ALERT_GMAIL_APP_PASSWORD=xxxx xxxx xxxx xxxx
  ALERT_SLACK_WEBHOOK=https://hooks.slack.com/services/... (optional)
"""

import os
import smtplib
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from datetime import datetime


def send_alert(title: str, message: str, level: str = "error"):
    """Send an alert via configured channels. Level: info, warning, error."""
    sent = []

    # Gmail SMTP
    to_email = os.getenv("ALERT_EMAIL_TO")
    gmail_user = os.getenv("ALERT_GMAIL_USER")
    gmail_pass = os.getenv("ALERT_GMAIL_APP_PASSWORD")
    if to_email and gmail_user and gmail_pass:
        try:
            _send_gmail(gmail_user, gmail_pass, to_email, title, message, level)
            sent.append("email")
        except Exception as e:
            print(f"[ALERT] Gmail failed: {e}")

    # Slack webhook
    slack_url = os.getenv("ALERT_SLACK_WEBHOOK")
    if slack_url:
        try:
            import httpx
            _send_slack(slack_url, title, message, level)
            sent.append("slack")
        except Exception as e:
            print(f"[ALERT] Slack failed: {e}")

    if not sent:
        print(f"[ALERT] No channels configured. {level.upper()}: {title} �� {message}")

    return sent


def pipeline_success(county: str, leads_scored: int, enriched: int, geocoded: int):
    send_alert(
        "Pipeline completed",
        f"County: {county}\n"
        f"Leads scored: {leads_scored:,}\n"
        f"New enriched: {enriched}\n"
        f"Geocoded: {geocoded}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}",
        level="info",
    )


def pipeline_failure(county: str, error: str):
    send_alert(
        "Pipeline FAILED",
        f"County: {county}\n"
        f"Error: {error}\n"
        f"Time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}\n\n"
        f"Check logs: sudo docker-compose logs app --tail 50",
        level="error",
    )


def _send_gmail(user: str, app_password: str, to: str, title: str, message: str, level: str):
    icon = {"info": "✅", "warning": "⚠️", "error": "🚨"}.get(level, "🔔")

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"{icon} [ACPM] {title}"
    msg["From"] = f"All County Pipeline <{user}>"
    msg["To"] = to

    # Plain text
    msg.attach(MIMEText(message, "plain"))

    # HTML version
    color = {"info": "#22c55e", "warning": "#f59e0b", "error": "#ef4444"}.get(level, "#999")
    html = f"""
    <div style="font-family: -apple-system, sans-serif; max-width: 500px; padding: 20px;">
        <div style="border-left: 4px solid {color}; padding: 12px 16px; background: #f9f9f9; border-radius: 4px;">
            <h2 style="margin: 0 0 8px; font-size: 16px; color: #333;">{icon} {title}</h2>
            <pre style="margin: 0; font-size: 13px; color: #555; white-space: pre-wrap;">{message}</pre>
        </div>
        <p style="font-size: 11px; color: #999; margin-top: 12px;">All County Lead Gen Pipeline</p>
    </div>
    """
    msg.attach(MIMEText(html, "html"))

    with smtplib.SMTP_SSL("smtp.gmail.com", 465) as server:
        server.login(user, app_password)
        server.sendmail(user, to, msg.as_string())


def _send_slack(webhook_url: str, title: str, message: str, level: str):
    import httpx
    emoji = {"info": ":white_check_mark:", "warning": ":warning:", "error": ":rotating_light:"}.get(level, ":bell:")
    color = {"info": "#22c55e", "warning": "#f59e0b", "error": "#ef4444"}.get(level, "#999999")

    resp = httpx.post(webhook_url, json={
        "attachments": [{
            "color": color,
            "blocks": [
                {"type": "header", "text": {"type": "plain_text", "text": f"{emoji} {title}"}},
                {"type": "section", "text": {"type": "mrkdwn", "text": message}},
            ],
        }],
    }, timeout=10)
    resp.raise_for_status()
