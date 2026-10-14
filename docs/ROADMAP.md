# Roadmap

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
- Keep the first locked campaign in draft until a human approves its exact hash;
  campaign approval remains separate from experiment execution.
- Evaluate approved campaigns only on post-approval evidence, deduplicated by
  independent episode and separated by outcome source.
- Persist immutable run and finding records; sample completion permits human
  review, never automatic promotion or downstream activation.

## Phase 3: token-efficient assistance

- Use deterministic screening to find data gaps, near-misses, and unanswered questions.
- Run approved deterministic evaluations daily and immediately when a sealed
  sample threshold is first crossed.
- Cap the active confirmatory batch at three campaigns and apply its locked
  Holm-Bonferroni familywise-error policy.
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

