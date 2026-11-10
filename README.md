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

The supervisor discovers `eur_bot` and `eur_agent` as sibling repositories of
this checkout. Set `FX_RESEARCH_RUNTIME_ROOT` when all three repositories share
a different parent directory, or use `FX_RESEARCH_EUR_BOT_ROOT` and
`FX_RESEARCH_EUR_AGENT_ROOT` for individual overrides. This keeps one portable
configuration for macOS development and Linux runtime deployment.

This repository becomes the canonical home for new research hypotheses. The
seven EUR agent records are imported once as immutable genesis history. The EUR
agent retains its existing rows as a historical downstream mirror.

On the VPS, `ops/research_storage_backup.py` creates an integrity-checked SQLite
backup and retains the latest three copies by default. It is designed to run
from the shared Friday-close runtime backup service.

```bash
python3 ops/research_supervisor.py init-db
python3 ops/research_supervisor.py import-genesis
python3 ops/research_supervisor.py status
python3 ops/research_supervisor.py backlog
python3 ops/research_supervisor.py sync-market-exports
python3 ops/research_supervisor.py market-data-status
python3 ops/research_supervisor.py portfolio-opportunity-report
python3 ops/research_supervisor.py futures-context-status
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

## Medium-horizon G10 trend diagnostic

The locked G10 time-series momentum campaign evaluates one weekly 21/63/126-day
trend ensemble across seven liquid USD majors. It is deliberately spot-only and
cannot qualify for downstream use without observed historical financing or
forward points. Reproduce it with the commands in
`docs/G10_TIME_SERIES_MOMENTUM_DIAGNOSTIC.md`. The locked specification failed
dated confirmation and is closed; see `docs/G10_TIME_SERIES_MOMENTUM_RESULT.md`.

## Cross-asset research

`CAMPAIGN_CROSS_ASSET_ETF_TREND_V1` is the first cross-asset campaign. It tests
one monthly long-or-cash twelve-month trend specification across liquid ETFs,
with BIL as cash and explicit asset/class caps. Yahoo adjusted closes are
discovery-only. The primary was positive in every chronological partition and
under 25 bp cost stress, but failed the locked comparison because the
one-month-stale control was stronger. V1 is closed without retuning. Delayed
timing is only a proposed confirmatory lead requiring independent prices and
fresh evidence. See `docs/CROSS_ASSET_ETF_TREND_V1.md` and
`docs/CROSS_ASSET_ETF_TREND_RESULT.md`.

The V2 follow-up is now frozen in
`config/campaigns/cross_asset_etf_delayed_trend_v2.json`. It uses Twelve Data
as the independent split-and-dividend-adjusted source, treats all reused
history as measurement replication only, and writes only post-December-2026
resolved months to an immutable forward ledger. Setup and review boundaries
are documented in `docs/CROSS_ASSET_ETF_DELAYED_TREND_V2.md`. The independent
10 bp and 25 bp source replications passed; V2 remains non-promotable at `0/36`
fresh forward months. See `docs/CROSS_ASSET_ETF_DELAYED_TREND_V2_RESULT.md`.

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

### Pair-native motif batch

AUD/USD, USD/JPY, and GBP/USD now have their own outcome-blind discovery
contracts over sealed M15/H1/H4/D histories beginning in 2002. Discovery used
2010-2018 only; 2019-2022 validation and 2023+ holdout remained sealed. Three
motifs per pair were chosen from centroid descriptions before outcomes were
read. The batch allocates one third of the 5% familywise error budget to each
pair and applies Holm-Bonferroni within each nine-hypothesis pair family.

All 27 development hypotheses failed after a fixed 2.0-pip cost assumption.
The best average net R was `-0.068R` for AUD/USD, `-0.113R` for USD/JPY, and
`-0.081R` for GBP/USD. No validation or holdout data was opened, no campaign
was created, and no pair received shadow, paper, or live authority. The frozen
design and result are summarized in `docs/PAIR_NATIVE_MOTIF_BATCH_V1.md`.

The bot-side pair exporter continues to supply fresh market-only candles,
spreads, and bid/ask snapshots. That collection is useful for future
predeclared work but does not revive these rejected motifs.

### Portfolio and futures context

`portfolio-opportunity-report` reports raw forward candidate cadence and
trigger-day overlap. Raw candidates are explicitly not treated as validated
edge or qualified trade frequency. Current EUR evidence has abundant raw
events but substantial overlap among objective-level, ORB, VWAP, and trend
pullback families.

`futures-context-status` defines the inert centralized-futures boundary for
CME 6E, 6J, and 6A. True CVD requires aggressor-side centralized trade data;
OANDA quote/tick pressure remains a venue proxy. Until a feed is configured,
the status stays `UNCONFIGURED` and grants no signal or execution authority.

The first activation phase requires only completed CME 6E bars, so EUR/USD
futures context can be evaluated before purchasing or importing 6J and 6A.
The separate order-flow phase additionally requires classified centralized
buy/sell volume. A generic volume column is never accepted as true CVD.

Provider exports stay credential-free. Convert a provider CSV into an
immutable payload and manifest with:

```bash
python3 ops/cme_fx_context_import.py /path/to/6e.csv \
  --output-dir data/external_market_exports \
  --product 6E \
  --provider PROVIDER_NAME \
  --source-symbol PROVIDER_6E_SYMBOL \
  --contract-mode CONTINUOUS \
  --roll-method VOLUME_SWITCH \
  --price-adjustment BACK_ADJUSTED \
  --aggressor-side-method NONE
