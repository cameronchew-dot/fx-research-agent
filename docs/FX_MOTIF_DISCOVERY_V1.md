# FX Motif Discovery V1

## Purpose

This lane adds raw, unlabeled EUR/USD market-state discovery without granting
research findings any trading authority. It combines the BTC bot's useful
machine-discovery pattern with the FX system's stricter point-in-time, control,
holdout, and multiple-comparisons discipline.

## Locked foundation

- Instrument: EUR/USD
- Base timeframe: completed M15 candles
- As-of context: completed H1, H4, and daily candles only
- Development: 2018-09-19 through 2022-12-31
- Sealed validation: 2023-01-01 through 2024-12-31
- Untouched holdout: 2025-01-01 onward
- Features: 25 price, volatility, participation, objective-location,
  higher-timeframe, and calendar features
- Clusters: 24 deterministic machine IDs
- Planned later comparisons: 24 clusters x 2 directions x 3 horizons = 144
- Required later correction: Holm-Bonferroni across the declared comparison set

Strategy labels and future outcomes are forbidden from the feature matrix.
Changing any contract field produces a different contract hash and cannot
silently rewrite the existing artifact.

## First descriptive run

The sanitized source package contains 307,162 completed market candles:
200,000 M15, 80,000 H1, 20,000 H4, and 7,162 daily rows. The resulting matrix
contains 199,762 timestamp-valid rows:

- 106,264 development rows across 1,334 distinct days
- 49,818 sealed validation rows
- 43,680 sealed holdout rows

The discovery runner trained on at most 100,000 development rows and produced
24 stable machine cluster IDs. It inspected zero validation rows, zero holdout
rows, and zero future outcomes. Consequently, this run makes no profitability
claim and identifies no paper candidate.

## Next gate

Before examining outcomes, a human must review the descriptive clusters and
predeclare a bounded candidate-selection rule. Only that frozen subset may be
evaluated on development outcomes and controls. Validation and holdout access
remain separate later gates. Downstream adoption would still require a sealed
export and the EUR bot's independent lifecycle checks.
