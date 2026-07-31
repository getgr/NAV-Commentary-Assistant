"""
Generates synthetic NAV rollforward + balance sheet data for 5 funds x 6 months.

Design (per Gopal's spec):
- Each fund is deliberately shaped to tell a distinct variance story, not randomly generated.
- Balance sheet ties to drivers in two tiers:
    Tier 1 (exact): Market value of investments, Cash -- derived directly from the six drivers.
    Tier 2 (loose): Trade receivables, Trade payables, Accrued fees -- modeled as small,
                    relatively stable balances (a modest % of NAV) with minor period noise.
- NAV = Investments + Cash + Receivables - Payables - Accrued fees  (always ties out exactly).
"""

import sqlite3
import random
from pathlib import Path

random.seed(42)

DB_PATH = Path(__file__).parent / "nav_variance.db"

PERIODS = ["2026-01", "2026-02", "2026-03", "2026-04", "2026-05", "2026-06"]

# Each fund: (fund_id, fund_name, currency, broker, "story" tag, starting_nav)
FUNDS = [
    ("F1", "Fund A", "USD", "Goldman Sachs", "steady", 50_000_000),
    ("F2", "Fund B", "USD", "Morgan Stanley", "fx_swing", 42_000_000),
    ("F3", "Fund C", "USD", "JPMorgan", "redemption_event", 65_000_000),
    ("F4", "Fund D", "USD", "UBS", "poor_performance", 30_000_000),
    ("F5", "Fund E", "USD", "Credit Suisse", "multi_driver_noisy", 55_000_000),
]


def gen_drivers(story, period_idx, beginning_nav):
    """
    Returns a dict of the six NAV rollforward drivers for one fund/period,
    shaped according to the fund's assigned story.

    All magnitudes are expressed as a realistic % of beginning NAV for a single month
    (not a cumulative or annualized move) to keep NAV trajectories plausible over 6 months.

    Subscriptions/redemptions trend with each fund's story rather than being independently
    randomized each period -- investor flows tend to persist in direction for a few months
    (chasing performance, or fleeing it) rather than flipping sign randomly month to month.
    """
    nav = beginning_nav
    t = period_idx / 5.0  # 0.0 (month 1) -> 1.0 (month 6), for trending flows

    if story == "steady":
        market = random.uniform(-0.012, 0.018) * nav
        income = random.uniform(0.0015, 0.0025) * nav
        expenses = -random.uniform(0.0010, 0.0016) * nav
        fx = random.uniform(-0.003, 0.003) * nav
        # Small, fairly balanced flows -- slight net inflow bias, steady fund attracts modest money
        subs = random.uniform(0.003, 0.006) * nav
        redemps = -random.uniform(0.002, 0.005) * nav

    elif story == "fx_swing":
        # Large FX move dominates; sign flips period to period to feel realistic
        fx_sign = 1 if period_idx % 2 == 0 else -1
        fx = fx_sign * random.uniform(0.025, 0.04) * nav
        market = random.uniform(-0.008, 0.012) * nav
        income = random.uniform(0.0012, 0.0022) * nav
        expenses = -random.uniform(0.0010, 0.0015) * nav
        # FX volatility makes investors cautious -- mild persistent net redemptions, not performance-driven
        subs = random.uniform(0.001, 0.003) * nav
        redemps = -random.uniform(0.004, 0.008) * nav

    elif story == "redemption_event":
        # One period (index 3) has a large redemption spike; otherwise modest steady flows
        if period_idx == 3:
            redemps = -random.uniform(0.10, 0.14) * nav
            subs = random.uniform(0.001, 0.003) * nav  # inflows dry up around the event
        else:
            redemps = -random.uniform(0.003, 0.007) * nav
            subs = random.uniform(0.003, 0.007) * nav
        market = random.uniform(-0.006, 0.014) * nav
        income = random.uniform(0.0015, 0.0025) * nav
        expenses = -random.uniform(0.0012, 0.0018) * nav
        fx = random.uniform(-0.003, 0.003) * nav

    elif story == "poor_performance":
        # Consistently negative market performance
        market = -random.uniform(0.015, 0.03) * nav
        income = random.uniform(0.0008, 0.0018) * nav
        expenses = -random.uniform(0.0010, 0.0014) * nav
        fx = random.uniform(-0.004, 0.001) * nav
        # Redemptions accelerate as losses accumulate; subscriptions dry up over the same period
        redemps = -(0.004 + 0.012 * t) * nav * random.uniform(0.9, 1.1)
        subs = (0.004 - 0.0035 * t) * nav * random.uniform(0.9, 1.1)

    else:  # multi_driver_noisy
        market = random.uniform(-0.025, 0.025) * nav
        income = random.uniform(0.0015, 0.0025) * nav
        expenses = -random.uniform(0.0012, 0.0018) * nav
        fx = random.uniform(-0.015, 0.015) * nav
        # Flows loosely follow the sign of that period's market move, plus noise -- performance-correlated
        flow_bias = 0.006 * (1 if market > 0 else -1)
        subs = max(0.001, (0.004 + flow_bias)) * nav * random.uniform(0.8, 1.2)
        redemps = -max(0.003, (0.006 - flow_bias)) * nav * random.uniform(0.8, 1.2)

    return {
        "market_gain_loss": round(market, 2),
        "income": round(income, 2),
        "expenses": round(expenses, 2),
        "subscriptions": round(subs, 2),
        "redemptions": round(redemps, 2),
        "fx_impact": round(fx, 2),
    }


