# FraudGraph AI

**Finding fraud rings hidden inside ordinary-looking transactions.**

A transaction can look completely normal on its own — an ordinary amount,
between two ordinary-looking accounts, well within any threshold rule. Looked
at as a *network*, the same transaction can be one leg of money that never
actually left a small group of accounts. This project analyzes transaction
data as a graph to find that kind of structure: circular money movement,
collector accounts that pool and forward funds, and unusually dense clusters
of accounts — not just individually unusual transactions.

```
Person A → ₹4,500 → Person B
Person B → ₹4,200 → Person C
Person C → ₹4,350 → Person A
```
Each transfer clears a simple threshold check. Together, they form a closed
loop — the pattern this project is built to surface.

## What it does

1. **Cleans and validates** uploaded transaction data (CSV), auto-detecting
   common column layouts (including public datasets such as PaySim).
2. **Scores individual transactions** for anomalies with an Isolation Forest
   trained on per-account behavioural features.
3. **Builds a transaction network** — every account a node, every transfer an
   edge — and runs graph analytics: closed-loop search, Louvain community
   detection, PageRank and betweenness centrality.
4. **Detects fraud rings** of three kinds — circular money movement,
   collector/mule hubs, and dense account clusters — and scores each 0–100
   from six weighted, explainable signals.
5. **Explains every result** in plain language: which signals fired, and why.
6. **Visualizes** each ring and the overall network as an interactive graph.
7. **Evaluates itself** against known fraud labels and, for the built-in
   synthetic dataset, against a ground-truth list of planted rings.

## Why both real and synthetic data

Public fraud datasets (e.g. Kaggle's IEEE-CIS or PaySim) provide realistic
transaction volume and, sometimes, fraud labels — but they rarely include
the *ring structure* needed to evaluate graph-based detection: which
accounts were actually coordinating. `ml/synthetic.py` generates a
realistic background of ordinary payments and plants known ring patterns
(closed loops and collector hubs) inside it, with full ground truth, so the
graph algorithms can be evaluated against a known answer. The app can
analyze either: upload any transaction CSV, or load the built-in demo
network from the "Transaction data" page.

## Project structure

```
FraudGraph-AI/
├── app/
│   ├── __init__.py          # application factory
│   ├── cli.py                # flask init-db / generate-sample / create-user
│   ├── routes/                # main, auth, upload, analysis, dashboard (+ /api)
│   ├── services/               # data_service, anomaly_service, graph_service,
│   │                            #   fraud_ring_service, risk_service, settings
│   ├── models/                 # plain-SQL data access (users, datasets, runs,
│   │                            #   rings, account risk, flagged transactions)
│   ├── utils/                   # security (CSRF/auth/headers), formatting filters
│   ├── templates/                # Jinja templates (landing, auth, dashboard,
│   │                              #   upload, analysis results, ring detail)
│   └── static/                    # css/js, no build step
├── ml/
│   ├── synthetic.py            # planted-ring transaction network generator
│   ├── evaluation.py           # precision/recall/AUC, ring-level matching
│   ├── baseline.py             # transaction-only baseline for comparison
│   └── benchmark.py             # python -m ml.benchmark
├── data/{raw,processed,uploads}
├── tests/                        # pytest suite
├── config.py, run.py, wsgi.py, requirements.txt
```

## Running it

Requires Python 3.11+.

```bash
pip install -r requirements.txt
cp .env.example .env            # edit SECRET_KEY
export FLASK_APP=run.py

flask init-db                   # create the SQLite schema
flask generate-sample           # optional: write a sample CSV to data/raw/
flask create-user you@example.com --name "Your Name"   # optional: skip the web form

python run.py                   # http://127.0.0.1:5000
```

Or sign up through the web UI at `/register` and use the built-in demo
dataset from the "Transaction data" page — no file needed.

For production, run behind gunicorn (Linux/macOS) or waitress (Windows)
using `wsgi:app`, and set `FRAUDGRAPH_ENV=production` with a real
`SECRET_KEY`.

## Running the tests

```bash
pip install -r requirements-dev.txt
pytest
```

## Research: benchmarking the graph approach

```bash
python -m ml.benchmark              # 10 synthetic datasets, default size
python -m ml.benchmark --seeds 20 --accounts 1200 --normal 15000
```

This compares the full hybrid pipeline (Isolation Forest **+** graph/ring
detection) against a transaction-only Isolation Forest baseline, on
datasets with known planted rings. Representative results (8 seeds, 600
accounts, 6,000 ordinary transactions, 5 planted rings each; see
`docs/benchmark_results.txt` for the raw run):

| Metric | Transaction-only baseline | FraudGraph hybrid |
|---|---|---|
| ROC-AUC on labelled fraud transactions | 0.73 | **1.00** |
| Precision @ K (K = number of fraud transactions) | 0.00 | **0.99** |
| Planted rings recovered | — | **5 / 5 (100%)** |
| Ring-level precision | — | **100%** |

The baseline's low precision-at-K is expected and is the project's core
point: individually, camouflaged ring transactions sit inside the normal
amount distribution, so a per-transaction model ranks them no higher than
ordinary payments. The network signals — closed loops, pooling/forwarding,
repeated similar-sized transfers in a tight time window — are what actually
separate them out.

## Dataset guidance

The cleaner (`app/services/data_service.py`) accepts:
- your own `transaction_id, sender, receiver, amount, timestamp[, is_fraud]`
  layout, or
- common public layouts, e.g. PaySim's `nameOrig`/`nameDest`/`step`/`isFraud`.

For evaluation on a real public dataset (e.g. Kaggle's PaySim or IEEE-CIS),
upload the CSV as-is; if it has a `sender`/`receiver`-style relationship and
a fraud label, the results page will show precision/recall/ROC-AUC
automatically. Datasets without an explicit relationship column (fully
anonymized ones like IEEE-CIS) can still be analyzed for anomalies, but
won't produce meaningful rings — that's the gap the synthetic generator
exists to cover, as discussed in `docs/design-notes.md`.

## Configuration

Detection thresholds (cycle tolerance, ring size limits, score weights,
scoring thresholds, currency symbol, etc.) live in one place:
`config.py`'s `DETECTION` dict / `app/services/settings.py`. Nothing is
hard-coded in the detection services.

## Security notes

Passwords are hashed with Werkzeug's `generate_password_hash` (salted
scrypt); sessions are server-side signed cookies; every state-changing form
carries a CSRF token checked against the session; login attempts are
rate-limited per email+IP; CSV exports neutralize formula-injection
characters; a Content-Security-Policy and standard security headers are set
on every response. This is a research/demonstration project, not an
audited production system — see `docs/design-notes.md` for scope notes
before using it on real financial data.
