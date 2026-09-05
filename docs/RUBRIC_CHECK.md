# Rubric Check — AI Finance Controller

## Buildathon Criteria Mapping

| Criterion | Implementation | Evidence |
|-----------|---------------|----------|
| Match rate | 3-pass matcher (exact→fuzzy→exception) | `evaluate_recon.py` match_resolution metric |
| Measured accuracy | Confusion matrix per CH on holdout | `outputs/metrics_report.json` confusion_matrix |
| Honest account | INSUFFICIENT_EVIDENCE + UNRESOLVED_AMBIGUITY terminal states | `docs/CALIBRATION.md` sweep proves both reachable |
| AI not load-bearing | Ablation test: AI on/off → identical outcomes | `tests/test_ablation.py` |
| Branching graph | 8-node DAG, not a chain | `tests/test_causal_dag.py` |
| Double-entry ledger | Balance + account-code mapping check | `src/ledger/bookkeeper.py` |
| Provenance downweighting | Never discard, always downweight | `src/ingest/schemas.py` |
| Blast radius | Signed variance + independent components | `src/agent/blast_radius.py` |
| Exception dossier | Includes genuinely unresolved cases | `src/agent/dossier.py` |
| Synthetic generator | Entity factory + injectors + scenario builder | `src/generate/` |
| Calibration | Sweep per constant, documented | `docs/CALIBRATION.md` |
| Regression guardrails | One test per known failure mode | `tests/test_regression_guardrails.py` |
| One-command bootstrap | `docker-compose up` | `docker-compose.yml` + `entrypoint.sh` |
| Glossary | RCH, FOD, OC, CH defined on first use | `README.md` |
