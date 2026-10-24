# FX Motif Development Result V1

## Decision

`EUR_USD_MOTIF_CONFIRMATION_V1` produced no development survivor. The result
is archived without retuning, validation access, campaign creation, or any
paper/live authority.

## Locked evaluation

- Development only: 2018-09-19 through 2022-12-31
- Five outcome-blind motifs
- One predeclared direction per motif
- Horizons: 4, 8, and 16 completed M15 bars
- Entry: next M15 open
- Stop: signal extreme or 0.75 ATR, whichever is farther
- Target: 1.5R
- Fixed round-trip friction: 1.9 pips
- Controls: opposite direction and a 480-observed-bar timestamp shift
- Significance: 20,000-draw one-sided paired sign-flip test
- Multiple comparisons: Holm-Bonferroni over 15 primaries

## Results

| Motif | Direction | Events | Best horizon | Best average net R | Positive events | Positive months |
|---|---:|---:|---:|---:|---:|---:|
| High-participation downside impulse | Short | 785 | 8 | -0.097R | 43.7% | 36.5% |
| High-participation upside impulse | Long | 736 | 8 | -0.106R | 43.5% | 32.7% |
| Multi-timeframe downside continuation | Short | 547 | 8 | -0.161R | 43.5% | 30.8% |
| High-volatility upper-wick rejection | Short | 1,508 | 4 | -0.330R | 37.7% | 3.8% |
| High-volatility lower-wick rejection | Long | 1,491 | 16 | -0.351R | 37.8% | 9.6% |

Every horizon for every motif had negative average and median net R. All Holm-
adjusted p-values were 1.0 under the locked stronger-control comparison. The
impulse motifs sometimes beat their controls on average, but they remained
absolutely loss-making and therefore failed the objective profitability gates.

## Audit record

- Evaluation run: `MOTIF_DEVELOPMENT_EVALUATION_4fdf8cbe1642a3bfd585`
- Event-ledger rows: 15,201
- Event-ledger SHA-256:
  `98ec68e4d3cfd6799090be5acf05f826ccdd1d2a7e5bd53cc15b1530b76648b8`
- Validation rows inspected: 0
- Holdout rows inspected: 0
- Development survivors: 0

An identical rerun reproduced both the run ID and event-ledger checksum.
