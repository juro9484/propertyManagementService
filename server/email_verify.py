"""
Email verification — checks if enriched emails are deliverable.

Uses ZeroBounce API to validate emails without sending.
Runs after enrichment to flag valid/invalid/risky emails.

Statuses:
  unverified — not yet checked
  valid — confirmed deliverable
  invalid — mailbox doesn't exist or domain dead
  risky — catch-all domain, disposable, or role-based address
"""

import os
import httpx
from db import get_cursor


def verify_emails(limit=50):
    """Verify unverified emails on enriched leads.
    Only checks leads in the top 200 per county.
    """
    api_key = os.environ.get("ZEROBOUNCE_API_KEY", "")
    if not api_key:
        print("[EMAIL] No ZEROBOUNCE_API_KEY — skipping verification")
        return 0

    with get_cursor() as cur:
        cur.execute("""
            SELECT id, email FROM leads
            WHERE email IS NOT NULL
            AND email_status = 'unverified'
            AND id IN (
                (SELECT id FROM leads WHERE county = 'boulder' ORDER BY score DESC LIMIT 200)
                UNION ALL
                (SELECT id FROM leads WHERE county = 'larimer' ORDER BY score DESC LIMIT 200)
            )
            LIMIT %s
        """, [limit])
        to_verify = cur.fetchall()

    if not to_verify:
        print("[EMAIL] No emails to verify")
        return 0

    verified = 0
    for lead in to_verify:
        try:
            resp = httpx.get(
                "https://api.zerobounce.net/v2/validate",
                params={"api_key": api_key, "email": lead["email"]},
                timeout=10,
            )

            if resp.status_code == 200:
                data = resp.json()
                zb_status = data.get("status", "").lower()

                # Map ZeroBounce status to our simple status
                if zb_status == "valid":
                    status = "valid"
                elif zb_status in ("invalid", "do_not_mail"):
                    status = "invalid"
                elif zb_status in ("catch-all", "spamtrap", "abuse", "disposable"):
                    status = "risky"
                else:
                    status = "unverified"

                with get_cursor(commit=True) as cur:
                    cur.execute(
                        "UPDATE leads SET email_status = %s WHERE id = %s",
                        [status, lead["id"]],
                    )
                verified += 1

        except Exception as e:
            print(f"[EMAIL] Verify failed for {lead['email']}: {e}")

    print(f"[EMAIL] Verified {verified}/{len(to_verify)} emails")
    return verified
