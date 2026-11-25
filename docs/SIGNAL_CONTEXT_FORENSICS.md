# Signal Context Forensics

`signal-context-forensics` is a read-only daily diagnostic over both immutable
original failed-auction candidates and strategy-shadow events with resolved
outcomes. The two populations and their outcome sources remain separate. It
keeps each exact signal geometry separate, removes overlapping fixed-horizon
observations, and compares timestamp-valid context slices within each signal.

The report currently examines session, direction, HTF alignment, spread/ATR,
signal-candle geometry, and available Markov, HMM, and GARCH labels. Missing
regime labels may be supplied by the separate causal historical enrichment
artifact. That replay uses only candles completed by each decision timestamp,
records the frozen model and candle-source hashes, and never edits the original
event. Reconstructed labels remain exploratory historical evidence rather than
forward confirmation.

All eligible categorical comparisons share one Benjamini-Hochberg false-
discovery correction. Results remain descriptive even when their corrected
q-value is small. A post-hoc lead must become a new locked forward campaign
before it can count as confirmation.

```bash
python3 ops/research_supervisor.py signal-regime-enrichment
python3 ops/research_supervisor.py signal-context-forensics
```

The command cannot create or approve campaigns, alter lifecycle or execution
state, submit orders, or change strategy parameters.
