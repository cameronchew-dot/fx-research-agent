# Cross-Asset Short-Term Reversal V1

## Status

`PREDECLARED_RESEARCH_ONLY`

This campaign asks one fixed question before inspecting its Alpaca result: does
the worst volatility-normalized five-session move among seven liquid ETFs
rebound over the next three sessions strongly enough to clear costs and BIL?

## Mechanism

Short-horizon reversal is commonly interpreted as compensation for supplying
liquidity after temporary selling pressure. That is a mechanism lead, not an
edge claim. Published evidence also warns that bid-ask effects and trading costs
can consume apparent reversal profits, so this test uses practical next-open
execution and two locked cost scenarios.

At each completed common daily close:

1. Compute each risky ETF's five-session close return.
2. Divide it by the standard deviation of the 20 daily returns ending one
   session before the decision, multiplied by the square root of five.
3. Select the minimum z-score.
4. Trade only when that z-score is at most `-1.5`.
5. Enter at the next common session open and exit at the third session close.
6. Do not overlap positions.

The risky universe is `SPY`, `EFA`, `IEF`, `TLT`, `GLD`, `DBC`, and `UUP`.
`BIL` is the cash hurdle. The frozen controls select the recent winner, a
deterministic random risky ETF, and SPY on exactly the same dates.

## Guardrails

- Historical Alpaca SIP bars use split-and-dividend adjustment `all`.
- Primary costs are 5 basis points per side; stress costs are 10 per side.
- BIL is an uncharged same-interval cash hurdle; traded controls pay costs.
- Development is 2016-2021, validation is 2022-2024, and dated confirmation is
  2025 through November 6, 2026.
- There is one threshold and one holding period. No sweeps or subgroup rescue
  are allowed after the result.
- Passing is only a human-review lead. This repository cannot activate paper or
  submit an order.

The mechanism references Bruce Lehmann's 1990 weekly-reversal evidence and
Stefan Nagel's 2012 interpretation of short-term reversal returns as liquidity
provision. Neither paper validates this ETF implementation.
