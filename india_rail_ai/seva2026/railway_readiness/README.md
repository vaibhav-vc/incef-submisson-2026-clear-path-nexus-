# Railway readiness packs

Everything this project can prepare for the steps that only Indian Railways can complete. Each pack turns a railway
step into review and sign-off.

**Start with [IR_HANDOVER.md](IR_HANDOVER.md)**: the remaining steps in order, who does each, the command to run and what closes it, plus the safety-acceptance dossier.

| Railway step | Pack | Done by this project | Left for the railway |
|---|---|---|---|
| Engineering data (loops, block sections) | `india_rail/railguard/register.py` | Empty template (headers only, nothing pre-filled); validation, including against the network the twin runs on; the twin uses a built register (tracks, headway, no wait without a loop) | Enter every row from Station Working Rules, working time table, signalling plans |
| Feed onboarding | `india_rail/railguard/conformance.py` | Producer and endpoint conformance certificates | CRIS runs both |
| Audit evidence | `india_rail/audit_pack.py` | SBOM, hashed evidence index, controls mapping, NTP clock control | The audit itself |
| Live data and CRIS integration | [LIVE_DATA_INTERFACE.md](LIVE_DATA_INTERFACE.md) | Signed gateway, contract, test vector, simulator, IST clock | Authorise access, share spec, issue keys, integration test |
| Security audit and hosting | [SECURITY_ASVS_CHECKLIST.md](SECURITY_ASVS_CHECKLIST.md), [../../SECURITY.md](../../SECURITY.md) | ASVS L2 self-assessment, attack tests, SAST/SCA | CERT-In/STQC audit; hosting on IR infrastructure |
| Safety acceptance | [HAZARD_LOG.md](HAZARD_LOG.md), [SAFETY_CASE.md](SAFETY_CASE.md) | Draft hazards, mitigations, evidence; safety-case structure | Hazard workshop, scoring, independent assessment, acceptance |
| Shadow-mode trial | [SHADOW_TRIAL_PLAN.md](SHADOW_TRIAL_PLAN.md), `india_rail/railguard/shadow.py` | Protocol, metrics, logging/report endpoints | Run it on a division for 3-12 months |
| Roll-out and training | [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) | Guide and training modules | Deliver training; issue procedures |
| Legal | [../COMPLIANCE_REGISTER.md](../COMPLIANCE_REGISTER.md) | Engineering register against Indian law, rules and standards | Legal review |
| Production deployment | [DEPLOYMENT.md](DEPLOYMENT.md), `Dockerfile`, `docker-compose.railguard.yml` | Hardened container, UPS through NUT, signed checkpoints and restore, health/metrics/JSON logs, hot-standby design; built and restart-tested | Host on IR infrastructure; site UPS and standby; monitoring |
| Cab GNSS units and live push | `railguard/gps.py`, `gnss_agent.py`, `live.py`; [../evidence/gnss](../evidence/gnss), [../evidence/live](../evidence/live) | NMEA/NavIC agent, quality gates, map-matching to real track, spoof rejection; per-cab capability streams; load-tested on the real network | Procure/fit units; issue per-unit keys; field trial |
| People and identity | `india_rail/accounts.py` | Named accounts, lockout, hashed sessions, roles, decisions carry the person | Connect to IR identity (SSO/LDAP) if required; staff-ID naming and retention policy |
| Delay reduction | `india_rail/delay_advisor.py`; [../evidence/real_data/delay_advisor_summary.json](../evidence/real_data/delay_advisor_summary.json) | Chronic losses, junction congestion, late starts, unachievable timings, with levers and persistence on held-out days | Engineering and timetabling review of the top findings; re-run on IR's own running data |
| Freight corridors | `india_rail/freight.py`; [../evidence/freight](../evidence/freight) | DFC network from OSM, conflict-free pathing with an independent check | DFCCIL path and block data, FOIS demand, trial with the DFC control office |
