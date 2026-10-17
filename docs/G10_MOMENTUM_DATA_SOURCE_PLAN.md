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
- The Journal of Financial Economics archive lists the authors' workbook
  `Menkoff_Sarno_Schmeling_Schrimpf.xlsx`, but the migrated archive page does
  not currently expose a working file URL. The authors describe the package as
  replication data that includes portfolio benchmarks and Datastream mnemonics.
  Until the workbook is recovered and inspected, it is `BENCHMARK_ONLY`, not
  evidence that raw nine-instrument forward quotes are available.
- The paper states that its end-of-month spot and one-month forward rates came
  from Barclays Bank International and Reuters via Datastream. This verifies a
  suitable data *type*, not present access, exact common-month coverage, or an
  acquired immutable artifact.

Run the committed source audit at any time:

```bash
python3 ops/research_supervisor.py financing-source-status
```

The audit is intentionally stricter than source discovery. Only an acquired,
checksummed complete panel with raw currency-level rows, all nine instruments,
at least 192 common months, an allowed observed financing source, historical
bid/ask costs, and immutable lineage can report `READY`. The catalog records
why each discovered source does or does not qualify.

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

The official BIS spot archive can be downloaded and reduced without extracting
its full CSV:

```bash
python3 ops/bis_xru_extract.py data/external/bis/WS_XRU_csv_flat.zip \
  --output data/external/bis/g10_monthly_spot.csv.gz \
  --summary data/external/bis/g10_monthly_spot_summary.json
```

This output is deliberately labeled `SPOT_ONLY_NOT_EXCESS_RETURN` and cannot be
registered as a complete Campaign 4 panel.

## Fallback decision

If an observed historical financing/forward source cannot be obtained, do not
weaken Campaign 4. A spot-momentum study would be a distinct hypothesis,
campaign ID, exact specification, and multiplicity slot. It must be
predeclared before its results are inspected.

Campaign 5 carry remains deliberately unpredeclared while this audit is
blocked. Carry depends on the same historical financing/forward leg, so writing
its exact specification before that input is supportable would create a sealed
campaign that cannot run.
