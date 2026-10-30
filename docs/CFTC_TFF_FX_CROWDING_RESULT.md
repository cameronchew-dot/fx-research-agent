# CFTC TFF FX Crowding Reversal V1 Result

Status: `NO_DEVELOPMENT_SURVIVORS`

The exact three-pair specification was evaluated only on CFTC report dates
through 2016. Validation (2017-2021) and holdout (2022 onward) were not
inspected.

| Instrument | Independent N | Average net R | Positive rate | Edge vs opposite | Edge vs shifted | Result |
|---|---:|---:|---:|---:|---:|---|
| EUR/USD | 12 | +0.048 | 41.7% | +0.389 | -0.205 | Rejected |
| USD/JPY | 14 | +0.403 | 57.1% | +0.587 | +0.354 | Rejected |
| AUD/USD | 5 | -0.510 | 20.0% | -1.233 | -0.261 | Rejected |

USD/JPY was directionally interesting, but it had fewer than half of the 30
required independent events, failed the worst-year gate, and did not clear the
familywise significance gate. That is a research lead, not validated edge.
The locked stopping rule forbids retuning this exact specification or opening
its sealed partitions in response.

EUR/USD was near flat, had a negative median, and underperformed the shifted
control. AUD/USD was clearly negative and its opposite-direction control was
positive. No result can enter a downstream bot or agent.

Artifacts:

- `data/results/cftc_tff_fx_crowding_reversal_development.json`
- `data/results/cftc_tff_fx_crowding_reversal_development.events.json.gz`

The official source extract is reproducible but remains untracked under
`data/external/cftc/`.
