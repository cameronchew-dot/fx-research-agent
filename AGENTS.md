# FX Research Agent Workspace

This repository is the canonical system of record for forward FX research.

- Never store or read OANDA credentials, account IDs, balances, positions, or order data.
- Never submit, modify, or close orders.
- Accept market data only through validated, immutable, market-only exports.
- Treat OANDA tick imbalance and quote pressure as venue-specific proxies, not centralized FX volume or true CVD.
- Keep hypotheses, experiment specifications, runs, controls, and findings append-only.
- A research finding cannot activate shadow, paper, promo, or live behavior.
- Downstream adoption requires a sealed export and explicit human review in the receiving repository.
- Preserve hypothesis IDs, timestamps, source provenance, and payload hashes during imports.
- Reject conflicting rewrites of immutable IDs.
- Use explicit Git staging. Do not use `git add .`.

