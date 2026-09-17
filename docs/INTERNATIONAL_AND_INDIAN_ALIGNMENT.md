# International evaluation and Indian Railway alignment

Checked 17 September 2026. Internal engineering guidance, not a student-authored research plan, abstract, poster or submission bibliography.

## Competition benchmark

The [official INSEF 2026–27 page](https://www.insef.org/insef/) gives a 30 September 2026 submission deadline and permits teams of at most two. ISEF is a separate competition; this document does not establish an INSEF-to-ISEF qualification route.

The [ISEF engineering rubric](https://www.societyforscience.org/isef/grand-award/criteria/) allocates 10 points to the problem, 15 to design/methodology, 20 to construction/testing, 20 to creativity/impact and 35 to presentation (10 poster, 25 interview). For this repository, the corresponding evidence is a precise problem, alternatives and baselines, repeatable trials, a defensible contribution, and the students' understanding of their own work. These are target criteria, not a predicted score.

The contribution under investigation is the exact binding of a recommendation to evidence authority, subject/context, time, dependencies and independent review, followed by reproducible reconstruction. Its originality is not established by the repository's feature count or test count. Independent prior-art comparison, held-out cases, externally designed faults, ablation studies and a relevant Indian data evaluation remain necessary research work. They must be designed and understood by the students with their sponsor.

## Indian Railway applicability

| Primary reference | Relevance to the programme | Present status |
|---|---|---|
| [CRIS project inventory](https://cris.org.in/loadpage?page=ProjectListPage), [COA](https://cris.org.in/loadpage?page=proCOA), [RTIS](https://cris.org.in/loadpage?page=proRTIS) | Incumbent capabilities, operational identities and system interfaces to preserve during migration | Architecture mapping; no authorized operational integration |
| [RDSO CTC FRS 2025, version 2.0, effective 3 March 2025](https://rdso.indianrailways.gov.in/uploads/files/CTC%20revised%20FRS%20effected%20from%203rd%20Mar%202025.pdf) | Functional baseline for any future CTC scope | Reference reviewed; clause-level conformance not demonstrated |
| [RDSO/SPN/196/2020 Kavach SRS version 4.0 amendment 3, effective 7 June 2024](https://rdso.indianrailways.gov.in/uploads/System%20requiremnt%20specification%20amd%203%20ver%204_0.pdf) | Applicable to a future Kavach/ATP product/interface scope, not automatic certification of an analytics application | No Kavach/ATP implementation or conformance claim |

The cited Kavach specification addresses train/brake characteristics in section 3.5.7, communication authenticity in section 4, and real-line specific-application acceptance with safety-case/independent-assessment evidence in section 34. A general web speed suggestion cannot stand in for these requirements. Applicable versions, amendments and authority must be confirmed for the exact proposed scope; older drafts found online must not be substituted.

The [government evaluation pack](GOVERNMENT_TECHNICAL_EVALUATION.md) and [replacement architecture](INDIAN_RAILWAY_REPLACEMENT_ARCHITECTURE.md) preserve the national objective while making each missing acceptance item visible.

## Student ownership and assistance record

The [current ISEF rules](https://www.societyforscience.org/isef/international-rules/rules-for-all-projects/) require disclosure of AI assistance and prohibit AI-written research plans, abstracts, posters and citations. The students and sponsor must check the actual fair's rules and prepare the submission themselves. Generated repository planning text is engineering assistance, not evidence of student authorship.

Known assistance in this change set: Codex and sub-agents generated and revised backend/frontend code, tests, experimental tooling, architecture/evaluation documents and review findings; tools executed tests, fetched public SNCF data and ran controlled benchmarks. The students requested the direction. This record does not claim they independently authored, validated or understood every generated change. Those contributions and their own subsequent decisions, experiments and explanations must be recorded accurately in their notebook and disclosure materials. Do not backdate approvals or replace the original provenance.

## Release evidence

Runtime code commit `7dfc91bd063e26f73084301bf0b2cce8f1619adb` passed all five jobs in [GitHub CI run 35176284755](https://github.com/vaibhav-vc/incef-submisson-2026-clear-path-nexus-/actions/runs/35176284755): backend, frontend, deployment, judge-demo and Android. The judge job includes actual HTTP/PostgreSQL assurance persistence, export and offline checksum reconstruction. The backend suite contains 346 passing tests. These are software results, not competition qualification or railway approval.
