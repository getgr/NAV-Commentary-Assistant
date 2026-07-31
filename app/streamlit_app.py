"""
NAV Variance & Commentary Assistant -- Streamlit UI

Layout: fund/period pickers -> NAV trend sparkline -> metric strip (4 cards) ->
driver breakdown bars -> collapsible balance sheet -> editable AI commentary panel.

Trend line and driver bars are rendered as custom inline SVG/HTML (not Plotly) --
this gives full control over labels and avoids Plotly's auto-tick/text-overflow
issues on compact card layouts, and matches the original design mockup.

IMPORTANT: all HTML strings below are built with NO leading whitespace on any line
and joined without indentation. Streamlit's markdown renderer treats 4+ leading
spaces on a line as a code block (CommonMark rule) -- indented multi-line f-strings
will render as literal escaped text instead of live HTML. Keep every template flush left.
"""

import sqlite3
from pathlib import Path

import pandas as pd
import streamlit as st

from commentary import generate_commentary, DRIVER_LABELS, DRIVER_PCT_COLUMNS

DB_PATH = Path(__file__).parent.parent / "data" / "nav_variance.db"

st.set_page_config(page_title="NAV Variance & Commentary Assistant", layout="centered")

CARD_CSS = (
"<style>"
".nva-card{background:#1a1c23;border:1px solid rgba(255,255,255,0.08);border-radius:12px;"
"padding:16px 20px;margin-bottom:16px;}"
".nva-card-title{font-size:14px;font-weight:600;color:rgba(255,255,255,0.92);margin:0 0 12px 0;}"
".nva-metric-grid{display:grid;grid-template-columns:repeat(4,1fr);gap:12px;}"
".nva-metric-box{background:rgba(255,255,255,0.04);border-radius:8px;padding:12px 14px;}"
".nva-metric-label{font-size:12px;color:rgba(255,255,255,0.55);margin:0 0 4px 0;}"
".nva-metric-value{font-size:20px;font-weight:600;margin:0;}"
".nva-metric-note{font-size:11px;color:rgba(255,255,255,0.45);margin-top:6px;line-height:1.4;}"
".nva-bar-row{display:flex;align-items:center;gap:10px;margin-bottom:10px;}"
".nva-bar-label{font-size:13px;color:rgba(255,255,255,0.7);width:120px;flex-shrink:0;}"
".nva-bar-track{flex:1;background:rgba(255,255,255,0.06);border-radius:4px;height:12px;"
"position:relative;overflow:hidden;}"
".nva-bar-fill{height:100%;border-radius:4px;}"
".nva-bar-value{font-size:13px;width:95px;text-align:right;flex-shrink:0;font-variant-numeric:tabular-nums;}"
"@media (max-width:640px){.nva-metric-grid{grid-template-columns:repeat(2,1fr);}}"
"</style>"
)
st.markdown(CARD_CSS, unsafe_allow_html=True)


@st.cache_resource
def get_conn():
    return sqlite3.connect(DB_PATH, check_same_thread=False)


def load_funds() -> pd.DataFrame:
    return pd.read_sql("SELECT fund_id, fund_name FROM funds ORDER BY fund_id", get_conn())


def load_periods() -> list[str]:
    df = pd.read_sql("SELECT DISTINCT period FROM nav_rollforward ORDER BY period", get_conn())
    return df["period"].tolist()


def load_variance_row(fund_id: str, period: str) -> pd.Series:
    df = pd.read_sql(
        "SELECT * FROM v_nav_variance WHERE fund_id = ? AND period = ?",
        get_conn(),
        params=(fund_id, period),
    )
    return df.iloc[0]


def load_trend(fund_id: str) -> pd.DataFrame:
    return pd.read_sql(
        "SELECT period, ending_nav FROM v_nav_trend WHERE fund_id = ? ORDER BY period",
        get_conn(),
        params=(fund_id,),
    )


def load_balance_sheet(fund_id: str, period: str) -> pd.Series:
    df = pd.read_sql(
        "SELECT * FROM v_balance_sheet WHERE fund_id = ? AND period = ?",
        get_conn(),
        params=(fund_id, period),
    )
    return df.iloc[0]


def fmt_money(value: float) -> str:
    sign = "-" if value < 0 else ""
    abs_val = abs(value)
    if abs_val >= 1_000_000:
        return f"{sign}${abs_val / 1_000_000:.2f}M"
    if abs_val >= 1_000:
        return f"{sign}${abs_val / 1_000:.0f}K"
    return f"{sign}${abs_val:,.0f}"


