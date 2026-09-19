# ISEF 2027 source-verification register — not a student bibliography

> **Compliance boundary:** the 2027 ISEF rules say students may not use generative
> AI to create citations. This AI-assisted register identifies candidate original
> sources and the repository claims they may help a student verify. It is not a
> submission bibliography. Each student must open and read every source used,
> confirm its metadata and relevance, then create the final bibliography in the
> student's own words and required citation style.

**Register checked:** 19 September 2026. Web pages can change; record the student's
actual access date in the final bibliography.

## A. Competition rules and project governance

### A1. Society for Science — 2027 International Rules

- Original page: <https://www.societyforscience.org/isef/international-rules/>
- Verify: current rulebook/forms, AI-use table, companion guide and rules wizard.
- Repository use: determines process and eligibility; it does not validate the
  engineering claim.

### A2. Society for Science — Rules for All Projects

- Original page: <https://www.societyforscience.org/isef/international-rules/rules-for-all-projects/>
- Verify: research-plan sections, prior approvals, continuation rules, eligible
  research window, student independence and AI restrictions.
- Critical check: the current page states that AI may be cited as a resource but
  may not write a student's research plan, abstract or poster or create citations.

### A3. Society for Science — Engineering and Invention Projects Guide

- Original page: <https://www.societyforscience.org/isef/international-rules/engineering-and-invention-projects-guide/>
- Verify: which additional rules apply if future work adds surveys, interviews,
  testing with people, hazardous devices or field activity.

### A4. Society for Science — Grand Award Judging Criteria

- Original page: <https://www.societyforscience.org/isef/grand-award/criteria/>
- Verify: engineering problem (10), design/methodology (15), construction/testing
  (20), creativity/potential impact (20), and presentation (35).

## B. Repository data and licence provenance

### B1. transport.data.gouv.fr — Réseau SNCF TGV, Intercités et TER dataset

- Original catalogue page: <https://transport.data.gouv.fr/datasets/horaires-sncf?locale=fr>
- Publisher shown in the frozen manifest: SNCF Voyageurs.
- Verify: publisher, resource descriptions, update status and special terms.
- Frozen local evidence:
  `submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37/source_manifest.json`
- Scope warning: these are French passenger timetable/feed bytes, not Indian
  Railways data, accident labels or operational authority.

### B2. Open Data Commons — Open Database License 1.0

- Original licence: <https://opendatacommons.org/licenses/odbl/1-0/>
- Verify: attribution, share-alike and keep-open requirements that apply to the
  database use. Ask the relevant publisher/legal owner about any ambiguity.

### B3. MobilityData — GTFS Schedule Reference

- Original specification: <https://gtfs.org/documentation/schedule/reference/>
- Verify: meaning and required fields of `agency.txt`, `routes.txt`, `trips.txt`,
  `stops.txt` and `stop_times.txt`.

### B4. MobilityData — GTFS Realtime Reference

- Original specification: <https://gtfs.org/documentation/realtime/reference/>
- Verify: protobuf entities for trip updates and service alerts.
- Scope warning: the repository snapshot preserves the realtime protobuf bytes but
  its source manifest states that semantic decoding was not performed.

## C. Indian railway context and safety boundary

### C1. Centre for Railway Information Systems — official organization site

- Original site: <https://cris.org.in/>
- Candidate pages to locate and independently verify: Freight Operations
  Information System (FOIS), Control Office Application (COA) and Real Time Train
  Information System (RTIS).
- Repository use: establishes that operational railway information already belongs
  to specialized institutional systems. It does not authorize public API access or
  make this prototype a replacement.

### C2. Research Designs and Standards Organisation — Kavach specification

- Official document located through the RDSO domain:
  <https://rdso.indianrailways.gov.in/uploads/files/System%20Requirement%20Specification%20of%20Kavach%20%28The%20Indian%20Railway%20ATP%29%20Amdt-1-26-05-2023.pdf>
- Document identifier reported by RDSO: RDSO/SPN/196/2020, Version 4.0 d3,
  Amendment 1, effective 26 May 2023.
- Verify: document revision/current superseding amendments before use; distinguish
  automatic train protection and speed supervision from this project's non-vital
  evidence assurance.

