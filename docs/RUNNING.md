# Running the study

## Before the first graded run (once)
1. `make kit` and `make test`. The tests confirm the kit matches the hashes in `kit/PREREG.md`.
2. Fill in the date in `kit/PREREG.md` and store it somewhere with a trustworthy timestamp (a signed commit, an
   e-mail to yourself, or an embargoed registry entry). The hashes prove that instances, answers, plan, protocols
   and analysis did not change after results were seen.
3. Enable code execution in the app (Track A).

## Track A — one chat per run (follow `kit/RUNSHEET.md` top to bottom)
1. Open a new chat with the model named in the row.
2. **First message:** attach the files in the "attach in the first message" column. If "memory from" names a run,
   also attach that run's `amp_memory.json`. For `FULL` runs, attach the latest feedback file **of the same model**
   (`amp_feedback_48.json` for Opus 4.8, `amp_feedback_55.json` for Opus 5.5); never another model's file, and none
   for other conditions. Paste the `opening` text from `plan.csv`.
3. Send PART2, PART3, PART4, PART5 one per message, **as files** (the problem files are matched by SHA-256; pasted
   text does not match), with no comment.
4. Last message (change the run id):
   > Copy, without changing any value, the final JSON blocks you gave for PART1, PART2, PART3 and PART4 into one
   > JSON object and save it with code to /mnt/user-data/outputs/R007.json
5. Download `R007.json`, `PART5.json` as `R007_p5.json`, `amp_memory.json` for memory conditions, and if present
   `amp_cert.json` as `R007_cert.json` and `amp_evidence.json` as `R007_evidence.json`.
6. Repeat a run only for a platform failure (error, code tool unavailable, chat cannot continue) and log it.
   Refusals and wrong or truncated answers are graded as they are.

**Order:** pilot (15 runs) → read the power table → primary (45) → ablations (100) → baselines (50) → extension (30)
only if the pilot's power table calls for it, decided before the primary tier is graded.

## Grading
In the app: a new chat with `grader/` files, `sealed/KEYS.json`, `plan.csv`, the answer files (or one `runs.zip`),
and — so certificates can be re-checked — `protocols/amp_lab.py` and a zip of `tests/`. Ask it to run
`python grade.py`. Without the last two, oracle claims cannot be checked and are capped at E2 (the report says so).

Locally: `python kit/grader/grade.py <runs folder> kit`. Output: `REPORT.md`, `runs.csv`, `amp_feedback_<model>.json`
in `<runs folder>/results/`. Then `python analysis/plot_results.py <runs folder>/results/runs.csv --out results/`.

## Reading the report
- **R:** 0 = no recovery, 1 = 4.8 + AMP equals plain 5.5. The claim holds only if the CI lower bound is above 0.
- **Ablations:** positive difference = the component helps; use Holm-adjusted p.
- **Baselines:** `FULL` vs `BON5` separates the protocol from the tools; `FULL` vs `CONF` compares with confidence-based allocation.
- **Oracle gating and provenance:** superiority is claimed only on items backed by a proven external oracle.
- **Calibration:** accuracy should rise with the derived evidence level.

## Track B — automated, through the API
See the README. Run it in the Docker image; the runner refuses real API runs if model-written code could read the
API key, the answer key or other runs. A `verifier` must not be one of the compared models.