def month_label(period: str) -> str:
    months = ["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"]
    y, m = period.split("-")
    return months[int(m) - 1]


def render_trend_svg(trend_df: pd.DataFrame, selected_period: str) -> str:
    """Builds a labeled sparkline as raw SVG -- exactly 6 historical points, no projection.
    Returned as a single-line string (no newlines) to stay safe inside st.markdown."""
    width, height = 640, 140
    pad_left, pad_right, pad_top, pad_bottom = 45, 15, 15, 25

    values = trend_df["ending_nav"].tolist()
    periods = trend_df["period"].tolist()
    vmin, vmax = min(values), max(values)
    vrange = (vmax - vmin) or 1.0
    vmin_padded = vmin - vrange * 0.1
    vmax_padded = vmax + vrange * 0.1
    vrange_padded = vmax_padded - vmin_padded

    plot_w = width - pad_left - pad_right
    plot_h = height - pad_top - pad_bottom
    n = len(values)

    def x_at(i):
        return pad_left + (i / (n - 1)) * plot_w if n > 1 else pad_left

    def y_at(v):
        return pad_top + plot_h - ((v - vmin_padded) / vrange_padded) * plot_h

    points = [(x_at(i), y_at(v)) for i, v in enumerate(values)]
    polyline_pts = " ".join(f"{x:.1f},{y:.1f}" for x, y in points)

    parts = []
    parts.append(f'<svg viewBox="0 0 {width} {height}" style="width:100%;height:{height}px;display:block;">')

    y_top_val = fmt_money(vmax)
    y_bot_val = fmt_money(vmin)
    parts.append(
        f'<text x="{pad_left - 8}" y="{pad_top + 4}" font-size="11" fill="rgba(255,255,255,0.5)" text-anchor="end">{y_top_val}</text>'
    )
    parts.append(
        f'<text x="{pad_left - 8}" y="{height - pad_bottom}" font-size="11" fill="rgba(255,255,255,0.5)" text-anchor="end">{y_bot_val}</text>'
    )

    parts.append(f'<polyline points="{polyline_pts}" fill="none" stroke="#378ADD" stroke-width="2" />')

    for i, (x, y) in enumerate(points):
        is_selected = periods[i] == selected_period
        r = 5 if is_selected else 3.5
        color = "#0C447C" if is_selected else "#378ADD"
        tooltip = f"{month_label(periods[i])} {periods[i].split('-')[0]}: {fmt_money(values[i])}"
        parts.append(f'<circle cx="{x:.1f}" cy="{y:.1f}" r="{r}" fill="{color}"><title>{tooltip}</title></circle>')

    for i, p in enumerate(periods):
        x = x_at(i)
        parts.append(
            f'<text x="{x:.1f}" y="{height - 6}" font-size="11" fill="rgba(255,255,255,0.5)" text-anchor="middle">{month_label(p)}</text>'
        )

    parts.append("</svg>")
    return "".join(parts)


def render_driver_bars(driver_df: pd.DataFrame) -> str:
    max_abs = driver_df["Amount"].abs().max() or 1.0
    rows = []
    for _, r in driver_df.iterrows():
        pct_width = min(100, (abs(r["Amount"]) / max_abs) * 100)
        color = "#639922" if r["Amount"] >= 0 else "#E24B4A"
        rows.append(
            f'<div class="nva-bar-row">'
            f'<span class="nva-bar-label">{r["Driver"]}</span>'
            f'<div class="nva-bar-track"><div class="nva-bar-fill" style="width:{pct_width:.1f}%;background:{color};"></div></div>'
            f'<span class="nva-bar-value">{fmt_money(r["Amount"])}</span>'
            f'</div>'
        )
    return "".join(rows)


# ---------- Header / selectors ----------
st.markdown("### NAV variance & commentary assistant")

funds_df = load_funds()
periods = load_periods()

col1, col2 = st.columns(2)
with col1:
    fund_name_to_id = dict(zip(funds_df["fund_name"], funds_df["fund_id"]))
    selected_fund_name = st.selectbox("Fund", list(fund_name_to_id.keys()))
    selected_fund_id = fund_name_to_id[selected_fund_name]
with col2:
    selected_period = st.selectbox("Period", periods, index=len(periods) - 1)

