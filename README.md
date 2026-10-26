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
python3 ops/research_supervisor.py park-campaign CAMPAIGN_ID --expected-payload-hash HASH --parked-by NAME --reason "Reason"
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
python3 ops/research_supervisor.py motif-build-matrix
python3 ops/research_supervisor.py motif-discover --matrix-metadata data/motif_discovery/MATRIX_ID.json
python3 ops/research_supervisor.py motif-predeclare
python3 ops/research_supervisor.py motif-register-evaluation
python3 ops/research_supervisor.py motif-evaluate-development --matrix-metadata data/motif_discovery/MATRIX_ID.json
python3 ops/research_supervisor.py motif-status
python3 ops/research_supervisor.py context-coverage-audit
python3 ops/research_supervisor.py context-build-matrix
python3 ops/research_supervisor.py context-discover --matrix-metadata data/context_discovery/MATRIX_ID.json
python3 ops/research_supervisor.py context-discovery-status
python3 ops/research_supervisor.py context-export-labels --matrix-metadata data/context_discovery/MATRIX_ID.json
```

## FX motif discovery

`FX_MOTIF_DISCOVERY_V1` adds a research-only discovery lane modeled on the
useful parts of the BTC bot's raw-context discovery process while retaining the
FX system's stricter evidence boundary. A credentialed collector first seals a
market-only historical candle export. The research agent then builds
point-in-time M15 features with completed H1/H4/D context, fits deterministic
clusters on the declared development period only, assigns stable machine IDs,
and records the complete planned hypothesis count before any outcomes are
examined.

The initial discovery report is descriptive. It reads zero validation or
holdout outcomes, makes no profitability claim, cannot create a campaign, and
has no downstream or execution authority. Any cluster selected for evaluation
must become a separately reviewed, predeclared experiment using the existing
controls, cost, OOS, dated-confirmation, and false-discovery gates.

The first blind review is frozen in `fx_motif_predeclaration_v1.json`. Its five
descriptive states, exact execution geometry, costs, controls, independence
rules, objective gates, and 15-test Holm family cannot change after outcomes
are seen. Registration itself reads no outcomes and keeps 2023+ sealed.

The frozen development evaluation subsequently tested all 15 primaries and
their controls. None produced positive average net R after the declared
1.9-pip friction, so no hypothesis received validation access. The exact
result is archived in `docs/FX_MOTIF_DEVELOPMENT_RESULT.md`; there was no
retuning.

## FX context discovery

`EUR_USD_CONTEXT_DISCOVERY_V1` is the next outcome-blind discovery lane. It
uses sealed, market-only historical candles for EUR/USD, EUR/GBP, EUR/JPY,
gold, two equity-index proxies, and US/German ten-year bond CFDs. Every context
candle must have completed by the EUR/USD M15 decision time. The committed
contract fixes the source roles, development window, feature names, clustering
budget, and exclusions before any profitability outcome is examined.

Run `context-coverage-audit` after syncing the dedicated historical exports.
The audit counts only the declared development interval and records immutable
source hashes. It cannot evaluate returns, create campaigns, export downstream,
or change paper/live state. Markov and HMM snapshots, partial GARCH history,
and macro artifacts without complete release-lagged point-in-time history are
explicitly excluded from V1 rather than treated as historical context.

Once coverage passes, `context-build-matrix` creates a development-only,
point-in-time feature matrix. `context-discover` fits the frozen deterministic
20-cluster model and reports descriptive centroids only. It assigns no trade
direction, entry, stop, target, or horizon and reads no outcome.

The completed V1 matrix contains 106,426 development decisions and 26 context
features. The frozen 20-cluster run converged without reading outcomes. Its
descriptive review and immutable IDs are recorded in
`docs/FX_CONTEXT_DISCOVERY_V1.md`; the next gate is a small blind human
selection, not automatic outcome evaluation.

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
`RULE_BASELINE` outcomes, and deterministic strategy-expansion shadow
events/outcomes. The expansion batch separately evaluates accepted
breakout/retests, ORB reversals, VWAP reclaim, VWAP stretch reversion, and
HTF-aligned trend pullbacks. A separate one-slot confirmatory batch evaluates
prior-week/month failed auctions under the locked V2 shadow specification.
LLM prompts, rationales, memory, provider data,
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

The exact specifications live under `config/campaigns/`. The original
literature-replication batch contains the published G10 MOM(1,1)
cross-sectional currency momentum specification. That campaign is parked,
without deleting its immutable history, because a complete historical
financing or forward-point panel is unavailable. MOM(6,1) and MOM(12,1) remain
descriptive only and cannot qualify.

The one-campaign AUD/USD pair-native batch in
`config/batches/audusd_pair_native_v1.json` preserves a proposed
daylight-saving-aware Sydney opening-range failed-auction specification. A
cross-repository audit performed before any evidence was ingested found that
the EUR bot had already rejected the same underlying AUD/USD Asia-range
failed-break mechanism on deep history. The research-agent campaign is
therefore parked without evaluation or parameter adjustment. It does not
consume active global capacity and has no downstream or order authority.

The separate China-proxy campaign in
`config/batches/audusd_china_proxy_v1.json` predeclared one exact AUD/USD-
USD/CNH Asia lead-lag rule before historical outcomes were inspected. The
locked evaluation produced 1,329 independent development events with
`-0.242634R` average net return and 337 dated-confirmation events with
`-0.241608R` average net return. It was parked without retuning. The immutable
campaign event preserves the exact payload hash and result summary; it consumes
no active campaign capacity and has no downstream or order authority.

Each batch uses its own locked Holm-Bonferroni familywise-error budget. No
campaign can promote itself or affect a downstream system.

The tenth active campaign is
`CAMPAIGN_EUR_PRIOR_WEEK_MONTH_FAILED_AUCTION_V1`. It counts only completed
M15 events observed strictly after human approval, enters at the next M15 open
with observed spread, uses a signal-extreme-plus-buffer stop, a `1.5R` target,
and a 16-bar horizon. Prior-week and prior-month levels remain separately
reported, but their descriptive splits cannot be promoted independently. The
campaign requires 30 resolved independent events and positive average net R
before human review; it cannot retune itself or activate downstream behavior.

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

The automation policy permits at most ten distinct approved campaigns across
all immutable batches. Parked campaigns and duplicate immutable memberships do
not consume active capacity. Evidence
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

Import immutable, checksummed locked-research results from the EUR/USD bot:

```bash
python3 ops/research_supervisor.py sync-research-results
python3 ops/research_supervisor.py research-result-status
```

Imported results are historical research evidence only. They cannot approve a
campaign, activate a downstream profile, or grant order authority.

