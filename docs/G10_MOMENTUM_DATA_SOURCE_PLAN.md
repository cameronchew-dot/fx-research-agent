# G10 Momentum Data Source Plan

## Locked requirement

Campaign 4 is a replication of monthly cross-sectional currency excess-return
momentum. A runnable panel needs, for all nine declared currencies and at least
192 common completed months:

1. normalized USD spot returns;
2. observed one-month forward points or observed historical financing returns;
3. historical bid/ask transaction costs; and
4. immutable source and arithmetic lineage.

Spot returns alone are not the predeclared hypothesis. Missing financing may
not be set to zero, inferred after looking at results, or replaced with current
OANDA financing metadata.

## Source feasibility

- BIS bilateral exchange rates are a strong public source for long monthly and
  daily USD spot histories, but they do not provide the required historical
  one-month forward series.
- IMF Exchange Rates provides official historical spot rates, not a complete
  G10 historical forward-point panel.
- OANDA can provide daily bid/ask candles for the declared instruments, but its
  current instrument financing metadata is not a historical monthly financing
  series.
- The published currency-momentum literature commonly relies on institutional
  forward-rate datasets. A trustworthy observed-forward source may therefore
  require a licensed vendor or a separately documented historical dataset.

## Acquisition sequence

1. Acquire and checksum the financing/forward dataset before downloading a
   large candle panel. Confirm all nine currencies and at least 192 common
   months are present.
2. Backfill OANDA daily bid/ask candles over exactly the same common window for
   implementable spot returns and cost estimates.
3. Normalize USD-base pairs into USD value per unit of foreign currency.
4. Build one immutable monthly payload per instrument under
   `config/g10_literature_panel_contract.json`.
5. Run `literature-panel-status`. Campaign evaluation remains blocked until it
   reports `READY`.

## Fallback decision

If an observed historical financing/forward source cannot be obtained, do not
weaken Campaign 4. A spot-momentum study would be a distinct hypothesis,
campaign ID, exact specification, and multiplicity slot. It must be
predeclared before its results are inspected.
