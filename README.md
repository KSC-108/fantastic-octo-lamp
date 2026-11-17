# OctoQuant

A cloud-hosted, risk-first research and paper-trading system for NSE equities.

A language model does the research and review. Deterministic, tested code makes every decision
that touches money. **Paper trading only: this build has no live broker adapter.** Research
software, not financial advice.

Planning document: [`docs/PLAN.md`](docs/PLAN.md).

## What it does

| Capability | Where |
|---|---|
| NSE daily data (OHLCV, VWAP, delivery %) via the public [`jugaad-data`](https://pypi.org/project/jugaad-data/) library, CSV import, synthetic market for tests | `src/octoquant/data/` |
| Point-in-time state snapshot per stock and day | `features.py` |
| Five calibrated probability questions: regime, direction, buying pressure, setup quality, risk state | `models.py`, `calibration.py` |
| Walk-forward research with embargoed labels, validation-only parameter search, one-shot test, acceptance gates | `walkforward.py`, `research.py` |
| Backtest and paper trading on the **same** simulator step, Indian delivery costs, slippage, gap-aware stops | `engine.py`, `costs.py` |
| Capped fractional Kelly sizing, hard risk limits, persistent kill switch | `sizing.py`, `risk.py` |
| Decision log with outcomes, live calibration monitoring, daily report | `runtime/` |
| Live dashboard, Telegram alerts through a BotFather bot | `runtime/dashboard.py`, `runtime/notify.py` |
| Nightly review: one bounded, gate-validated rule proposal (Anthropic API optional) | `review.py` |
| Preflight report "What could blow up this account?" that refuses to clear live trading | `preflight.py` |
| Index options: Black-Scholes pricing and greeks, NSE bhavcopy import, 10 strategy templates, backtest and paper book on one simulator step | `options/` |
| Dashboard charts: equity, drawdown, monthly-return heatmap, trade distribution, options greeks, payoff diagrams, strategy comparison | `runtime/dashboard.html` |

## Quick start

```bash
python -m venv .venv && . .venv/bin/activate
pip install -e ".[dev]"          # add ,nse for real NSE data and ,llm for the Anthropic API
pytest                           # ~1 minute

octoquant demo                   # end-to-end on SYNTHETIC data into ./demo_run
octoquant --workdir demo_run serve --port 8000    # dashboard at http://localhost:8000
```

### With real NSE data

Run from a host that can reach `nseindia.com` (some cloud and datacenter IP ranges are blocked):

```bash
pip install -e ".[nse]"
octoquant --config config/nse.yaml research       # walk-forward, gates, strategy.md, model
octoquant --config config/nse.yaml serve          # dashboard plus daily paper-trading job
```

`research` writes `strategy.md` (entry, exit, stop, take profit, timeframe, invalidation rule)
and `artifacts/strategy.yaml`. The paper runner refuses to trade a strategy that failed the gates.

## Commands

| Command | Purpose |
|---|---|
| `research` | Walk-forward research, gates, `strategy.md`, trained model |
| `backtest` | Re-run the accepted strategy on its test window |
| `paper-run` | One daily cycle (`--expected-date` aborts on stale data) |
| `serve` | Dashboard plus the IST daily scheduler |
| `review` | Nightly slow-brain review (`--llm` uses the Anthropic API if `ANTHROPIC_API_KEY` is set) |
| `preflight` | Writes `reports/preflight.md` |
| `kill` / `kill --resume` | Trip or clear the kill switch |
| `approve ID` | Release an order held for manual approval |
| `live` | Always refuses in this build |
| `demo` | End-to-end run on synthetic data |
| `options strategies` | List the strategy templates and their legs |
| `options backtest [--strategy X] [--all]` | Backtest one strategy, or every strategy in `options.compare`; stores results for the dashboard and writes `reports/options_backtest.md` |
| `options paper-run` | Step the options paper book to the latest data (refuses a strategy that failed the gates unless `--allow-unvalidated`) |
| `options ticket STRATEGY [--expiry --lots --width --wing]` | Manual paper ticket, sized and margin-checked, fills at the next open |
| `options close ID` / `options kill [--resume]` | Close a paper position at the next open / options kill switch |
| `options demo` | Synthetic underlying, model-priced options: compare strategies, then replay 30 days through the paper book |

## Options module

Paper only. Ten templates (iron condor, iron butterfly, short and long straddle and strangle, bull and bear
put and call spreads), legs placed in strike steps from ATM. The rule enters once per expiry when calendar
DTE falls to `entry_dte`, and exits on a stop (a multiple of the credit, or a share of the debit), a profit
target, a DTE cut-off, or cash settlement at expiry. Sizing caps the rupee loss per position (max loss for
defined-risk structures, the stop loss for naked ones) and total blocked margin. A drawdown kill switch
flattens the book. Every decision uses the close of day *t*; every fill is at the open of *t+1*.

**Two price sources**

| `options.source` | Prices | What a result means |
|---|---|---|
| `model` (default) | Black-Scholes on the underlying. Volatility from a `vix` column if the underlying CSV has one, else 20-day realised vol x `iv_multiplier` | Checks the machinery. No skew, no real premia: **not evidence of an edge** |
| `bhavcopy` | Traded closes and opens from NSE F&O bhavcopy files | The meaningful backtest |

**Importing historical data.** Drop NSE F&O bhavcopy CSVs into `data/options/` (git-ignored) and set
`options.source: bhavcopy`. Three layouts are read:

- the old format (`INSTRUMENT, SYMBOL, EXPIRY_DT, STRIKE_PR, OPTION_TYP, OPEN, ..., CLOSE, SETTLE_PR, ..., TIMESTAMP`),
- the UDiFF format NSE has published since July 2024 (`TradDt, FinInstrmTp, TckrSymb, XpryDt, StrkPric, OptnTp, OpnPric, ClsPric, SttlmPric, UndrlygPric, ...`),
- a generic chain export with columns `date, expiry, strike, option_type, open, close[, settle, oi, underlying]`.

Spot comes from the underlying column, else `options.underlying_csv`, else put-call parity on the nearest
expiry. Contracts with no positive close or settlement price are treated as untradable.

```bash
octoquant options backtest --all          # compare strategies; open the dashboard's "Options backtests" tab
octoquant options ticket iron_condor --lots 1
octoquant options paper-run --allow-unvalidated
```

Assumptions to verify before trusting any rupee figure: lot size (75), weekly expiry weekday (Tuesday, model
chain only), STT and exchange charges in `options.costs`, and the naked-short margin (12% of notional, a stand-in for SPAN).

## Design rules

1. **Models advise, code decides.** Thresholds, sizing, risk vetoes and orders are plain functions.
2. **No look-ahead.** Features use data up to the close of day *t*. Orders fill at the open of *t+1*.
   Training rows are embargoed by the longest label horizon. This is tested.
3. **Hard limits are out of any model's reach.** The slow brain may only change a whitelisted
   strategy threshold within fixed bounds, and only if the walk-forward gates confirm it helps.
4. **A failed gate is a valid result.** The harness is checked on markets with no edge and must reject them.
5. **Secrets stay in the environment.** Copy `.env.example` to `.env`; it is git-ignored.

## Limitations you should know about

- **No result here is evidence of an edge on NSE.** Everything in this repository was developed and
  tested on synthetic data because the build environment could not reach NSE. The NSE adapter's
  column mapping is tested against the library's own headers, but it has not fetched live data.
- Free NSE history is end-of-day, so the strategy is daily-bar and long-only. Intraday needs a broker feed.
- Options results on the model chain are not evidence of anything. Naked short options can lose more than the
  stop-loss budget in a single gap; the backtest shows this, and sizing cannot prevent it.
- Order book imbalance and spread are not in free data. Delivery % and close location are used instead.
- Cost rates (STT, stamp duty, exchange charges, DP charge) are assumptions. Check your contract note.
- The default universe is today's NIFTY constituents, which introduces survivorship bias.
- Searching many parameter sets raises the chance of a lucky result. The trial count is recorded in `strategy.md`.
- The Docker image and GitHub Actions workflows were written but not run in the build environment.

## Deployment

See [`docs/DEPLOY.md`](docs/DEPLOY.md).
