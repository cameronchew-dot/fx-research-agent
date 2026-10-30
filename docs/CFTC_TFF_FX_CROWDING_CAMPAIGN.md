# CFTC TFF FX Crowding Reversal V1

This is one frozen, development-only test of a weekly positioning mechanism on
EUR/USD, USD/JPY, and AUD/USD. It is not a broad parameter search.

The source is the official CFTC Traders in Financial Futures, Futures Only
dataset. The signal is the leveraged-money net position divided by open
interest, standardized against the prior 156 reports with the current report
excluded. An instrument becomes eligible only on the first report in a newly
armed `|z| >= 1.5` episode. It rearms only after `|z| < 1.0`.

The strategy fades foreign-currency crowding. A crowded long EUR or AUD is a
short EUR/USD or AUD/USD signal. A crowded long JPY is a long USD/JPY signal.
The fixed availability time is eight calendar days after the Tuesday report,
followed by the next daily open. This deliberately sacrifices timeliness to
avoid publication look-ahead, including ordinary Friday publication and
historical holiday uncertainty.

Geometry is fixed before outcomes are inspected: prior-only daily ATR(20), a
2 ATR stop, a 3 ATR target, a 20-daily-bar horizon, conservative stop-first
ties, conservative gap handling, and 2 pips round-trip cost. Controls are the
opposite direction at the same event and the same direction 26 weeks later.
Primary holding windows cannot overlap.

Only reports dated through 2016 are available to development. Reports from
2017-2021 are sealed validation and 2022 onward is sealed holdout. A
development survivor does not open either partition automatically. The three
instrument hypotheses share one Holm-Bonferroni family at alpha 0.05.

This campaign has no shadow, paper, live, account, or order authority. Failure
closes this exact specification without retuning.
