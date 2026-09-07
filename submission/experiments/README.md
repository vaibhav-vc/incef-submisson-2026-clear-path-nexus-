# EvidenceGate INSEF experiment

This experiment measures whether the EvidenceGate decision layer accepts complete, fresh and
integrity-valid evidence while failing closed when evidence is missing, stale, future-dated,
seeded, hard-blocked or altered after signing.

Run from the repository's `backend` directory:

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe ..\submission\experiments\run_evidencegate_experiment.py
```

The script writes the raw CSV and aggregate JSON beside itself. The signing key used by the
experiment is explicitly marked as non-production and exists only in the process memory.

The results are software validation data. They do not replace certified railway engineering
measurements, authenticated freight feeds, port-authority data or field trials.

To repeat the short public-provider observation check:

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe ..\submission\experiments\run_live_provider_observations.py
```
