# FX Research Agent

An isolated, token-efficient research workspace for proposing, predeclaring,
testing, and reviewing FX hypotheses. It is not a trading service.

## Authority boundary

The research agent has no OANDA credentials and no broker code. Market data is
collected by a separate credentialed collector and exported through a sanitized,
immutable manifest. Exports may contain candles, bid/ask snapshots, spreads,
tick-rate and quote-pressure proxies, regime features, and data-quality flags.
They may not contain account, position, balance, order, transaction, token, or
credential fields.

Spot FX has no centralized tape. Any CVD-like field is explicitly labeled as an
OANDA venue quote/tick-pressure proxy, never as true market-wide volume.

## System of record

This repository becomes the canonical home for new research hypotheses. The
seven EUR agent records are imported once as immutable genesis history. The EUR
agent retains its existing rows as a historical downstream mirror.

```bash
python3 ops/research_supervisor.py init-db
python3 ops/research_supervisor.py import-genesis
python3 ops/research_supervisor.py status
python3 ops/research_supervisor.py backlog
python3 ops/research_supervisor.py sync-market-exports
python3 ops/research_supervisor.py market-data-status
python3 ops/research_supervisor.py sync-research-evidence
python3 ops/research_supervisor.py research-evidence-status
python3 ops/research_supervisor.py register-campaign
python3 ops/research_supervisor.py campaign-readiness CAMPAIGN_EUR_TREND_LOCATION_RANGE_FORWARD_V1
python3 ops/research_supervisor.py campaign-status
python3 ops/research_supervisor.py run-campaign CAMPAIGN_EUR_TREND_LOCATION_RANGE_FORWARD_V1
python3 ops/research_supervisor.py experiment-status CAMPAIGN_EUR_TREND_LOCATION_RANGE_FORWARD_V1
```

No command in this repository can place a trade or change another repository's
lifecycle state.

The normal forward data path is incremental: `eur_bot` writes compressed,
market-only packages under `exports/fx_research`, and this repository validates,
copies, and registers them. The importer rejects checksum mismatches, immutable
ID conflicts, stale/gapped packages for testing, and any broker-account field.
The installed one-shot launch agents run both sides every 15 minutes and write
local operational status to `data/eur_research_market_export.json` in the bot
and `data/market_ingest_status.json` plus `data/market_data_status.json` here.

Forward agent evidence follows a separate one-way boundary. `eur_agent`
exports only objective-level episode facts, locked trend/location/range context,
and `RULE_BASELINE` outcomes. LLM prompts, rationales, memory, provider data,
credentials, account state, and order state are rejected. Outcome sources remain
separate. The exporter and importer run as short one-shot launch agents every
15 minutes; `state = not running` with exit code 0 is normal between runs.

Campaigns are immutable drafts first. Approval requires the exact displayed
payload hash, a named human operator, and a reason. Approval seals the
experiment specification and controls but still does not run the experiment or
grant any downstream authority.

The experiment runner fails closed unless the campaign is approved and all
required data classes are available. Confirmatory evidence begins strictly
after the human approval timestamp, so previously observed outcomes can test
plumbing but cannot count toward the result. It keeps abstention
counterfactuals and shadow actions in separate cohorts, takes only the first
eligible baseline outcome per independent episode, and records immutable runs
and findings. Reaching a sample gate produces a human-review state only; it
cannot promote a hypothesis or affect a trading system.

The first campaign is registered as a draft under
`config/campaigns/eur_trend_location_range_forward_v1.json`. Once both data
feeds are healthy, its remaining blocker is deliberately human approval of the
exact displayed payload hash. Approval still does not execute the experiment.

