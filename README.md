# NAV Variance & Commentary Assistant (SQL + LLM)

Project 2 in the portfolio series (after the Automated Reconciliation Engine).

## What it does
- Synthetic NAV rollforward data for 5 funds x 6 months, each shaped around a distinct
  variance story (steady, FX-driven, redemption event, poor performance, multi-driver noisy).
- SQL views compute period-over-period NAV variance and driver contributions
  (market gain/loss, income, expenses, subscriptions, redemptions, FX impact).
- A balance sheet ties to those drivers -- investments/cash reconcile exactly to the
  drivers; receivables/payables/accrued fees are small, stable, loosely-modeled balances.
- An LLM (Claude) drafts first-pass variance commentary from the SQL output; falls back
  to a rule-based template if no API key is set. The draft is always editable in the UI --
  the point is "AI drafts, human reviews," not full automation.

## Setup
```
pip install -r requirements.txt
```

To regenerate the dataset (optional -- a pre-built nav_variance.db is included):
```
cd data && python3 generate_data.py
```

To use the real LLM commentary (optional -- falls back to templates otherwise):
```
export ANTHROPIC_API_KEY=your_key_here
```

## Run
```
cd app && streamlit run streamlit_app.py
```

## Structure
- `data/generate_data.py` -- synthetic data generator + SQLite writer
- `data/nav_variance.db` -- generated SQLite database
- `sql/variance_queries.sql` -- SQL views for variance, dominant driver, balance sheet, trend
- `app/commentary.py` -- LLM + template commentary generation
- `app/streamlit_app.py` -- the UI
