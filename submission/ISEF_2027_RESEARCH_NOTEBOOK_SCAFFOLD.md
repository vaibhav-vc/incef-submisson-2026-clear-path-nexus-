# ISEF 2027 research notebook scaffold

> **Integrity notice:** this file is an AI-assisted blank structure plus a
> repository-derived retrospective evidence log. It is not a contemporaneous
> student notebook and contains no invented observations, approvals, signatures or
> student reflections. Students should keep their own dated record and may use
> these verified repository events only after checking the cited artifacts.

## Notebook identity

- Project title: `[student entry]`
- Student researcher(s): `[student entry]`
- School/fair: `[student entry]`
- Adult Sponsor: `[student entry]`
- Notebook start date: `[actual date entered by student]`
- Boundaries inherited from earlier work: `[student entry]`
- Current-year work starts: `[student/SRC entry]`

## Evidence labels

- **REPOSITORY-DERIVED:** fact reconstructed from a tracked manifest, result or Git
  record. It is not evidence that a student wrote a contemporaneous note.
- **STUDENT ENTRY REQUIRED:** only the researcher can provide the observation,
  decision, reasoning or signature.
- **FUTURE PROTOCOL:** planned activity that has not occurred merely because it is
  written here.

## Retrospective repository evidence log

### 16 September 2026, 06:48:06–06:48:14 UTC — source snapshot

**Label:** REPOSITORY-DERIVED

**Evidence:** `submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37/source_manifest.json`

The recorder archived three SNCF Voyageurs resources from the French national
transport-data platform: one GTFS schedule ZIP and two GTFS-Realtime protobuf
payloads. The manifest records retrieval timestamps, final URLs, response metadata,
byte lengths and SHA-256 digests. Static ZIP validation found the required GTFS
members and 38,050 trip rows, 330,490 stop-time rows and 8,713 stop rows. The two
realtime payloads were retained byte-for-byte but were not semantically decoded.

**What this supports:** reproducible proof of which publisher bytes were present.

**What it does not support:** Indian Railways provenance, incident labels,
operational authority, carriage loads, collision risk or safety validation.

**Student verification/reflection:** `[student entry after opening the manifest]`

### 16 September 2026, 06:48:55 UTC — benchmark v1 development run

**Label:** REPOSITORY-DERIVED

**Evidence:** `submission/experiments/runs/20260916T064855068103Z_evidence_assurance_1431e7d7/`

An earlier evidence-assurance run was preserved. Students should compare its
manifest, parameters and limitations with the later v2 run before deciding whether
it belongs in current-year analysis.

**Student comparison and decision:** `[student entry]`

### 18 September 2026 — security and validation repair

**Label:** REPOSITORY-DERIVED

**Evidence:** Git commit `54f223a17b6a4b549ca2715c095d362453e3bf32`,
subject “Fix locally reproduced security and carriage validation gaps.”

This commit is evidence of engineering change, not evidence of a successful safety
study. Students should review the diff and record which parts they personally
designed, implemented or verified.

**Student contribution/reflection:** `[student entry]`

### 19 September 2026, 04:07:56 UTC — benchmark v2 development run

**Label:** REPOSITORY-DERIVED

**Evidence:** `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/`

The internal seeded run contains 2,400 unique controlled software cases (462 clean,
1,938 mutated). The full gate produced TP=462, TN=1,938, FP=0 and FN=0. The Wilson
95% upper bound was 0.001978 for false admission and 0.008246 for false hold. The
strongest simple baseline by false-admission rate, conservative completeness,
produced FP=953 and TN=985. The paired comparison had 953 discordant cases, all in
favor of the full gate, with log10(p)=-286.580556.

The run manifest also says `origin: INTERNAL_SEEDED_GENERATOR` and
`declared_independence: false`. Therefore this is a development benchmark, not an
independent held-out replication and not field evidence.

**Student interpretation in own words:** `[student entry]`

**Unexpected observations/errors:** `[student entry]`

**Decision made after this run:** `[student entry]`

### 19 September 2026 — benchmark reproducibility hardening

**Label:** REPOSITORY-DERIVED

**Evidence:** Git commits `5e120d352b3c7160792db648ef790eded12eb287`
and `ecf393ee40808eae96e5da261a34618d6eb38bf5`.

The first commit added the held-out research protocol and verifier; the second
made artifact verification byte-stable across platforms. The exact CI run and test
result should be attached by the student after independently checking GitHub.

**Student verification/reflection:** `[student entry]`

## Prospective notebook entry template

Copy this section for each actual research session. Complete it at the time of
work; never reconstruct a signature or approval date.

### `[YYYY-MM-DD HH:MM timezone]` — `[short activity title]`

- Entry type: `[planning / build / test / analysis / failure / deviation]`
- People present and roles: `[student entry]`
- Objective decided before work: `[student entry]`
- Frozen commit/tag: `[student entry]`
- Source manifest SHA-256: `[student entry]`
- Sealed plan filename and SHA-256: `[student entry]`
- Environment/hardware: `[student entry]`
- Exact procedure or command: `[student entry]`
- Raw output directory: `[student entry]`
- Expected outcome: `[student entry before run]`
- Observed outcome, including failures: `[student entry after run]`
- Quantitative results: `[student entry]`
- Interpretation and limitations: `[student entry]`
- Protocol deviation and reason: `[none, or student entry]`
- Next decision: `[student entry]`
- Files/photos/screenshots attached: `[student entry]`
- Researcher initials/signature: `[real student action]`
- Adult/mentor witness, if applicable: `[real person/date; do not backfill]`

## Confirmatory-run checklist entry

- [ ] Approval existed before the run.
- [ ] Student-authored plan and analysis choices were frozen before results.
- [ ] This is a new, never-before-used sealed fault plan.
- [ ] The plan author and independence declaration are documented.
- [ ] Source bytes and manifest digests verified.
- [ ] Code tag and commit recorded.
- [ ] All validators saw the same case bundles.
- [ ] Raw rows and failures preserved.
- [ ] Independent verifier passed without modifying artifacts.
- [ ] No post-result tuning was relabelled as confirmatory.
- [ ] Negative and null outcomes were retained.

## Required final student synthesis

The student team should add, in its own words:

1. why the observed results did or did not support the predeclared hypothesis;
2. the largest source of internal and external validity risk;
3. what changed from earlier work and why it is a substantive continuation;
4. which parts were student work, teammate work, mentor work and tool/AI support;
5. the next experiment that could most strongly disprove the claim; and
6. why no conclusion about real train control follows from this software benchmark.