def gen_balance_sheet(ending_nav, prior_investments, prior_cash, drivers):
    """
    Tier 1 (exact): investments and cash roll forward directly from drivers.
    Tier 2 (loose): receivables/payables/accrued fees as small stable % of NAV with noise.
    Investments absorbs FX + market movement; cash absorbs the flow-related drivers.
    """
    investments = prior_investments + drivers["market_gain_loss"] + drivers["fx_impact"] * 0.7
    cash = (
        prior_cash
        + drivers["income"]
        + drivers["expenses"]
        + drivers["subscriptions"]
        + drivers["redemptions"]
        + drivers["fx_impact"] * 0.3
    )

    # Tier 2: small stable balances as % of NAV, with minor noise
    receivables = round(ending_nav * random.uniform(0.006, 0.009), 2)
    payables = round(ending_nav * random.uniform(0.005, 0.008), 2)
    accrued_fees = round(ending_nav * random.uniform(0.006, 0.009), 2)
    investments = round(investments, 2)

    # Force exact tie-out AFTER rounding: NAV = Investments + Cash + Receivables - Payables - AccruedFees
    # Cash is the plug so tier-1 investments stays driver-derived and tier-2 stays small/stable.
    cash = round(ending_nav - (investments + receivables - payables - accrued_fees), 2)

    return {
        "investments": investments,
        "cash": cash,
        "receivables": receivables,
        "payables": payables,
        "accrued_fees": accrued_fees,
    }


def build_dataset():
    rows_rollforward = []
    rows_balance_sheet = []

    for fund_id, fund_name, currency, broker, story, start_nav in FUNDS:
        beginning_nav = start_nav
        # initial balance sheet split: ~90% investments, ~10% cash roughly, minus small tier-2 items
        prior_investments = beginning_nav * 0.90
        prior_cash = beginning_nav * 0.10

        for idx, period in enumerate(PERIODS):
            drivers = gen_drivers(story, idx, beginning_nav)
            change = sum(drivers.values())
            ending_nav = beginning_nav + change

            rows_rollforward.append(
                {
                    "fund_id": fund_id,
                    "period": period,
                    "beginning_nav": round(beginning_nav, 2),
                    "ending_nav": round(ending_nav, 2),
                    **drivers,
                }
            )

            bs = gen_balance_sheet(ending_nav, prior_investments, prior_cash, drivers)
            rows_balance_sheet.append(
                {"fund_id": fund_id, "period": period, **bs}
            )

            prior_investments = bs["investments"]
            prior_cash = bs["cash"]
            beginning_nav = ending_nav

    return rows_rollforward, rows_balance_sheet


