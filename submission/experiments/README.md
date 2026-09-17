# Evidence assurance experiments

The primary Phase 4/5 study is now a paired randomized benchmark backed by an
immutable snapshot of real public publisher bytes. It supersedes the original
`run_evidencegate_experiment.py` result as the current experiment design. The
original eight-scenario experiment and its outputs remain in the repository as
historical evidence; they must not be presented as 1,600 independent railway
cases because they repeat eight fixtures 200 times each.

## 1. Capture real publisher data

From `backend/`:

```powershell
.venv\Scripts\python.exe ..\submission\experiments\record_official_sncf_snapshot.py
```

The recorder downloads the official SNCF static GTFS schedule, GTFS-Realtime
Trip Updates and GTFS-Realtime Service Alerts linked by France's National
Access Point. It writes the byte-for-byte responses and a manifest containing:

- requested and final URLs;
- UTC retrieval times and selected HTTP headers;
- byte lengths and SHA-256 digests;
- GTFS ZIP CRC validation, required-member validation and row counts;
- publisher, catalogue, ODbL licence and special-conditions links; and
- explicit limitations and evidence classification.

Every run receives a new UTC-stamped directory. Files are opened in exclusive
creation mode and the recorder rejects unexpectedly large or empty responses.
The GTFS-RT protobuf files are preserved but not semantically decoded by this
dependency-free recorder; the manifest says so explicitly.

See [`docs/data/SNCF_ODBL_NOTICE.md`](../../docs/data/SNCF_ODBL_NOTICE.md) before
redistributing a snapshot.

## 2. Run the randomized paired benchmark

Use the manifest path printed by step 1:

```powershell
$env:PYTHONPATH='.'
.venv\Scripts\python.exe ..\submission\experiments\run_evidence_assurance_benchmark.py `
  --cases 2400 `
  --source-manifest ..\submission\experiments\runs\<snapshot-run>\source_manifest.json
```

The benchmark verifies the source manifest and every referenced raw-file digest
before starting. It then generates 2,400 unique evidence bundles with the fixed
seed `20260915`. Clean fixtures have randomized values and identities; invalid
fixtures receive one randomly selected, explicitly labelled
`CONTROLLED_TEST_MUTATION`. These mutations are software test cases—not real
failures, incidents, accidents or trains.

Each case is evaluated by the same three classifiers:

1. `B0 latest-value`: explicit approval and a non-empty value for every role.
2. `B1 checksum/timestamp`: B0 plus value digests, completeness, availability,
   and coarse temporal checks; it intentionally omits authority, lineage and
   role-specific semantics.
3. `EvidenceGate V2`: the full fail-closed policy implemented by the backend.

Outputs include all case-level decisions and timings, confusion matrices,
false-admission and false-hold rates with Wilson 95% intervals, balanced
accuracy, Matthews correlation coefficient, p50/p95/p99 latency, per-fault
results and exact paired McNemar comparisons. A run manifest digests the raw CSV
and summary. The script exits non-zero if EvidenceGate has any false admission
or false hold under the generated ground-truth labels.

The deterministic seed makes case generation reproducible; local timing is not
expected to be bit-for-bit reproducible. Use `--seed` for a declared replication
run and `--output-dir` for a specific new destination. Existing result files are
never overwritten.

## Checked-in run status

The source snapshot
`20260916T064806641708Z_sncf_snapshot_2dc07b37` was captured with the rebuilt
recorder and reverified against every recorded byte length and SHA-256 digest;
its GTFS ZIP also passes CRC, safe-member, required-table and row-count
validation. All recorded UTC fields contain an explicit `+00:00` offset.

`20260916T064855068103Z_evidence_assurance_1431e7d7` is the current checked-in
2,400-case run. It contains 481 clean fixtures and 1,919 controlled mutations;
the full gate produced `TP=481`, `TN=1,919`, `FP=0`, and `FN=0` under those
controlled fixture labels, with 2,400 unique case fingerprints and no policy
exceptions. The run manifest seals the CSV, summary and source-snapshot digest.

These are software-policy results only. Even the passing run does not establish
field safety, real-world incident detection, or suitability for operational
railway control.

## Interpretation boundary

The attached SNCF snapshot proves which real external bytes were observed. It
does **not** make the randomized route bundles real and does not validate Indian
Railways deployment, collision prevention, signalling, movement authority,
driver-speed advice, certified engineering limits or replacement of an
operational railway system. Those claims require authorised Indian railway
interfaces, safety engineering, regulator/operator participation and field
validation.

`run_live_provider_observations.py` remains a short public-provider availability
check. Like the assurance benchmark, it is not a long-term uptime or safety
test. Its output and all historical experiment results must retain their own
timestamps and checksums rather than being silently copied over by a later run.
