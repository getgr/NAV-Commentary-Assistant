-- NAV Variance & Driver Contribution Queries
-- Computes period-over-period NAV change and the % contribution of each of the six drivers.

-- 1. Core variance query: change + % of beginning NAV for each driver, per fund/period
CREATE VIEW IF NOT EXISTS v_nav_variance AS
SELECT
    r.fund_id,
    f.fund_name,
    f.currency,
    f.broker,
    r.period,
    r.beginning_nav,
    r.ending_nav,
    (r.ending_nav - r.beginning_nav) AS nav_change,
    ROUND((r.ending_nav - r.beginning_nav) * 100.0 / r.beginning_nav, 2) AS nav_pct_change,
    r.market_gain_loss,
    r.income,
    r.expenses,
    r.subscriptions,
    r.redemptions,
    r.fx_impact,
    ROUND(r.market_gain_loss * 100.0 / r.beginning_nav, 2) AS market_pct,
    ROUND(r.income * 100.0 / r.beginning_nav, 2) AS income_pct,
    ROUND(r.expenses * 100.0 / r.beginning_nav, 2) AS expenses_pct,
    ROUND(r.subscriptions * 100.0 / r.beginning_nav, 2) AS subscriptions_pct,
    ROUND(r.redemptions * 100.0 / r.beginning_nav, 2) AS redemptions_pct,
    ROUND(r.fx_impact * 100.0 / r.beginning_nav, 2) AS fx_impact_pct
FROM nav_rollforward r
JOIN funds f ON r.fund_id = f.fund_id;

-- 2. Dominant driver per fund/period -- the largest absolute-value driver, used to
--    flag "what mainly moved this period" for the commentary prompt and the UI.
CREATE VIEW IF NOT EXISTS v_dominant_driver AS
SELECT
    fund_id,
    period,
    driver_name,
    driver_value,
    ABS(driver_value) AS abs_value
FROM (
    SELECT fund_id, period, 'market_gain_loss' AS driver_name, market_gain_loss AS driver_value FROM nav_rollforward
    UNION ALL
    SELECT fund_id, period, 'income', income FROM nav_rollforward
    UNION ALL
    SELECT fund_id, period, 'expenses', expenses FROM nav_rollforward
    UNION ALL
    SELECT fund_id, period, 'subscriptions', subscriptions FROM nav_rollforward
    UNION ALL
    SELECT fund_id, period, 'redemptions', redemptions FROM nav_rollforward
    UNION ALL
    SELECT fund_id, period, 'fx_impact', fx_impact FROM nav_rollforward
) all_drivers
WHERE (fund_id, period, ABS(driver_value)) IN (
    SELECT fund_id, period, MAX(ABS(driver_value))
    FROM (
        SELECT fund_id, period, market_gain_loss AS driver_value FROM nav_rollforward
        UNION ALL SELECT fund_id, period, income FROM nav_rollforward
        UNION ALL SELECT fund_id, period, expenses FROM nav_rollforward
        UNION ALL SELECT fund_id, period, subscriptions FROM nav_rollforward
        UNION ALL SELECT fund_id, period, redemptions FROM nav_rollforward
        UNION ALL SELECT fund_id, period, fx_impact FROM nav_rollforward
    )
    GROUP BY fund_id, period
);

-- 3. Balance sheet with reconciliation check exposed (NAV vs reconstructed NAV)
CREATE VIEW IF NOT EXISTS v_balance_sheet AS
SELECT
    b.fund_id,
    f.fund_name,
    b.period,
    b.investments,
    b.cash,
    b.receivables,
    b.payables,
    b.accrued_fees,
    r.ending_nav,
    (b.investments + b.cash + b.receivables - b.payables - b.accrued_fees) AS reconstructed_nav
FROM balance_sheet b
JOIN funds f ON b.fund_id = f.fund_id
JOIN nav_rollforward r ON b.fund_id = r.fund_id AND b.period = r.period;

-- 4. 6-month NAV trend per fund (for the sparkline) -- historical only, ordered by period
CREATE VIEW IF NOT EXISTS v_nav_trend AS
SELECT fund_id, period, ending_nav
FROM nav_rollforward
ORDER BY fund_id, period;
