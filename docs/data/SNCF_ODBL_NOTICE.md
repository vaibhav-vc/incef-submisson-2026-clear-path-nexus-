# SNCF open-data attribution and separation notice

The optional research recorder in
`submission/experiments/record_official_sncf_snapshot.py` downloads the public
SNCF TGV, Intercités and TER schedule and real-time resources linked by France's
National Access Point for transport data.

- Publisher: SNCF Voyageurs
- Dataset catalogue and scope: <https://transport.data.gouv.fr/datasets/horaires-sncf?locale=fr>
- Licence shown by the catalogue: Open Database License (ODbL) 1.0
- Licence text: <https://opendatacommons.org/licenses/odbl/1-0/>
- Platform's ODbL conditions page: <https://doc.transport.data.gouv.fr/le-point-d-acces-national/cadre-juridique/conditions-dutilisation-des-donnees/licence-odbl.md>

Attribution: **Contains information from SNCF Voyageurs' “Réseau SNCF TGV,
Intercités et TER” dataset, made available under ODbL 1.0 and the stated
particular conditions of use.** Each recorded manifest includes the exact
source URLs, retrieval timestamps, HTTP metadata, byte lengths and SHA-256
digests.

These are real publisher bytes, but they are not Indian Railways data, verified
incident reports, movement authority, signalling inputs, engineering limits or
proof of operational safety. Controlled mutations created by the comparative
benchmark are labelled `CONTROLLED_TEST_MUTATION` and are never described as
real events. The catalogue itself warns that feed scope and quality have limits;
users must consult the live catalogue and competent transport authorities before
any reuse.
