"""
Generates first-pass NAV variance commentary using the Anthropic API.

Design intent (per project spec): the LLM DRAFTS commentary from SQL-computed drivers;
the human reviews/edits before it's final. This module only ever produces a draft --
it never marks anything as final, and the caller (UI) is expected to surface it in an
editable field.

Falls back to a deterministic template-based draft if ANTHROPIC_API_KEY isn't set, so the
project runs standalone without requiring a key.
"""

import os
import sqlite3
from pathlib import Path

DB_PATH = Path(__file__).parent.parent / "data" / "nav_variance.db"

DRIVER_LABELS = {
    "market_gain_loss": "market gain/loss",
    "income": "income",
    "expenses": "expenses",
    "subscriptions": "subscriptions",
    "redemptions": "redemptions",
    "fx_impact": "FX impact",
}

# Maps driver column name -> its %-of-NAV column name in v_nav_variance (names don't all match 1:1)
DRIVER_PCT_COLUMNS = {
    "market_gain_loss": "market_pct",
    "income": "income_pct",
    "expenses": "expenses_pct",
    "subscriptions": "subscriptions_pct",
    "redemptions": "redemptions_pct",
    "fx_impact": "fx_impact_pct",
}


def get_variance_row(fund_id: str, period: str) -> dict:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    cur = conn.cursor()
    cur.execute(
        "SELECT * FROM v_nav_variance WHERE fund_id = ? AND period = ?",
        (fund_id, period),
    )
    row = cur.fetchone()
    conn.close()
    if row is None:
        raise ValueError(f"No data for {fund_id} / {period}")
    return dict(row)


def _fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    return f"{sign}${abs(value):,.0f}"


def _build_prompt(row: dict) -> str:
    drivers_text = "\n".join(
        f"- {DRIVER_LABELS[key]}: {_fmt_money(row[key])} ({row[DRIVER_PCT_COLUMNS[key]]:+.2f}% of beginning NAV)"
        for key in DRIVER_LABELS
    )
    return f"""You are a fund accountant drafting a first-pass NAV variance commentary for internal review.
This is a DRAFT for a human reviewer to check and edit -- do not present it as final.

Fund: {row['fund_name']} ({row['currency']})
Period: {row['period']}
Beginning NAV: {_fmt_money(row['beginning_nav'])}
Ending NAV: {_fmt_money(row['ending_nav'])}
NAV change: {_fmt_money(row['nav_change'])} ({row['nav_pct_change']:+.2f}%)

Driver breakdown:
{drivers_text}

Write a concise 2-4 sentence variance commentary in a professional fund accounting tone.
Identify the dominant driver(s) of the change, note any secondary contributors worth mentioning,
and flag anything unusual (e.g. a large one-off redemption, a notable FX swing). Do not
editorialize on future NAV movements -- describe only what happened this period. Do not
use bullet points; write in prose."""


def generate_commentary_llm(fund_id: str, period: str) -> str:
    """
    Calls the Anthropic API to draft commentary. Requires ANTHROPIC_API_KEY in the
    environment. Raises if the call fails -- caller should catch and fall back to
    generate_commentary_template().
    """
    import anthropic  # imported lazily so the module loads fine without the package installed

    row = get_variance_row(fund_id, period)
    prompt = _build_prompt(row)

    client = anthropic.Anthropic()  # reads ANTHROPIC_API_KEY from env
    message = client.messages.create(
        model="claude-sonnet-4-6",
        max_tokens=300,
        messages=[{"role": "user", "content": prompt}],
    )
    return message.content[0].text.strip()


def generate_commentary_template(fund_id: str, period: str) -> str:
    """
    Deterministic, rule-based commentary as a fallback when no API key is available.
    Picks the dominant driver and builds a templated sentence -- weaker than the LLM
    version, but keeps the app fully runnable standalone.
    """
    row = get_variance_row(fund_id, period)

    driver_pcts = {key: row[DRIVER_PCT_COLUMNS[key]] for key in DRIVER_LABELS}
    dominant_key = max(driver_pcts, key=lambda k: abs(driver_pcts[k]))
    dominant_label = DRIVER_LABELS[dominant_key]
    dominant_value = row[dominant_key]

    direction = "increased" if row["nav_change"] >= 0 else "decreased"
    dom_direction = "a gain" if dominant_value >= 0 else "a decline"
    dominant_magnitude = _fmt_money(abs(dominant_value))

    secondary = sorted(
        (k for k in DRIVER_LABELS if k != dominant_key),
        key=lambda k: abs(row[k]),
        reverse=True,
    )[:2]
    secondary_text = " and ".join(
        f"{DRIVER_LABELS[k]} ({row[DRIVER_PCT_COLUMNS[k]]:+.2f}%)" for k in secondary
    )

    return (
        f"{row['fund_name']}'s NAV {direction} by {_fmt_money(row['nav_change'])} "
        f"({row['nav_pct_change']:+.2f}%) in {row['period']}, driven primarily by "
        f"{dom_direction} in {dominant_label} of {dominant_magnitude}. "
        f"Secondary contributors were {secondary_text}. "
        f"[Template-generated draft -- no LLM API key configured.]"
    )


def generate_commentary(fund_id: str, period: str) -> tuple[str, str]:
    """
    Returns (commentary_text, source) where source is 'llm' or 'template'.
    Tries the LLM first; falls back to the template on any failure (missing key,
    network error, etc.) so the app never breaks.
    """
    if os.environ.get("ANTHROPIC_API_KEY"):
        try:
            return generate_commentary_llm(fund_id, period), "llm"
        except Exception as e:
            print(f"LLM commentary failed ({e}), falling back to template.")
    return generate_commentary_template(fund_id, period), "template"


if __name__ == "__main__":
    # Quick manual test across all funds for the redemption-event period
    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()
    cur.execute("SELECT DISTINCT fund_id FROM funds")
    fund_ids = [r[0] for r in cur.fetchall()]
    conn.close()

    for fid in fund_ids:
        text, source = generate_commentary(fid, "2026-04")
        print(f"\n--- {fid} (2026-04) [{source}] ---")
        print(text)
