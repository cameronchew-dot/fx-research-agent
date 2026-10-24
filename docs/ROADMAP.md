# Roadmap

## Operations

- Low-noise Discord notifications cover sample-gate crossings, ingest failures,
  and machine proposals awaiting review. They stay inert until the dedicated
  webhook variable is configured locally.

## Phase 1: system of record

- Import the seven EUR agent hypotheses as immutable genesis history.
- Produce one consolidated backlog and status report.
- Validate sanitized market-data manifests and reject sensitive fields.
- Preserve source repository, commit, path, timestamps, and payload hashes.
- Import compressed forward market-data deltas and report freshness, gaps, and
  row counts without broker credentials.
- Import sanitized forward episode, objective-level, context, and baseline
  outcome evidence while keeping outcome sources separate.

## Phase 2: controlled research campaigns

- Register immutable draft campaign records for one pair and one mechanism at a time.
- Require an exact payload-hash match and named human approval before sealing
  an experiment specification; approval never starts a run automatically.
- Lock exact hypotheses, geometry, controls, holdouts, and stopping rules before testing.
- Import completed-candle and market-proxy exports from the credentialed collector.
- Track every run, failure, control, and finding without overwriting history.
- Register the outcome-blind `EUR_USD_MOTIF_CONFIRMATION_V1` selection before
  implementing its development-only evaluator; keep 2023+ data sealed.
- Maintain the three exact-hash-approved EUR/USD campaigns as one fixed
  confirmatory batch: trend/location/room, spread/liquidity degradation, and
  first-touch versus repeat-touch degradation.
- Maintain a separate seven-slot literature-replication batch. Campaign 4 is a
  fixed G10 MOM(1,1) cross-sectional excess-return replication; Campaigns 5-10
  are reserved for carry, value, economic momentum, output-gap differential,
  central-bank restrictiveness, and USD/JPY intervention regime research.
- Require every multi-instrument campaign to have complete per-instrument data
  classes before evaluation. Data-blocked campaigns are skipped without
  interrupting ready forward campaigns.
- Follow `G10_MOMENTUM_DATA_SOURCE_PLAN.md` for Campaign 4. Do not reinterpret
  public spot histories as the missing historical financing/forward leg.
- Campaign 6 is the single locked five-year real-exchange-rate value
  replication in `G10_VALUE_CAMPAIGN.md`. It uses BIS spot and official OECD
  CPI with a fixed two-month information lag and never claims to measure
  financing-inclusive currency excess returns. Its locked run failed the
  chronological OOS gate; see `CAMPAIGN_6_RESULT.md`. It is closed and does not
  consume an active literature-batch slot.
- Campaign 9 is one locked inflation-adjusted central-bank stance-shift test,
  documented in `G10_POLICY_STANCE_CAMPAIGN.md`. Its specification and code
  were committed before historical inspection. The exact strategy was negative
  in development, OOS, and dated confirmation and is closed; see
  `CAMPAIGN_9_RESULT.md`. The positive opposite-direction control is post-result
  evidence only and cannot be recycled against the used holdout.
- Campaign 7 is one locked 60-month industrial-production momentum test on the
  six-currency subset with complete OECD monthly history. Its exact universe,
  two-month information lag, top-two/bottom-two construction, costs, and
  controls are documented in `G10_ECONOMIC_MOMENTUM_CAMPAIGN.md`. Its locked
  run failed chronological OOS and the stale-signal control; see
  `CAMPAIGN_7_RESULT.md`. It is closed and does not consume an active
  literature-batch slot.
- Campaign 8 is one locked recursive Hamilton output-gap test using the same
  official industrial-production source but a distinct cyclical-residual
  mechanism. Its filter, lag, portfolio, costs, controls, and real-time-vintage
  caveat are documented in `G10_OUTPUT_GAP_CAMPAIGN.md`. Its locked run failed
  chronological OOS, cost stress, and the stale-signal control; see
  `CAMPAIGN_8_RESULT.md`. It is closed and does not consume an active
  literature-batch slot.
- Campaign 10 is a locked retrospective audit of official Japanese USD/JPY
  intervention episodes. Exact MOF dates are delayed labels, so the audit can
  only support later observable-proxy design and can never directly become a
  strategy or lifecycle profile. Policy-aligned returns were positive in
  development, chronological OOS, dated confirmation, and cost stress, but the
  audit failed its predeclared +60-trading-day control and minimum dated-control
  sample gate. It is closed without a proxy campaign; see
  `CAMPAIGN_10_RESULT.md`.
- Evaluate approved campaigns only on post-approval evidence, deduplicated by
  independent episode and separated by outcome source.
- Persist immutable run and finding records; sample completion permits human
  review, never automatic promotion or downstream activation.

## Phase 3: token-efficient assistance

- Use deterministic screening to find data gaps, near-misses, and unanswered questions.
- Run approved deterministic evaluations daily and immediately when a sealed
  sample threshold is first crossed.
- Preserve the original three-campaign batch and permit a separate seven-slot
  batch, for ten governed campaign slots total. Apply each batch's locked
  Holm-Bonferroni familywise-error policy independently.
- Permit one bounded weekly Anthropic proposal cycle to draft no more than
  three proposals, only into `PROPOSED` state.
- Keep proposal context blind to findings, net R, and hidden holdouts; reject
  duplicate and unavailable-data proposals deterministically.
- Require human approval before predeclaration or experiment execution.
- Record model, prompt, input hashes, token use, and proposal lineage.

## Phase 4: downstream handoff

- Build signed/checksummed, market-only research packs.
- Require explicit human approval for export.
- Let each receiving bot or agent apply its own validation and lifecycle gates.
- Never grant this repository shadow, paper, promo, live, or order authority.

## Phase 5: raw FX motif discovery

- Seal historical EUR/USD M15/H1/H4/D candles through the existing one-way,
  market-only export boundary.
- Build a versioned point-in-time feature matrix with no strategy labels or
  future outcomes.
- Fit deterministic development-only clusters and assign stable machine IDs.
- Record the full cluster x direction x horizon hypothesis budget before any
  outcome evaluation and require Holm-Bonferroni correction later.
- Keep validation and the 2025+ holdout untouched until a human chooses and
  predeclares an exact cluster expression.
- Add runtime matching, forward snapshots, decay retirement, and dormant
  reactivation only after a motif survives the full confirmation pipeline.
- Archive the completed V1 motif evaluation as `NO_DEVELOPMENT_SURVIVORS`; do
  not retune these five states or open validation in response to rejection.

## Phase 6: cross-market FX context discovery

- Audit sealed historical coverage before building a feature matrix.
- Use EUR/GBP and EUR/JPY for EUR-specific confirmation, gold for broad-dollar
  context, SPX500/NAS100 for risk regime, and US/German ten-year bond CFDs for
  yield-shock proxies.
- Require completed-bar, point-in-time joins at every EUR/USD M15 decision.
- Keep Markov/HMM snapshots, partial GARCH history, and incomplete release-
  lagged macro histories outside V1.
- Freeze the exact development feature set and cluster budget before reading
  any outcome; keep 2023-2024 validation and 2025+ holdout sealed.
- Permit no campaign, downstream export, paper, or live authority from coverage
  readiness alone.
- Coverage, the 106,426-row matrix, and the frozen 20-cluster descriptive run
  are complete. No direction, geometry, or outcome comparison has been assigned.
- Next require a small blind human selection and a separate immutable
  predeclaration before implementing any development outcome evaluator.

