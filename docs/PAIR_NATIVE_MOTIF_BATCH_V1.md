# Pair-Native Motif Batch V1

## Scope

This batch tested fresh, pair-native price/volume/session states for AUD/USD,
USD/JPY, and GBP/USD. It did not port EUR/USD approvals. The research agent
used sealed market-only M15/H1/H4/D histories and had no broker credentials,
account state, order state, or execution authority.

## Frozen method

- Development: 2010-2018.
- Sealed validation: 2019-2022.
- Sealed holdout: 2023 onward.
- Discovery: deterministic 24-cluster k-means per pair, using only features
  knowable at the completed M15 candle close.
- Selection: three motifs per pair chosen from centroid descriptions before
  outcomes were inspected.
- Geometry: next M15 open, signal-extreme-or-0.75-ATR stop, 1.5R target, and
  4/8/16-bar horizons.
- Costs: fixed 2.0 pips round trip, with instrument-correct pip sizing.
- Controls: opposite direction and a 480-observed-M15-bar timestamp shift.
- Independence: first cluster entry, then skip 16 completed M15 bars.
- Error control: one third of the 5% batch alpha per pair, followed by
  Holm-Bonferroni across that pair's nine primary hypotheses.

## Result

| Pair | Hypotheses | Best frozen hypothesis | Events | Best avg net R | Median net R | Positive rate | Survivors |
|---|---:|---|---:|---:|---:|---:|---:|
| AUD/USD | 9 | downside impulse, short, 4 bars | 1,208 | -0.068 | -0.073 | 45.1% | 0 |
| USD/JPY | 9 | downside impulse, short, 4 bars | 975 | -0.113 | -0.138 | 40.6% | 0 |
| GBP/USD | 9 | upside impulse, long, 4 bars | 1,570 | -0.081 | -0.126 | 42.5% | 0 |

All pair results are `NO_DEVELOPMENT_SURVIVORS`. The failures are not caused
by inadequate sample size. Validation and holdout remained unopened, and the
batch must not be retuned in response to these results.

## Operational additions

The EUR bot now exports sanitized AUD/USD, USD/JPY, and GBP/USD candles,
spreads, and bid/ask snapshots every five minutes. The research agent ingests
them through immutable manifests. A portfolio report separately measures raw
candidate cadence and overlap without confusing either with validated edge.

The CME 6E/6J/6A context contract is present but inert. No centralized futures
feed is configured, so true CVD and futures order-flow context are unavailable.

## Disposition

Archive this batch without retuning. Fresh future research must begin from a
new economic mechanism and a new predeclaration, not from a geometry search on
these rejected motifs. No downstream lifecycle or trading permissions changed.
