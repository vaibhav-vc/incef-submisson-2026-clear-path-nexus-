# ISEF 2027 research protocol — internal engineering guidance

**Status:** AI-assisted planning record, not a student-authored research plan,
abstract, poster, notebook or bibliography. The student team must understand the
work, make and record its own research decisions, write its own submission, and
disclose assistance accurately. Do not backdate approvals or signatures.

Checked 19 September 2026 against the Society for Science [2027 International
Rules](https://www.societyforscience.org/isef/international-rules/) and [Grand
Award judging criteria](https://www.societyforscience.org/isef/grand-award/criteria/).
Qualification starts through an affiliated fair; INSEF and ISEF are not assumed
to be the same competition or an automatic qualification route.

## Defensible project claim

**Engineering problem:** decision-support software can accept recommendations
whose underlying records are current-looking but unauthorized, incomplete,
wrong-scope, contradictory, tampered or disconnected from their dependencies.

**Engineering goal:** construct a non-vital evidence-admissibility gate that binds
a recommendation to source authority, subject/context, time, required roles,
lineage, integrity and independent review, and measure whether it reduces false
admission relative to predeclared simpler validators.

**Primary hypothesis:** on a frozen held-out challenge set, EvidenceGate will have
a lower false-admission rate than each baseline under paired exact McNemar tests,
with Holm correction, while its false-hold rate on clean cases remains below 5%.

**Explicit non-claim:** this study does not test railway physics, real collision
prevention, safe driver speeds, signalling, movement authority, Indian Railways
replacement, or field safety. SNCF bytes prove source capture only. Controlled
mutations are not real trains, incidents or failures.

## Frozen experiment protocol

1. Before the confirmatory run, the students and sponsor record the research
   question, primary endpoint, thresholds, baseline definitions, sample size,
   exclusion rules and analysis method in the dated notebook/research plan.
2. Freeze one source manifest and one code commit. Verify every source byte and
   record its publisher, URL, retrieval time, licence, length and SHA-256.
3. A reviewer who did not implement the gate authors an unsealed fault-plan JSON.
   The `author_role` and `declared_independence` fields are declarations, not
   cryptographic identity proof; the notebook must identify the actual person.
4. Seal that plan with `seal_fault_plan.py`. Neither the sealer nor the benchmark
   may overwrite an existing plan or result directory. Preserve the draft, sealed
   plan, digest and time in the research record.
5. Run every case through the same six classifiers: latest-value, checksum/time,
   source-agnostic role quorum, conservative completeness, legacy numerical score,
   and EvidenceGate. The classifiers receive the evidence bundle, not its label.
6. Publish raw case rows, case fingerprints, classifier outputs, latencies,
   confusion matrices, Wilson intervals, paired tests, corrected p-values,
   per-fault results, source digests, fault-plan digests and all failures.
7. Replicate with at least three separately sealed plans. Treat cases within one
   generated plan as controlled software trials—not independent railway events.
   Report each replication separately before any pooled descriptive summary.
8. Do not change code, policies, thresholds or exclusions after viewing the
   confirmatory results. Any repair creates a new version and new held-out plan.

Draft plan shape:

```json
{
  "schema_version": "clearpath.fault-plan.v1",
  "protocol_id": "team-defined-held-out-01",
  "author_role": "named role recorded separately in the notebook",
  "declared_independence": false,
  "faults": ["none", "wrong_context", "lineage_cycle"]
}
```

From `backend/`:

```powershell
.venv\Scripts\python.exe ..\submission\experiments\seal_fault_plan.py `
  <draft.json> <new-sealed-plan.json>

.venv\Scripts\python.exe ..\submission\experiments\run_evidence_assurance_benchmark.py `
  --seed <declared-fixture-seed> `
  --role-quorum-minimum <predeclared-count> `
  --legacy-score-threshold <predeclared-score> `
  --fault-plan <new-sealed-plan.json> `
  --source-manifest ..\submission\experiments\runs\20260916T064806641708Z_sncf_snapshot_2dc07b37\source_manifest.json
```

The seed still controls fixture values and identities; the sealed plan controls
case labels and order. Comparator thresholds are command-line parameters recorded
in both summary and run manifest; they must be chosen before the confirmatory run.
Supplying both `--cases` and `--fault-plan` is rejected.

After the run, independently verify its artifact and source bytes:

```powershell
python ..\submission\verify_evidence_assurance_run.py `
  <run-directory>\evidence_assurance_run_manifest.json `
  ..\submission\experiments\runs\20260916T064806641708Z_sncf_snapshot_2dc07b37\source_manifest.json
```

## Acceptance evidence and failure conditions

- The primary claim passes only if the full gate has fewer false admissions than
  every predeclared baseline, all corrected comparisons and confidence intervals
  are reported, and the clean-case false-hold target is met.
- Any policy exception, duplicate fingerprint, source/plan digest mismatch,
  overwritten artifact, missing raw row or undisclosed post-result code change
  invalidates that confirmatory run.
- A perfect controlled result is not called 100% railway safety or accuracy. Its
  confidence interval and constrained fault model must appear beside the result.
- External validity requires authorized, independently labelled railway workflow
  cases. Until then, the conclusion is limited to software evidence-admissibility.
- Human interviews, usability testing, surveys or observation of controllers are
  a separate human-participant study and require the applicable IRB/SRC review
  before interaction. Repository tests do not authorize that work.

## Mandatory student-owned competition work

The official rules require a research plan containing rationale, question or
engineering goal, expected outcomes, materials, procedures, risk/safety, data
analysis and bibliography. Forms generally include Adult Sponsor Checklist 1,
Student Checklist 1A, Approval 1B, Student Support Disclosure 2A and any additional
forms determined by the affiliated fair/SRC. A continuation project needs the
required continuation documentation and must distinguish this year's work.

The team—not an AI system—must choose and defend the final hypothesis, describe
alternatives, explain every metric and limitation, keep the notebook, prepare the
forms/poster/abstract in compliance with current rules, and be able to reproduce
the run. If team members cannot explain a component, it should not be presented as
their independent contribution.
