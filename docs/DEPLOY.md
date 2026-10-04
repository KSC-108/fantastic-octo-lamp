# Deploying OctoQuant

The system is one process: a FastAPI dashboard plus a scheduler thread that runs the daily paper
cycle after the NSE close (default 16:10 IST on weekdays that are not in `runtime.holidays`).
It needs a persistent disk for the SQLite database, trained model and strategy files.

> The Docker image and these steps were written but **not executed** in the build environment
> (no running Docker daemon, and NSE was unreachable). Treat them as a starting point and verify.

## 1. Prepare on a host that can reach NSE

```bash
git clone <your repo> && cd fantastic-octo-lamp
python -m venv .venv && . .venv/bin/activate && pip install -e ".[nse]"
octoquant --config config/nse.yaml research
```

Read `strategy.md`. If it says **REJECTED**, the paper runner will refuse to trade. That is the
system working as designed. Do not loosen the gates to get a pass.

NSE can block datacenter IP ranges. If fetches fail from your cloud host, run `research` and the
daily data fetch from a host that works, or supply data by CSV (`data.source: csv`).

## 2. Secrets

Copy `.env.example` to `.env` (never commit it).

| Variable | Purpose |
|---|---|
| `DASHBOARD_TOKEN` | Required for the kill and resume endpoints. If unset they return 403. |
| `TELEGRAM_BOT_TOKEN`, `TELEGRAM_CHAT_ID` | Alerts. Create a bot with BotFather, message it once, then read your chat id from `getUpdates`. |
| `ANTHROPIC_API_KEY` | Optional. Enables `octoquant review --llm`. |

## 3. Run

**Docker (VPS, Mac Mini, any container host):**

```bash
docker compose up -d --build        # restart: unless-stopped gives automatic restart
```

The compose file mounts `data/`, `artifacts/` and `reports/`. Run `research` first so
`artifacts/strategy.yaml` and `artifacts/bank.joblib` exist.

**Plain VPS with systemd:**

```ini
[Service]
WorkingDirectory=/opt/octoquant
EnvironmentFile=/opt/octoquant/.env
ExecStart=/opt/octoquant/.venv/bin/octoquant --config config/nse.yaml serve --port 8000
Restart=always
```

**Serverless hosts (for example Vercel) are a poor fit.** The scheduler thread and SQLite file need
a long-running process with a persistent disk. Use a VPS, a container host with a volume, or a Mac Mini.

Put the dashboard behind HTTPS and an auth proxy if it is reachable from the internet. It is read-only
except for the token-protected kill and resume endpoints.

## 4. Operate

| Task | Command |
|---|---|
| Health | `GET /healthz` |
| Emergency stop | `octoquant kill --reason "..."` or `POST /api/kill` with `X-Dashboard-Token` |
| Clear the kill switch | `octoquant kill --resume` (human action only) |
| Nightly review | cron: `octoquant --config config/nse.yaml review --llm` |
| Pre-live checklist | `octoquant preflight` |

Keep `runtime.holidays` current. A missed holiday makes the job look for a bar that does not
exist, and the runner then aborts with a "stale data" alert instead of trading on old data.

## 5. Going live

Not supported by this build. `octoquant live` refuses, and `preflight` will not clear without a
tested broker adapter, real-data evidence, a paper track record and an attestation that broker keys
are trade-only with withdrawals disabled.
