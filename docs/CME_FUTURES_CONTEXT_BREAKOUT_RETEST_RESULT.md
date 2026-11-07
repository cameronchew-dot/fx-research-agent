# CME Futures Context Breakout/Retest V1 Result

Status: `NO_DEVELOPMENT_SURVIVORS`

The campaign specification was registered and explicitly approved before any
returns were calculated. It used completed spot M15 candles from September
20, 2018 through December 31, 2022 and causally constructed CME 6E, 6J, and 6A
context. The 2023-2024 validation partition and the 2025+ dated-confirmation
partition were not inspected.

The fixed spot population was the first non-overlapping prior-day accepted
breakout/retest per level direction and New York 17:00 trading day. Entry was
the next M15 open; stops included a four-pip minimum risk, targets were 1.5R,
the maximum horizon was 16 M15 bars, same-bar ties were stop-first, and fixed
round-trip costs were 1.5 pips for EUR/USD, 1.8 for USD/JPY, and 2.0 for
AUD/USD.

| Population/filter | Independent N | Average net R | Median net R | Positive rate | Edge vs unfiltered | Holm p | Result |
|---|---:|---:|---:|---:|---:|---:|---|
| Unfiltered spot setup | 2,328 | -0.371 | -1.161 | 38.1% | - | - | Negative baseline |
| Aligned 15m futures return + volume ratio >= 1.25 | 700 | -0.295 | -1.106 | 38.3% | +0.076 | 0.121 | Rejected |
| Rising OI + aligned settlement change | 838 | -0.415 | -1.175 | 36.9% | -0.044 | 0.861 | Rejected |
| Full confluence | 267 | -0.342 | -1.117 | 37.8% | +0.029 | 0.669 | Rejected |

High-volume directional alignment improved the negative baseline and beat its
opposite-context control by `+0.112R`, but it did not produce positive absolute
expectancy, a positive median, sufficient month stability, or familywise
significance. That is useful context evidence, not a tradeable signal.

The OI/settlement filter and full confluence were also negative. Pair-level
breakdowns were descriptive only and were negative for all three pairs. No
filter received validation access, downstream export, paper authority, or live
authority. The exact campaign is parked; its stopping rule prohibits tuning a
second threshold after seeing this result.

Artifacts:

- `config/campaigns/multipair_cme_futures_context_breakout_retest_v1.json`
- `data/results/multipair_cme_futures_context_breakout_retest_development.json`
- `data/results/multipair_cme_futures_context_breakout_retest_development.events.json.gz`
