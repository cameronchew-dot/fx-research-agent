# G10 Daily Time-Series Momentum Spot Diagnostic

`CAMPAIGN_G10_DAILY_TIME_SERIES_MOMENTUM_SPOT_DIAGNOSTIC_V1` tests one
predeclared medium-horizon portfolio, not a parameter search. It covers seven
liquid USD majors and uses a majority vote across 21-, 63-, and 126-common-day
log spot returns. Targets are formed from the final common BIS daily average in
each ISO week and become effective on the next common observation.
Provider rows encoded as non-finite values are excluded before the complete
seven-instrument common-date panel is formed, and the exclusion count is
recorded in the extraction summary.

Pair weights are inverse-volatility sized using the prior 20 common daily
returns. Absolute pair weight is capped at 25%, gross exposure at 100%, and the
absolute common USD-factor exposure at 50%. The primary five-basis-point
one-way turnover cost is repeated at ten basis points as a locked stress test.

The four controls are opposite direction, one-week stale targets, fixed-hash
random directions, and a single common USD-factor trend. The first 60% of
weekly observations are development, the next 20% chronological OOS, and the
final 20% dated confirmation. The specification cannot change after results
are inspected.

## Interpretation boundary

BIS daily observations are daily averages, not executable bid/ask quotes. The
historical panel also lacks observed financing or forward points. Results are
therefore a spot-predictability diagnostic only. Even if every spot gate passes,
the campaign remains `NOT_PROMOTABLE_WITHOUT_FINANCING`; it cannot create a
trading signal, enter a downstream lifecycle, or obtain order authority.

## Reproduction

```bash
python3 ops/bis_xru_daily_extract.py data/external/bis/WS_XRU_csv_flat.zip \
  --output data/external/bis/g10_daily_spot.csv.gz \
  --summary data/external/bis/g10_daily_spot_summary.json

python3 ops/g10_time_series_momentum_research.py \
  --output data/results/g10_time_series_momentum_spot_primary.json

python3 ops/g10_time_series_momentum_research.py --cost-bps 10 \
  --output data/results/g10_time_series_momentum_spot_stress.json
```

The locked run is complete and rejected. See
`G10_TIME_SERIES_MOMENTUM_RESULT.md`; do not alter this specification or reuse
its dated confirmation window for a revised version.
