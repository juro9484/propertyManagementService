"""
Insight Generator — rule-based, no AI.

Interprets raw RentCast + ownership data into structured insights.
Output feeds into the LLM for personalized emails.
"""

from db import get_cursor


def get_market_avg_dom(zip_code):
    """Compute average days on market for a zip code from our rental_listings DB.
    Excludes <15 day listings (platform cycling noise).
    """
    with get_cursor() as cur:
        cur.execute("""
            SELECT COALESCE(AVG(days_on_market), 0)::int as avg_dom
            FROM rental_listings
            WHERE zip_code = %s
            AND days_on_market BETWEEN 15 AND 180
            AND fetched_at > NOW() - INTERVAL '10 days'
        """, [zip_code])
        return cur.fetchone()["avg_dom"] or 0


def compute_metrics(listing, market_avg_dom):
    """Derive metrics from raw listing data."""
    dom = listing.get("days_on_market") or 0
    price = listing.get("price") or 0
    rent_estimate = listing.get("rent_estimate") or 0
    max_history_price = listing.get("max_history_price") or price

    dom_ratio = round(dom / market_avg_dom, 2) if market_avg_dom > 0 else 0

    price_drop_pct = 0
    if max_history_price > 0 and price < max_history_price:
        price_drop_pct = round((max_history_price - price) / max_history_price * 100, 1)

    price_vs_market_pct = 0
    if rent_estimate > 0 and price > 0:
        price_vs_market_pct = round((price - rent_estimate) / rent_estimate * 100, 1)

    return {
        "dom": dom,
        "market_avg_dom": market_avg_dom,
        "dom_ratio": dom_ratio,
        "current_price": price,
        "rent_estimate": rent_estimate,
        "price_vs_market_pct": price_vs_market_pct,
        "max_history_price": max_history_price,
        "price_drop_pct": price_drop_pct,
    }


def generate_insights(metrics, lead_data):
    """Generate human-readable insights. Pure rules, no AI."""
    insights = []
    dom_ratio = metrics.get("dom_ratio", 0)
    dom = metrics.get("dom", 0)
    market_avg = metrics.get("market_avg_dom", 0)
    price_drop = metrics.get("price_drop_pct", 0)
    price_vs_market = metrics.get("price_vs_market_pct", 0)
    rent_est = metrics.get("rent_estimate", 0)
    current_price = metrics.get("current_price", 0)

    # Raw DOM signal (no market comparison — just how long it's been sitting)
    if dom >= 45:
        insights.append({
            "message": f"Property has been on the market {dom} days",
            "severity": "high",
            "category": "vacancy",
        })
    elif dom >= 15:
        insights.append({
            "message": f"Property has been listed for {dom} days",
            "severity": "medium",
            "category": "vacancy",
        })

    # Overpriced vs market comps
    if price_vs_market >= 15 and rent_est > 0:
        insights.append({
            "message": f"Listed {price_vs_market}% above market — comparable rentals average ${rent_est:,}/mo vs asking ${current_price:,}",
            "severity": "high",
            "category": "pricing",
        })
    elif price_vs_market >= 5 and rent_est > 0:
        insights.append({
            "message": f"Listed {price_vs_market}% above comparable rentals in the area (${rent_est:,}/mo average)",
            "severity": "medium",
            "category": "pricing",
        })

    # Underpriced vs market
    if price_vs_market < -15 and rent_est > 0:
        insights.append({
            "message": f"Listed {abs(price_vs_market)}% below market — potential income opportunity at ${rent_est:,}/mo",
            "severity": "medium",
            "category": "underpricing",
        })

    # Price drop from original listing
    if price_drop >= 15:
        insights.append({
            "message": f"Owner has cut asking rent by {price_drop}% (from ${metrics['max_history_price']:,} to ${current_price:,}), indicating difficulty leasing",
            "severity": "high",
            "category": "pricing",
        })
    elif price_drop >= 5:
        insights.append({
            "message": f"Asking rent reduced {price_drop}% from original listing price",
            "severity": "medium",
            "category": "pricing",
        })

    # Owner friction
    if lead_data.get("out_of_state"):
        insights.append({
            "message": "Owner is managing remotely from out of state",
            "severity": "low",
            "category": "friction",
        })
    elif lead_data.get("absentee"):
        insights.append({
            "message": "Owner does not live near their rental property",
            "severity": "low",
            "category": "friction",
        })

    # Multi-vacancy
    vacant_count = lead_data.get("vacant_count", 0)
    if vacant_count >= 3:
        insights.append({
            "message": f"Owner has {vacant_count} vacant units — likely overwhelmed managing multiple vacancies",
            "severity": "high",
            "category": "vacancy",
        })
    elif vacant_count == 2:
        insights.append({
            "message": "Owner has 2 vacant units simultaneously",
            "severity": "medium",
            "category": "vacancy",
        })

    return insights


