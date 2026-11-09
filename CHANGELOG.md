# Changelog

## 6.7.0
- **Runner isolation.** Model-written code runs as a separate OS user with a clean environment; a pre-flight probe
  refuses real API runs if the API key, the answer key or other runs are readable.
- **Verifier separation.** A verifier may not be one of the compared models; the example configuration no longer
  uses the stronger model as the weaker model's verifier.
- **Grader input handling.** One reader for folders and zip archives: `_meta`, `_attest` and `_cert` files are
  classified identically wherever they come from; explicit folders are the only source of runs; conflicting copies
  are reported.
- **Unproven oracle claims.** Claims that cannot be checked after the run are capped at E2 and excluded from the
  oracle-backed subset; the report separates proven, refuted and uncheckable claims.
- **Feedback isolation.** Feedback files are written per model from `FULL` runs only, as the pre-registration states.
- **Kit consistency.** The kit is rebuilt from the generator; the pre-registration hashes match the shipped files,
  and a test enforces it. Run counts and the ablation count are consistent across documents.

## 6.6.0
- Oracle provenance tiers (`given`, `live`, `validator`, `self`) with post-run attestation.