row = load_variance_row(selected_fund_id, selected_period)
trend_df = load_trend(selected_fund_id)  # exactly 6 historical rows, no projection

# ---------- NAV trend + metric strip (one card) ----------
trend_svg = render_trend_svg(trend_df, selected_period)

change_color = "#639922" if row["nav_change"] >= 0 else "#E24B4A"
pct_color = "#639922" if row["nav_pct_change"] >= 0 else "#E24B4A"

metric_html = (
    '<div class="nva-card">'
    '<p class="nva-card-title">NAV trend (6 months)</p>'
    f'{trend_svg}'
    '<div class="nva-metric-grid" style="margin-top:16px;">'
    '<div class="nva-metric-box">'
    '<p class="nva-metric-label">Beginning NAV</p>'
    f'<p class="nva-metric-value">{fmt_money(row["beginning_nav"])}</p>'
    '</div>'
    '<div class="nva-metric-box">'
    '<p class="nva-metric-label">Ending NAV</p>'
    f'<p class="nva-metric-value">{fmt_money(row["ending_nav"])}</p>'
    '</div>'
    '<div class="nva-metric-box">'
    '<p class="nva-metric-label">Change</p>'
    f'<p class="nva-metric-value" style="color:{change_color};">{fmt_money(row["nav_change"])}</p>'
    '</div>'
    '<div class="nva-metric-box">'
    '<p class="nva-metric-label">% change</p>'
    f'<p class="nva-metric-value" style="color:{pct_color};">{row["nav_pct_change"]:+.2f}%</p>'
    '<p class="nva-metric-note">NAV % change, not investment performance — includes subscription/redemption flows.</p>'
    '</div>'
    '</div>'
    '</div>'
)
st.markdown(metric_html, unsafe_allow_html=True)

# ---------- Driver breakdown ----------
driver_rows = []
for key, label in DRIVER_LABELS.items():
    driver_rows.append({"Driver": label, "Amount": row[key], "% of NAV": row[DRIVER_PCT_COLUMNS[key]]})
driver_df = pd.DataFrame(driver_rows).sort_values("Amount", key=abs, ascending=False)

driver_html = (
    '<div class="nva-card">'
    '<p class="nva-card-title">Driver breakdown</p>'
    f'{render_driver_bars(driver_df)}'
    '</div>'
)
st.markdown(driver_html, unsafe_allow_html=True)

# ---------- Balance sheet (collapsed) ----------
with st.expander("Balance sheet breakdown"):
    bs = load_balance_sheet(selected_fund_id, selected_period)
    bs_rows = [
        ("Market value of investments", bs["investments"]),
        ("Cash", bs["cash"]),
        ("Trade receivables", bs["receivables"]),
        ("Trade payables", -bs["payables"]),
        ("Accrued fees", -bs["accrued_fees"]),
    ]
    for label, value in bs_rows:
        c1, c2 = st.columns([3, 1])
        c1.write(label)
        c2.write(fmt_money(value))
    st.markdown("---")
    c1, c2 = st.columns([3, 1])
    c1.markdown("**Ending NAV**")
    c2.markdown(f"**{fmt_money(bs['ending_nav'])}**")
    recon_diff = abs(bs["ending_nav"] - bs["reconstructed_nav"])
    if recon_diff > 0.01:
        st.warning(f"Reconciliation mismatch: {fmt_money(recon_diff)}")

# ---------- AI-drafted commentary ----------
st.markdown("###### :sparkles: AI-drafted commentary")

commentary_key = f"commentary_{selected_fund_id}_{selected_period}"
source_key = f"source_{selected_fund_id}_{selected_period}"

regenerate = st.button(":arrows_counterclockwise: Regenerate", key="regen_btn")

if commentary_key not in st.session_state or regenerate:
    with st.spinner("Drafting commentary..."):
        text, source = generate_commentary(selected_fund_id, selected_period)
        st.session_state[commentary_key] = text
        st.session_state[source_key] = source

edited_text = st.text_area(
    "Commentary (editable)",
    value=st.session_state[commentary_key],
    height=140,
    label_visibility="collapsed",
    key=f"textarea_{commentary_key}",
)

source_label = "Claude-drafted" if st.session_state.get(source_key) == "llm" else "Template-drafted (no API key set)"
st.caption(f"{source_label} — editable, review before finalizing.")