python3 ops/research_supervisor.py register-market-export \
  data/external_market_exports/<generated-manifest>.manifest.json
python3 ops/research_supervisor.py futures-context-status
```

Required CSV columns are `window_start_utc`, `window_end_utc`, `open`, `high`,
`low`, `close`, `volume`, and `trade_count`. Optional `open_interest`,
`aggressive_buy_volume`, and `aggressive_sell_volume` columns activate their
respective data classes only when complete and correctly labeled.

Databento batch packages can be ingested directly without converting or
altering their DBN source files:

```bash
python3 ops/databento_package_import.py /path/to/GLBX-JOB-ID
python3 ops/research_supervisor.py register-market-export \
  data/external/databento/GLBX-JOB-ID/GLBX-JOB-ID.market.manifest.json
python3 ops/research_supervisor.py futures-context-status
```

The importer verifies every provider checksum, preserves the original support
files, and records non-`available` condition dates as mandatory research
exclusions. A package with declared exclusions can be usable only because the
exclusion list is immutable and enforced by the futures payload contract.
Supported source schemas are one-minute or other OHLCV bars, trades, official
venue statistics, and point-in-time instrument definitions. Each is registered
under a distinct capability; statistics and definitions never imply trade-level
order flow, aggressor classification, or true CVD.

Once bars, official statistics, and point-in-time definitions are available for
`6E`, `6J`, and `6A`, build the causal continuous datasets with:

```bash
python3 ops/databento_continuous_build.py --product all --register
```

Export the latest causal 15-minute participation snapshot from the registered
6E/6J/6A continuous series with:

```bash
python3 ops/cme_forward_context_export.py
```

The atomic JSON pack under `exports/cme_forward_context/latest.json` contains
market context only and grants no downstream execution authority. The receiver
must record first ingestion time and reject stale or retroactive context. The
historical Databento packages do not update themselves; a current data source
is required before this export can accumulate forward evidence.

The versioned builder admits outright futures only, defines CME sessions at
17:00 America/Chicago, selects each target session's contract from the previous
valid completed session's volume leader, and ratio-adjusts rolls using only
prior-session closes. Provider-degraded UTC dates exclude every intersecting
CME session. `6J` OHLC is inverted with high/low swapped so its normalized
orientation matches `USD_JPY`. Outputs are checksum-validated Zstandard Parquet
artifacts and remain research context only.

The first locked use of those datasets tested whether centralized intraday
volume, last-known open interest plus settlement direction, or their
confluence improved one fixed prior-day accepted-breakout/retest setup across
EUR/USD, USD/JPY, and AUD/USD. Run the reproducible development-only evaluator
with:

```bash
python3 ops/futures_context_breakout_retest_research.py
```

All three filters failed. The unfiltered setup averaged `-0.371R`; the least
negative filter, aligned high-volume confirmation, averaged `-0.295R` over 700
events and did not clear the corrected significance or absolute-edge gates.
Validation (2023-2024) and dated confirmation (2025 onward) were not opened.
The exact campaign is parked without retuning and is summarized in
`docs/CME_FUTURES_CONTEXT_BREAKOUT_RETEST_RESULT.md`.

The separately predeclared EUR/USD agent-context diagnostic joined causal 6E
15-minute price, volume, range, and realized-volatility features to 69
independent failed-auction episodes. It failed: calibration worsened versus the
spot-only model, the current feature pack lost to a 24-hour-lagged control, and
the ranked outcome ordering was inverted. It does not justify agent activation
or a live CME subscription. See
`docs/EUR_CME_BAR_CONTEXT_DIAGNOSTIC_RESULT_V1.md` and reproduce with:

```bash
python3 ops/eur_cme_bar_context_diagnostic.py
```

A separately frozen short-horizon campaign tested whether a positive SPY
morning return predicted an executable long return from 15:30 through 15:55.
It failed across development, validation, and dated confirmation: 1,514 trades
could not cover the locked 2 bp per-side cost, and the signal did not beat the
opposite-morning control. It has no Alpaca paper authority and is closed without
retuning. See `docs/SPY_MORNING_MOMENTUM_LAST_HALF_HOUR_RESULT_V1.md`.

The next predeclared short-horizon campaign tests one cross-asset liquidity-
overshoot mechanism instead of another minute-timing variant. It buys the most
negative volatility-normalized five-session move among seven liquid ETFs,
enters at the next open, exits at the third session close, and evaluates 5 and
10 basis points per side against recent-winner, random, SPY, and BIL controls.
The threshold and holding period are frozen with no sweep or automatic paper
authority. See `docs/CROSS_ASSET_SHORT_TERM_REVERSAL_V1.md` and run:

```bash
python3 ops/alpaca_cross_asset_daily_extract.py
python3 ops/cross_asset_short_term_reversal_research.py
```

The locked historical result was a positive but insufficient near-miss. It
produced 378 non-overlapping events at roughly 0.68 per week and positive
excess-BIL averages in every chronological partition, but missed the frozen
positive-rate and significance gates at both cost levels. It is closed without
retuning or paper authority. See
`docs/CROSS_ASSET_SHORT_TERM_REVERSAL_RESULT_V1.md`.

A second, futures-native campaign then tested two mechanisms directly on the
centralized data: participation-shock acceptance continuation and
participation-shock failed-auction reversal. Both used volume at least `1.75x`
and true range at least `1.5x` their prior-only, time-of-day baselines. Neither
survived. Continuation averaged `-0.324R` over 4,573 events and reversal
averaged `-0.295R` over 2,477; both also trailed their paired controls. The
2023+ partitions remain sealed. See
`docs/CME_FUTURES_PARTICIPATION_SHOCK_RESULT.md`.

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
For strategy-shadow campaigns, distinct event IDs are not automatically
independent. The evaluator keeps only the first event in each non-overlapping
fixed outcome horizon, separately by outcome source and cohort, so overlapping
signals cannot inflate the effective sample size.

The London ORB V3 confirmation is a single predeclared paired experiment. It
compares the first failed-break reversal of each London trading day with a
breakout-direction control from the identical trigger. Its first review is
fixed at 30 resolved pairs and additionally requires positive treatment net R,
positive paired lift, at least 44% positive outcomes, and positive average net
R in both chronological halves. Prior broad-ORB outcomes cannot qualify.

The Asia ORB V1 confirmation applies the same paired research design to the
Tokyo 09:00 local opening range. It has independent setup IDs, a Tokyo-local
daily first-event lock, and its own 30-pair review gate. Asia evidence cannot be
pooled with London evidence, and neither campaign can activate execution.

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

The official-positioning campaign in
`config/campaigns/cftc_tff_fx_crowding_reversal_v1.json` is one frozen
development-only test of newly re-armed CFTC leveraged-money extremes in EUR,
JPY, and AUD futures. It applies a conservative eight-day publication lag,
prior-only z-scores, non-overlapping daily holding windows, fixed ATR geometry,
two controls, and Holm-Bonferroni correction across the three pairs. Validation
and holdout remain sealed unless development survives and a human explicitly
opens the next stage. See `docs/CFTC_TFF_FX_CROWDING_CAMPAIGN.md`.

The locked development run produced no survivors. USD/JPY was promising but
underpowered at 14 independent episodes and failed its worst-year and
familywise-significance gates; EUR/USD was near flat and lost to the shifted
control; AUD/USD was negative. Validation and holdout stayed sealed. See
`docs/CFTC_TFF_FX_CROWDING_RESULT.md`.

Refresh the official public positioning file and run the locked development
stage with:

```bash
python3 ops/cftc_tff_fx_extract.py \
  --contract config/cftc_tff_fx_positioning_data_contract.json \
  --output data/external/cftc/tff_fx_positioning.csv.gz \
  --summary data/external/cftc/tff_fx_positioning.summary.json
python3 ops/cftc_tff_positioning_research.py
```

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

For unattended reconciliation, install
`ops/com.camcam.fx-research-agent.result-reconciliation.plist.example` as a
LaunchAgent. It watches the bot's result-export directory for immediate imports
and also runs at 17:05 local time as a daily fallback. Normal and unchanged
syncs are silent; rejected or conflicting packages use the existing low-noise
Discord ingest-failure notification path.

