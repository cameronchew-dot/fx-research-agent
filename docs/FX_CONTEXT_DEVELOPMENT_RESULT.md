# FX Context Development Result V1

## Decision

`FX_CONTEXT_DISCOVERY_V1` produced no development survivors. Archive this
confirmation pass without retuning its directions, geometry, cluster selection,
or thresholds.

The outcome-blind predeclaration was committed as `3cdb377` before any outcome
evaluation. The evaluator then ran the sealed 18-hypothesis family once on the
development window.

## Result

- Evaluation: `CONTEXT_DEVELOPMENT_EVALUATION_78f1119e280bffdfaf06`
- Development survivors: `0 / 18`
- Event-ledger rows: `7,332`
- Independent events per hypothesis: `43` to `1,046`
- Validation rows inspected: `0`
- Holdout rows inspected: `0`
- Campaigns or downstream exports created: `0`
- Paper/live authority: `false`

The least-negative primary hypothesis was
`POSITIVE_BOND_PRICE_SPREAD_SHOCK SHORT H4`:

- independent events: `246`
- calendar months: `41`
- average net R: `-0.0843`
- median net R: `-0.2124`
- positive-net-R rate: `45.93%`
- edge over opposite-direction control: `+0.1579R`
- edge over shifted-event control: `+0.0324R`
- Holm-adjusted p-value: `1.0`

It failed average and median expectancy, month consistency, tail-month,
shifted-control edge, and corrected-significance gates. This is not a near-miss.

## Frozen Design

Six outcome-blind context states represented three distinct mechanism axes:

1. acute cross-asset risk-on/risk-off shocks;
2. synchronized EUR-cross strength/weakness;
3. relative US/German bond-price shocks as a yield-differential proxy.

Each state had one predeclared direction and 4, 8, and 16 completed-M15-bar
horizons. Entry was the next M15 open. Risk was the larger of 8 pips or signal
ATR14, target was 1.5R, and fixed round-trip cost was 1.9 pips. Same-bar stop and
target touches were scored stop-first. Required controls were the opposite
direction at the same event and the same direction shifted 480 observed M15
bars. Holm-Bonferroni correction covered all 18 primary hypotheses.

## Interpretation

These broad context states do not have standalone entry edge under the frozen
execution model. This does not prove that cross-market context is useless as a
conditioner for an independently validated setup, but this result cannot be
reinterpreted as permission to filter, reverse, or retune the failed states.
Any future conditioner study must be a new predeclared experiment with its own
hypothesis budget.

The validation and holdout windows remain sealed because no development
survivor earned access.
