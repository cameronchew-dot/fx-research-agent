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
python3 ops/research_supervisor.py literature-panel-status
python3 ops/research_supervisor.py sync-research-evidence
python3 ops/research_supervisor.py research-evidence-status
python3 ops/research_supervisor.py register-campaign
python3 ops/research_supervisor.py campaign-readiness CAMPAIGN_EUR_TREND_LOCATION_RANGE_FORWARD_V1
python3 ops/research_supervisor.py campaign-status
python3 ops/research_supervisor.py run-campaign CAMPAIGN_EUR_TREND_LOCATION_RANGE_FORWARD_V1
python3 ops/research_supervisor.py experiment-status CAMPAIGN_EUR_TREND_LOCATION_RANGE_FORWARD_V1
python3 ops/research_supervisor.py register-autonomy-policy
python3 ops/research_supervisor.py register-batch
python3 ops/research_supervisor.py automation-status
python3 ops/research_supervisor.py batch-status
python3 ops/research_supervisor.py add-campaign-to-batch BATCH_ID CAMPAIGN_ID --added-by CAMERON --reason "Reviewed"
python3 ops/research_supervisor.py refresh-approved-campaigns --trigger MANUAL
python3 ops/research_supervisor.py proposal-cycle
python3 ops/research_supervisor.py proposal-status
python3 ops/research_supervisor.py review-hypothesis HYPOTHESIS_ID --decision REJECT --reviewed-by CAMERON --reason "Reviewed"
```

## Low-noise research alerts

Set `FX_RESEARCH_DISCORD_WEBHOOK_URL` in the local `.env` to receive alerts only
when an approved campaign crosses its predeclared sample gate, an ingest fails,
or a machine proposal passes deterministic filters and needs human review.
Routine syncs and evaluations stay silent. Successful deliveries are recorded
once in SQLite, so scheduler reruns cannot repeat the same alert. Delivery
failures do not stop research jobs, and notifications grant no authority.

```bash
python3 ops/research_supervisor.py notification-status
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

The governed EUR/USD batch retains its original three-slot boundary and contains three explicitly approved campaigns,
each accruing only evidence observed after its own approval timestamp:

- trend alignment, objective location, and reward room;
- decision spread relative to the prior 96 completed M15 bars; and
- first-touch versus repeat-touch objective-level history.

The exact specifications live under `config/campaigns/`. A separate seven-slot
literature-replication batch expands total governed capacity to ten without
rewriting the original batch. Its first predeclared campaign is the published
G10 MOM(1,1) cross-sectional currency momentum strategy. It remains data-blocked
until every currency has a common completed month-end panel, financing or forward
points, implementable bid/ask costs, and computed excess returns. MOM(6,1) and
MOM(12,1) are descriptive only and cannot qualify. Each batch uses its own locked
Holm-Bonferroni familywise-error budget. No campaign can promote itself or affect
a downstream system.

Campaign 4's market input follows `config/g10_literature_panel_contract.json`.
Each currency is imported as an immutable monthly panel using normalized USD
quotes, observed one-month forward points or observed historical financing,
and historical bid/ask transaction costs. The importer independently recomputes
gross and net excess returns. Spot-only panels, inferred or zero-filled
financing, incomplete currency coverage, and fewer than 192 common months remain
blocked. Use `literature-panel-status` to see the exact coverage shortfall.
Use `financing-source-status` to inspect the upstream source-acquisition gate.
Its committed catalog distinguishes spot-only, current-only, benchmark-only,
unacquired licensed, and complete acquired sources. Discovering a paper or a
replication workbook does not unlock the campaign by itself.

## Governed autonomy

The automation policy permits at most ten concurrent campaigns across the
immutable three-slot EUR batch and separate seven-slot literature batch. Evidence
ingestion checks whether a predeclared sample gate has just been crossed, and a
daily local job refreshes all approved evaluations at 17:00. Repeated ingests
with no new immutable evidence manifest skip evaluation work. Approved campaigns
whose data is incomplete are explicitly skipped as `BLOCKED_DATA_READINESS`, so
one unavailable literature dataset cannot disrupt the existing forward campaigns.

Once per week while the FX market is closed, a bounded Anthropic Sonnet call
may draft at most three hypotheses. It receives the registry, available data
classes, and sealed campaign specifications, but never findings, net R, or
hidden holdouts. Deterministic filters reject duplicates and proposals that
need unavailable data. Survivors enter only `PROPOSED`; they cannot create a
campaign, approve themselves, export downstream, or place an order.
The proposer also pauses without making a provider call whenever three
machine-authored proposals are already awaiting human review.

Copy `.env.example` to `.env` and set `FX_RESEARCH_ANTHROPIC_API_KEY` before
enabling the optional weekly proposal job. This credential is kept separate
from the EUR trading agent. All routine ingestion and evaluation remains
model-free and consumes no provider tokens.