### C3. CERT-In — Guidelines for Secure Application Design, Development,
Implementation & Operations

- Official PDF: <https://www.cert-in.org.in/PDF/CIWP-2023-0001.pdf>
- Verify: applicable secure-development and API-security guidance.
- Repository use: security design context only; following guidance is not a
  certification or audit approval.

## D. Provenance, integrity and statistical methods

### D1. W3C — PROV Overview

- Original recommendation overview: <https://www.w3.org/TR/prov-overview/>
- Verify: concepts for entities, activities, agents and provenance relationships.
- Repository use: conceptual background for traceable evidence lineage; the project
  does not claim formal PROV conformance unless separately tested.

### D2. NIST — Secure Hash Standard (FIPS PUB 180-4)

- Original NIST publication page: <https://csrc.nist.gov/pubs/fips/180-4/upd1/final>
- Verify: current status/superseding revision and the SHA-256 definition.
- Repository use: content-integrity digests. A matching hash does not establish
  truth, authority, freshness or safe operational use.

### D3. Wilson — interval for a binomial proportion

- Locate/verify using DOI: <https://doi.org/10.1080/01621459.1927.10502953>
- Metadata to check against the paper: Edwin B. Wilson; “Probable Inference, the
  Law of Succession, and Statistical Inference”; *Journal of the American
  Statistical Association* 22(158), 209–212 (1927).
- Repository use: Wilson 95% intervals for false-admission and false-hold rates.

### D4. McNemar — correlated proportions

- Locate/verify using DOI: <https://doi.org/10.1007/BF02295996>
- Metadata to check against the paper: Quinn McNemar; “Note on the Sampling Error
  of the Difference Between Correlated Proportions or Percentages”;
  *Psychometrika* 12(2), 153–157 (1947).
- Repository use: exact paired comparisons because validators classify the same
  cases.

### D5. Holm — multiple-test correction

- Locate/verify using DOI/stable identifier: <https://doi.org/10.2307/4615733>
- Metadata to check against the paper: Sture Holm; “A Simple Sequentially Rejective
  Multiple Test Procedure”; *Scandinavian Journal of Statistics* 6(2), 65–70
  (1979).
- Repository use: family-wise adjustment across predeclared baseline comparisons.

### D6. Matthews — Matthews correlation coefficient origin

- Locate/verify using DOI: <https://doi.org/10.1016/0005-2795(75)90109-9>
- Metadata to check against the paper: B. W. Matthews; “Comparison of the Predicted
  and Observed Secondary Structure of T4 Phage Lysozyme”; *Biochimica et
  Biophysica Acta — Protein Structure* 405(2), 442–451 (1975).
- Repository use: a secondary classification-quality measure; the paper's subject
  matter is protein structure, not railway safety.

## E. Internal primary artifacts to cite precisely in the research record

These are reproducibility artifacts, not external scholarly authority:

1. Source manifest:
   `submission/experiments/runs/20260916T064806641708Z_sncf_snapshot_2dc07b37/source_manifest.json`
   — manifest-file SHA-256
   `b2d83222fe4bab87f393b8e93c8a29f87ac2f8279ebd9de6ca63f25604bbf49f`.
2. Development run manifest:
   `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/evidence_assurance_run_manifest.json`.
3. Development run summary:
   `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/evidence_assurance_summary.json`.
4. Raw case rows:
   `submission/experiments/runs/20260919T040756096976Z_evidence_assurance_40fe5fe4/evidence_assurance_cases.csv`
   — SHA-256
   `95d62852283860700aa3ea52195992daa71c1f9cec5425220423d1c98f071e99`.
5. Frozen software version: use the annotated Git tag named in the release handoff;
   resolve it with `git rev-list -n 1 <tag>` and record the resulting commit.

## Student source-verification worksheet

Complete one row for every item actually used in the student-authored bibliography.

| Source ID | Student opened original? | Metadata verified? | Relevant claim and page/section | Limitations/conflict | Student initials/date |
|---|---|---|---|---|---|
|  |  |  |  |  |  |

Do not cite a source merely because it appears in this register. Do not cite a
search-result snippet. Prefer the original publisher, specification, standard or
paper, and preserve the exact version used.
