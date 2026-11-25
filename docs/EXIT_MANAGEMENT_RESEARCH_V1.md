# Exit Management Research V1

This read-only diagnostic replays four frozen exit policies over the same
independent EUR/USD signals, entries, initial stops, spreads, and 16-bar M15
paths. It first reproduces the stored `+1.5R/-1R` control within `0.02R`; rows
that fail reproduction are excluded rather than silently compared.

The alternatives are full-position break-even after a `+1R` touch, 50% partial
profit at `+1R` with a `+2R` runner, and the same partial with a break-even
runner. Management changes become active on the next candle. A candle touching
both an adverse exit and a favorable management threshold uses stop-first
ordering. Partial exits pay a conservative additional fill-cost proxy.

Original failed-auction outcomes and strategy-shadow outcomes remain separate.
All six alternative-versus-control comparisons share one Benjamini-Hochberg
false-discovery family. Historical findings are post-hoc and cannot alter paper
or live execution. A favorable result must be frozen into a new forward
campaign before any policy discussion.

```bash
python3 ops/research_supervisor.py exit-management-research
```
