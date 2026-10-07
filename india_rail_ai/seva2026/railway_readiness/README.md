# Railway readiness packs

Everything this project can prepare for the steps that only Indian Railways can complete. Each pack turns a railway
step into review and sign-off.

| Railway step | Pack | Done by this project | Left for the railway |
|---|---|---|---|
| Live data and CRIS integration | [LIVE_DATA_INTERFACE.md](LIVE_DATA_INTERFACE.md) | Signed gateway, contract, test vector, simulator, IST clock | Authorise access, share spec, issue keys, integration test |
| Security audit and hosting | [SECURITY_ASVS_CHECKLIST.md](SECURITY_ASVS_CHECKLIST.md), [../../SECURITY.md](../../SECURITY.md) | ASVS L2 self-assessment, attack tests, SAST/SCA | CERT-In/STQC audit; hosting on IR infrastructure |
| Safety acceptance | [HAZARD_LOG.md](HAZARD_LOG.md), [SAFETY_CASE.md](SAFETY_CASE.md) | Draft hazards, mitigations, evidence; safety-case structure | Hazard workshop, scoring, independent assessment, acceptance |
| Shadow-mode trial | [SHADOW_TRIAL_PLAN.md](SHADOW_TRIAL_PLAN.md), `india_rail/railguard/shadow.py` | Protocol, metrics, logging/report endpoints | Run it on a division for 3-12 months |
| Roll-out and training | [OPERATOR_GUIDE.md](OPERATOR_GUIDE.md) | Guide and training modules | Deliver training; issue procedures |
| Legal | [../COMPLIANCE_REGISTER.md](../COMPLIANCE_REGISTER.md) | Engineering register against Indian law, rules and standards | Legal review |
