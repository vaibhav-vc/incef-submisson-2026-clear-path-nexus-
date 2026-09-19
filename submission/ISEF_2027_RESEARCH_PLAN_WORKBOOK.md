# ISEF 2027 research-plan workbook — student completion required

> **Compliance boundary:** this is an AI-assisted planning aid and evidence index,
> not the student's research plan. The 2027 ISEF rules say a student may not use
> generative AI to write the submitted research plan or create its citations. The
> student team must independently make the choices below, consult the Adult
> Sponsor/SRC, read every source it uses, and write the final plan in its own words.
> Do not submit this file as student-authored work and do not backdate it.

**Prepared:** 19 September 2026

**Purpose:** support a new, prospective confirmatory phase without rewriting the
history of work already completed in the repository.

**Project type to confirm with the SRC:** continuation/research progression. The
repository contains development and test activity before this workbook was made;
the team should assume continuation documentation is required unless its SRC says
otherwise.

## 1. Project identity worksheet

The student team must complete these fields before any new confirmatory data are
collected.

- Student researcher(s): `[student entry]`
- School and affiliated fair: `[student entry]`
- Adult Sponsor: `[student entry]`
- Qualified Scientist or mentor, if any: `[student entry]`
- Proposed category/subcategory: `[student entry after checking current fair list]`
- Current-year research period: `[student entry; maximum eligible window must be checked]`
- Prior-year work being continued: `[student description in own words]`
- New work that is a substantive expansion: `[student description in own words]`
- Required approvals and form numbers confirmed by SRC: `[student/SRC entry]`

## 2. Narrow claim boundary to evaluate

The implemented prototype is a **non-vital evidence-admissibility gate**. It tests
whether a software recommendation is supported by records having the required
source authority, context, freshness, roles, lineage and integrity. It does not
control a train.

The team should formulate its own research problem around this measurable software
claim. It must not claim that the current work:

- prevents railway collisions or establishes a safe driver speed;
- issues movement authority, signals, braking commands or driver instructions;
- validates carriage loads, braking curves or network timetables;
- uses Indian Railways operational data;
- is certified, production-authorized or capable of replacing Indian Railways; or
- converts controlled software mutations into real incidents or field evidence.

The phrase "replacement of Indian Railways" is not a testable or supported claim.
A defensible long-term vision is interoperability with authorized railway systems
after operator partnership, independent safety assessment, field trials and
regulatory acceptance. The current study remains research-only.

## 3. Student decision sheet: rationale and research problem

Write the final response independently. Use the prompts, not the wording, below.

1. What real decision-support failure occurs when current-looking data are accepted
   without checking authority, scope, lineage, role coverage and integrity?
2. Who is affected by a false admission and by a false hold?
3. What is missing from checksum-only, timestamp-only, quorum-only, completeness-only
   and numerical-score validators?
4. Why is a fail-closed, explainable gate worth testing before any field use?
5. Which single measurable claim will the current-year experiment support or reject?

Repository evidence to inspect:

- `docs/RESEARCH_PIVOT_V7.md`
- `docs/INDIAN_RAILWAY_REPLACEMENT_ARCHITECTURE.md`
- `backend/app/services/evidence_gate.py`
- `submission/experiments/run_evidence_assurance_benchmark.py`

## 4. Student decision sheet: engineering goal, criteria and constraints

Before experimentation, the student team should choose and record:

- the engineering goal in one sentence;
- the primary endpoint and directional hypothesis;
- the maximum acceptable false-hold rate on clean cases;
- the required advantage over every predeclared baseline;
- the latency measure and whether it is descriptive or an acceptance criterion;
- the exact case count and rationale;
- the allowed fault classes, exclusions and stopping rules;
- what result would falsify the main claim; and
- why each threshold is appropriate.

Candidate measures already implemented, which the student must understand before
selecting, are false-admission rate, false-hold rate, Wilson 95% intervals,
balanced accuracy, Matthews correlation coefficient, per-fault admission counts,
local-process latency and paired exact McNemar comparisons with Holm correction.

## 5. Variables and controls worksheet

| Item | Candidate implementation fact to verify | Student's pre-experiment decision |
|---|---|---|
| Independent variable | Validator: latest value, checksum/time, role quorum, conservative completeness, legacy score, or full gate | `[student entry]` |
| Primary dependent variable | False-admission rate on controlled mutations | `[student entry]` |
| Clean-case outcome | False-hold rate | `[student entry]` |
| Secondary outcomes | Balanced accuracy, MCC, per-fault results, latency | `[student entry]` |
| Controlled inputs | Same evidence bundle and classification label for all validators | `[student entry]` |
| Frozen parameters | Seed, case plan, quorum, score threshold, source manifest, code commit | `[student entry]` |
| Replication unit | One separately sealed fault plan; cases within a generated plan are not real independent railway events | `[student entry]` |
| Blinding/independence | Plan author should not implement or tune the gate; declaration must name a real person in the private notebook | `[student entry]` |

## 6. Materials inventory

The student should inspect, select and describe only what is actually used:

