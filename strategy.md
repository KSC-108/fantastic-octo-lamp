# Strategy: none validated yet

No strategy has passed the acceptance gates on real NSE data. This file is rewritten by
`octoquant research` with the exact entry, exit, stop, take-profit, timeframe and invalidation
rules of the winning parameter set, together with the gate results and caveats.

Run from a host that can reach NSE:

```
pip install -e ".[nse]"
octoquant --config config/nse.yaml research
```

Paper trading refuses to run until a strategy is accepted.
