# EUR/USD London ORB HMM Direction Selector V1

## Purpose

This campaign tests one narrow forward-only question: when the existing London
ORB failed-break mechanism emits paired continuation and reversal routes, does
the route aligned with the timestamp-valid causal HMM direction outperform the
opposed route?

The historical causal replay supplied an exploratory lead. It did not supply
confirmation. Small absolute-state slices looked favorable for continuation in
an up/expanding/high-volatility state and reversal in a down/expanding/high-
volatility state. Those suffixes were observed after outcomes and are therefore
not part of the locked forward rule.

At the campaign freeze, the broader historical direction-alignment diagnostic
did not reproduce that suffix-specific lead. Pooling the two routes produced 12
aligned observations averaging approximately `+0.071R` and 12 opposed
observations averaging `+0.250R`, for an aligned-minus-opposed lift of about
`-0.179R`. The underlying per-route slices were small and no tested context
slice survived false-discovery correction. This lowers the prior probability
of the campaign succeeding; it does not alter the already-frozen forward rule.

## Frozen rule

- Population: new `LONDON_ORB_REVERSAL_CONFIRMATION` strategy-shadow events.
- Routes: the existing reversal and breakout-control setup IDs.
- Treatment: route direction agrees with a causal HMM `UP` or `DOWN` state.
- Comparator: route direction opposes that state.
- Excluded: flat, missing, unavailable, or non-causal HMM states.
- Entry, costs, 16-bar horizon, and conservative same-bar tie handling remain
  identical to the existing London ORB paired contract.
- Volatility, transition, Markov, and GARCH subsets remain descriptive only.

## Evidence boundary

Only events whose decision time is strictly after campaign approval can count.
Historical regime replay rows remain exploratory and cannot be imported as
forward observations. Fixed-horizon overlap is removed independently in each
cohort.

The first review requires 20 resolved independent aligned events and 20 opposed
events. The aligned cohort must have positive average net R, positive average-R
lift over the opposed cohort, at least a 50% positive-net-R rate, and positive
average net R in both chronological halves. Reaching a gate triggers review; it
does not authorize trading or promotion.

## Authority

This is research only. The campaign cannot place orders, alter paper policy,
activate a downstream selector, or weaken any lifecycle or risk gate.
