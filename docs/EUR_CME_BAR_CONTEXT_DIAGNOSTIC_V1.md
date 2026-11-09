# EUR/USD CME Bar Context Diagnostic V1

This predeclared diagnostic asks whether causally available CME Euro FX futures
bar and participation context improves discrimination of the EUR/USD agent's
failed-auction episodes.

## Available information

The purchased Databento package contains roll-safe 1-minute OHLCV, official
statistics, and definitions. It does not contain tick trades, aggressor side,
BBO, or order-book depth. This diagnostic therefore makes no claim to true CVD,
spread, quote pressure, or order-book imbalance.

## Independence and timing

- The first candidate in each episode is retained.
- A new independent episode cannot begin until the prior 16-bar M15 outcome
  window has ended.
- Every futures feature uses a complete 15-minute bar whose end timestamp equals
  the EUR/USD decision timestamp.
- Intraday range, volume, and volatility baselines use only the prior 20 bars in
  the same New York 15-minute clock slot.

## Frozen comparison

Three L2-logistic models use identical expanding one-step-ahead training:

1. Spot context only.
2. Spot context plus current causal CME context.
3. Spot context plus CME context lagged exactly 24 hours.

The first 30 independent episodes initialize each model. Every subsequent
episode is predicted from strictly earlier episodes. The final 20% of predictions
is also reported as a small dated tail. No model penalty, feature, threshold, or
partition may be changed after inspecting results.

This is retrospective diagnostic evidence because the episode outcomes existed
before the campaign was frozen. A pass cannot activate agent, paper, or live
behavior; it would justify a new forward-only confirmation epoch.
