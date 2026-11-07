# CME Futures Participation Shock V1 Result

Status: `NO_DEVELOPMENT_SURVIVORS`

The two-mechanism campaign was registered and explicitly approved before any
returns were calculated. It used development decisions from September 20,
2018 through December 31, 2022. The 2023-2024 validation partition and 2025+
dated-confirmation partition were not inspected.

Every event required a completed CME 6E, normalized 6J, or 6A 15-minute bar
with volume at least `1.75x` and true range at least `1.5x` the median for the
same New York local quarter-hour over the prior 20 available observations.
Only the first event per mechanism, direction, and CME session was admitted,
and primary holding horizons could not overlap.

| Mechanism | Independent N | Average net R | Median net R | Positive rate | Edge vs opposite | Edge vs delayed | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Acceptance continuation | 4,573 | -0.324 | -1.187 | 38.5% | -0.036 | +0.005 | Rejected |
| Failed-auction reversal | 2,477 | -0.295 | -1.149 | 39.0% | -0.013 | -0.012 | Rejected |

All EUR/USD, USD/JPY, and AUD/USD descriptive pair breakdowns were negative.
Neither mechanism beat both paired controls, and both Holm-adjusted p-values
were `1.0`. The failure is therefore not explained merely by transaction
costs: the fixed direction rules did not discriminate better than the controls.

No mechanism received validation access, downstream export, paper authority,
or live authority. The campaign is parked, and the exact stopping rule forbids
changing its thresholds or geometry after seeing this result.

Artifacts:

- `config/campaigns/multipair_cme_participation_shock_v1.json`
- `data/results/multipair_cme_participation_shock_development.json`
- `data/results/multipair_cme_participation_shock_development.events.json.gz`