- a local computer with a recorded operating system and hardware profile;
- Python and dependency versions from the frozen repository;
- the frozen Git commit and annotated tag;
- the benchmark runner, plan sealer and independent verifier;
- a predeclared, sealed fault-plan JSON;
- the archived SNCF publisher snapshot and its SHA-256 manifest;
- storage for immutable raw rows, summaries, manifests and failure logs; and
- the current official fair rules and required forms.

No physical railway equipment, track access, driver interaction, human survey,
passenger data or operator control interface is part of the current protocol.

## 7. Prospective procedure checklist

This checklist is for a **new** confirmatory phase. It does not retroactively turn
the 19 September development run into an independent confirmatory experiment.

1. Obtain the Adult Sponsor/SRC determination and every required approval before
   new experimentation. Record approval dates truthfully.
2. Student team writes and signs its own research plan; record all adult, mentor
   and AI support accurately.
3. Freeze the research question, endpoint, thresholds, baselines, case count,
   exclusions and analysis before seeing confirmatory results.
4. Freeze and record one code commit and verify the external source snapshot using
   its manifest and SHA-256 digests.
5. Have an identified reviewer who did not implement the gate create a new fault
   plan. Preserve the draft; seal it once; do not overwrite it.
6. Run all predeclared validators over identical cases. The validators receive an
   evidence bundle, not the correct classification label.
7. Preserve raw case rows, fingerprints, outcomes, reason codes, timings, summary,
   run manifest, source manifest, sealed-plan digest and environment details.
8. Run `submission/verify_evidence_assurance_run.py` independently and retain its
   unedited output.
9. Repeat using at least three separately authored and sealed plans. Report each
   replication separately before any pooled descriptive summary.
10. Do not repair or tune the system after viewing results and call the same run
    confirmatory. A repair starts a new version and requires a new held-out plan.
11. Record null, negative and failed results. Explain deviations in a dated addendum.

The command sequence and plan schema are maintained in
`docs/ISEF_2027_RESEARCH_PROTOCOL.md`.

## 8. Risk and safety decision sheet

Current repository testing is a software-only activity using controlled fixtures
and public publisher bytes. Reasonable risks include accidental exposure of secrets,
unbounded input/resource use, corrupted artifacts, misleading safety claims and
licence/attribution errors. Existing controls include bounded inputs, digest
verification, fail-closed decisions, archived source bytes, secret scanning in CI
and explicit non-vital scope.

The team must stop and obtain the applicable review **before** adding interviews,
surveys, usability tests, observations of railway personnel, personal data, field
tests, physical rail equipment, hazardous devices or any connection to operational
railway control. Repository tests are not approval for those activities.

## 9. Analysis decision sheet

Before a confirmatory run, the student team should be able to derive or explain:

- TP, TN, FP and FN for each validator;
- false-admission = FP / (FP + TN);
- false-hold = FN / (FN + TP);
- why a confidence interval is shown even when the observed rate is zero;
- why paired comparisons use the same cases;
- what the McNemar discordant pairs mean;
- why multiple-comparison correction is needed;
- why generated cases within one plan do not establish external railway validity;
- why local latency is not a production availability or capacity result; and
- which conclusions remain valid if the primary hypothesis fails.

## 10. Existing development evidence — not confirmatory proof

The repository contains a 19 September 2026 internal seeded development run with
2,400 unique software cases: 462 clean fixtures and 1,938 controlled mutations.
The full gate recorded 0 false admissions and 0 false holds; its Wilson upper 95%
bounds were 0.001978 and 0.008246 respectively. The strongest simple baseline in
that run recorded 953 false admissions. These results are useful for debugging and
method selection, but the run declared `INTERNAL_SEEDED_GENERATOR` and
`declared_independence: false`; it is not the independent held-out confirmation.

Evidence paths:

- `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/evidence_assurance_cases.csv`
- `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/evidence_assurance_summary.json`
- `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/evidence_assurance_run_manifest.json`

## 11. Student contribution and disclosure worksheet

For every major element, record who proposed it, who implemented it, who tested it,
what outside help was received, and what the student can independently explain.

| Element | Student work | Teammate work | Mentor/adult work | AI/tool assistance | Evidence/date |
|---|---|---|---|---|---|
| Research question |  |  |  |  |  |
| Gate design |  |  |  |  |  |
| Benchmark design |  |  |  |  |  |
| Code implementation |  |  |  |  |  |
| Statistical analysis |  |  |  |  |  |
| Interpretation |  |  |  |  |  |
| Final writing |  |  |  |  |  |

Anything the team cannot explain should not be presented as independent student
work. The official Student Support Disclosure and any continuation forms must be
completed under the current fair rules.

## 12. Completion gate

Do not begin the new confirmatory phase until every box is truthfully complete:

- [ ] Current rules read by student and Adult Sponsor.
- [ ] SRC/form determination recorded.
- [ ] Student-authored plan finished before experimentation.
- [ ] Continuation/current-year boundary documented.
- [ ] Human-participant and field work excluded or separately preapproved.
- [ ] Primary endpoint, thresholds and failure conditions frozen.
- [ ] Independent plan author identified.
- [ ] Code, data and plan freeze identifiers recorded.
- [ ] Student-created bibliography verified against original sources.
- [ ] Assistance disclosure complete.
