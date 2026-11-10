# SPY Morning Momentum Last-Half-Hour V1

This predeclared campaign tests one published-mechanism lead using an execution
window that is practical for the paper-only Alpaca sleeve.

## Locked rule

- Compute SPY's return from the previous complete regular-session close through
  the current session's 09:59 minute close.
- If that return is strictly positive, buy at the 15:30 minute open.
- Exit at the 15:55 minute open.
- Otherwise remain in cash.

The five-minute buffer before the regular close avoids assuming a perfect
closing-auction fill. It is intentionally less favorable than measuring through
the official close.

## Data and costs

The source is distribution-adjusted one-minute historical SIP data from Alpaca.
The primary model charges 2 basis points each way; stress charges 5 basis points
each way. Early closes and sessions missing any required timestamp are excluded.

## Controls and review

The fixed controls are always long during the execution window, long after a
non-positive morning, and the prior session's positive-morning signal. Calendar
partitions, sample gates, risk gates, and a paired Newey-West comparison are
frozen in the campaign JSON. There is no threshold, entry-time, exit-time, or
context-filter sweep.

Historical success would justify a new paper-forward target only. This research
repository cannot place orders and the campaign cannot activate the Alpaca
executor automatically.
