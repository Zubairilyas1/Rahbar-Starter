# Trace samples (Assignment 03 D/F4)

`cluster/` holds the trace files copied from the `rahbar-traces` volume: one JSON-lines
file per API pod. Copy them with `kubectl cp rahbar/<toolbox-pod>:/traces traces/cluster`.
The same records also go to the pods' stdout (`kubectl logs deploy/api -n rahbar`).

Tools: `inspect.py` (D2: exact context and prompt for a trace id), `metrics_summary.py`
(D3: metrics over a time window), `diagnose.py` (D5: root cause from one trace),
`trace_io.py` (shared loader for files, directories or saved `kubectl logs` output).
