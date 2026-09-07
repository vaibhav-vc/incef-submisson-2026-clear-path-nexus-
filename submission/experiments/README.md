# EvidenceGate INSEF experiment

This experiment measures whether the EvidenceGate decision layer accepts complete, fresh and
integrity-valid evidence while failing closed when evidence is missing, stale, future-dated,
seeded, hard-blocked or altered after signing.

Run from the repository's `backend` directory:

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe ..\submission\experiments\run_evidencegate_experiment.py
```

Each rerun writes its raw CSV and aggregate JSON into a new UTC-timestamped folder beneath
`submission/experiments/runs/`. The original CSV/JSON files beside these scripts are preserved.
The signing key used by the experiment is explicitly marked as non-production and exists only
in the process memory.

The results are software validation data. They do not replace certified railway engineering
measurements, authenticated freight feeds, port-authority data or field trials.

To repeat the short public-provider observation check:

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe ..\submission\experiments\run_live_provider_observations.py
```

Both scripts accept `--output-dir` to choose a folder, relative to your current working directory:

```powershell
.venv\Scripts\python.exe ..\submission\experiments\run_evidencegate_experiment.py --output-dir ..\submission\experiments\runs\my-validation-run
```

Existing result filenames cause an error before any trial or provider request starts. Files are
also created exclusively to prevent accidental overwrite during concurrent runs. An interrupted
run may leave a partial folder; keep it as evidence of interruption and use a new folder to retry.
Do not copy rerun outputs over the original data or silently substitute them into the original
report. Timing and provider availability measurements are specific to each execution.
Each script exits with code `0` only when every expected check passes, or `1` when any
measurement fails; either way, completed measurements are preserved in the new folder.

The public-provider check validates numeric values (not just field presence) and timestamps.
It rejects null, boolean, non-finite and malformed observations. Passing this short check does not
prove long-term uptime, operational readiness, or freshness at the time of a later dispatch.