def build_insight_object(lead, metrics, insights):
    """Build structured insight object for LLM consumption."""
    high = [i for i in insights if i["severity"] == "high"]
    medium = [i for i in insights if i["severity"] == "medium"]
    top_insights = high or medium or insights

    if not top_insights:
        primary_issue = "Property owner who may benefit from professional management"
        angle = "general"
    else:
        primary_issue = ". ".join(i["message"] for i in top_insights[:2])
        categories = [i["category"] for i in top_insights]
        if "pricing" in categories and "vacancy" in categories:
            angle = "pricing_and_vacancy"
        elif "pricing" in categories:
            angle = "pricing"
        elif "vacancy" in categories:
            angle = "vacancy"
        elif "underpricing" in categories:
            angle = "underpricing"
        else:
            angle = "general"

    return {
        "score": lead.get("score", 0),
        "primary_issue": primary_issue,
        "angle": angle,
        "insights": insights,
        "metrics": metrics,
    }


def build_llm_context(insight_object):
    """Build context string for the LLM email prompt.
    Only includes relevant, specific facts.
    """
    insights = insight_object.get("insights", [])
    metrics = insight_object.get("metrics", {})
    angle = insight_object.get("angle", "general")

    if not insights:
        return ""

    lines = ["SITUATION INSIGHTS (reference these naturally — be specific, not generic):"]

    for i in insights:
        marker = {"high": "!!!", "medium": "!!", "low": "!"}.get(i["severity"], "")
        lines.append(f"  {marker} {i['message']}")

    # Key numbers for the LLM to reference
    numbers = []
    if metrics.get("dom", 0) > 0:
        numbers.append(f"Days on market: {metrics['dom']}")
    if metrics.get("market_avg_dom", 0) > 0:
        numbers.append(f"Market average: {metrics['market_avg_dom']} days")
    if metrics.get("price_vs_market_pct", 0) != 0:
        numbers.append(f"Price vs market: {metrics['price_vs_market_pct']:+.0f}%")
    if metrics.get("rent_estimate", 0) > 0:
        numbers.append(f"Market rent estimate: ${metrics['rent_estimate']:,}/mo")
    if metrics.get("price_drop_pct", 0) > 0:
        numbers.append(f"Price reduced: {metrics['price_drop_pct']}% (${metrics['max_history_price']:,} → ${metrics['current_price']:,})")

    if numbers:
        lines.append("\nKEY NUMBERS:")
        for n in numbers:
            lines.append(f"  {n}")

    lines.append(f"\nOUTREACH ANGLE: {angle}")
    lines.append("  Reference the specific numbers above. Be concrete, not vague.")

    return "\n".join(lines)


def get_insights_for_lead(lead):
    """Full pipeline: get listing data → compute metrics → generate insights.
    Returns insight_object or None if no vacancy data.
    """
    lead_id = lead.get("id")
    if not lead_id:
        return None

    # Get this lead's vacant listings
    with get_cursor() as cur:
        cur.execute("""
            SELECT rl.* FROM rental_listings rl
            JOIN lead_properties lp ON
                UPPER(REGEXP_REPLACE(rl.address, '(Apt|Unit|Suite|Ste|#)\s*', '# ', 'gi'))
                = UPPER(REGEXP_REPLACE(lp.address, '(APT|UNIT|SUITE|STE|#)\s*', '# ', 'gi'))
            WHERE lp.lead_id = %s
            AND rl.days_on_market BETWEEN 1 AND 180
            AND rl.fetched_at > NOW() - INTERVAL '10 days'
            ORDER BY rl.days_on_market DESC
            LIMIT 1
        """, [lead_id])
        listing = cur.fetchone()

    if not listing:
        return None

    zip_code = listing.get("zip_code") or ""
    market_avg = get_market_avg_dom(zip_code)

    metrics = compute_metrics(dict(listing), market_avg)

    lead_data = {
        "out_of_state": "OUT_OF_STATE" in (lead.get("badges") or []),
        "absentee": "ABSENTEE" in (lead.get("badges") or []),
        "vacant_count": len([b for b in (lead.get("badges") or []) if b == "VACANT"]),
    }

    insights = generate_insights(metrics, lead_data)
    return build_insight_object(lead, metrics, insights)
