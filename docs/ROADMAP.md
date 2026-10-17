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