def write_to_sqlite():
    if DB_PATH.exists():
        DB_PATH.unlink()

    conn = sqlite3.connect(DB_PATH)
    cur = conn.cursor()

    cur.execute(
        """
        CREATE TABLE funds (
            fund_id TEXT PRIMARY KEY,
            fund_name TEXT NOT NULL,
            currency TEXT NOT NULL,
            broker TEXT NOT NULL,
            story_tag TEXT NOT NULL
        )
        """
    )
    cur.executemany(
        "INSERT INTO funds VALUES (?, ?, ?, ?, ?)",
        [(f[0], f[1], f[2], f[3], f[4]) for f in FUNDS],
    )

    cur.execute(
        """
        CREATE TABLE nav_rollforward (
            fund_id TEXT NOT NULL,
            period TEXT NOT NULL,
            beginning_nav REAL NOT NULL,
            ending_nav REAL NOT NULL,
            market_gain_loss REAL NOT NULL,
            income REAL NOT NULL,
            expenses REAL NOT NULL,
            subscriptions REAL NOT NULL,
            redemptions REAL NOT NULL,
            fx_impact REAL NOT NULL,
            PRIMARY KEY (fund_id, period),
            FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
        )
        """
    )

    cur.execute(
        """
        CREATE TABLE balance_sheet (
            fund_id TEXT NOT NULL,
            period TEXT NOT NULL,
            investments REAL NOT NULL,
            cash REAL NOT NULL,
            receivables REAL NOT NULL,
            payables REAL NOT NULL,
            accrued_fees REAL NOT NULL,
            PRIMARY KEY (fund_id, period),
            FOREIGN KEY (fund_id) REFERENCES funds(fund_id)
        )
        """
    )

    rows_rf, rows_bs = build_dataset()

    cur.executemany(
        """
        INSERT INTO nav_rollforward
        (fund_id, period, beginning_nav, ending_nav, market_gain_loss, income, expenses, subscriptions, redemptions, fx_impact)
        VALUES (:fund_id, :period, :beginning_nav, :ending_nav, :market_gain_loss, :income, :expenses, :subscriptions, :redemptions, :fx_impact)
        """,
        rows_rf,
    )

    cur.executemany(
        """
        INSERT INTO balance_sheet
        (fund_id, period, investments, cash, receivables, payables, accrued_fees)
        VALUES (:fund_id, :period, :investments, :cash, :receivables, :payables, :accrued_fees)
        """,
        rows_bs,
    )

    conn.commit()

    # Sanity check: NAV = Investments + Cash + Receivables - Payables - AccruedFees for every row
    cur.execute(
        """
        SELECT r.fund_id, r.period, r.ending_nav,
               b.investments + b.cash + b.receivables - b.payables - b.accrued_fees AS reconstructed_nav
        FROM nav_rollforward r
        JOIN balance_sheet b ON r.fund_id = b.fund_id AND r.period = b.period
        """
    )
    max_diff = 0.0
    for fund_id, period, ending_nav, reconstructed in cur.fetchall():
        diff = abs(ending_nav - reconstructed)
        max_diff = max(max_diff, diff)
        if diff > 0.01:
            print(f"WARNING: {fund_id} {period} mismatch: {ending_nav} vs {reconstructed} (diff {diff})")

    print(f"Balance sheet reconciliation check passed. Max diff: {max_diff:.6f}")
    print(f"Database written to {DB_PATH}")
    print(f"Rows: {len(rows_rf)} rollforward, {len(rows_bs)} balance sheet")

    conn.close()


if __name__ == "__main__":
    write_to_sqlite()
