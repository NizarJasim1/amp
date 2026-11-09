# Pre-registration: AMP v6

Fill in the date, then commit this file **before the first graded run**. If you use OSF, register WITH AN EMBARGO
until the patent decision is made: a public registration can count as a disclosure. This file contains no
mechanism details, only hypotheses and hashes. The SHA-256 values at the bottom freeze the test instances, the answer key, the run plan, every
protocol variant, and the analysis code. Any later change to these files shows up as a hash mismatch.

Date registered: ____________   Registered by: ____________

## 1. Question
Can a pure-text protocol plus a tested tool library, carried by the weaker model itself inside one ordinary
chat, recover a measurable share of the capability gap between two generations of the same model family? And
which component carries the effect?

## 2. Design
- **Instances.** Every test seed has its own freshly generated instance: 6 insight problems drawn from 7
  families, 4 grid-induction puzzles from a grammar of 6 rule kinds, 2 precise-execution transcripts, 4
  parameterised constructions, and 4 idea tasks scored on hidden instances. No answer existed anywhere before
  generation. Every exact answer was checked at generation time against an independent brute force on small
  parameters.
- **Blocks.** Every seed is run under every condition of its tier. All comparisons are paired on seeds. The order
  of conditions inside a seed block is randomised by a fixed seed.
- **Cells.** CONDITION@MODEL. 48 = Opus 4.8, 55 = Opus 5.5. Code execution is on in every cell.
- **Plan.** __NRUNS__ runs in `plan.csv`, organised in tiers: pilot (seeds 1–5), primary (6–20), ablation (1–10),
  baselines (1–10), and an optional extension (21–30).

## 3. Endpoints
- **Primary:** `exact` = share of the 12 exact items solved (Q1–6, G1–4, K1, T1).
- **Secondary:** per family (insight Q, induction G, precision P); `creative` = mean of the four construction
  scores normalised by a simple reference construction (invalid = 0); `ideas` = mean improvement over a simple
  baseline on hidden instances (missing or crashing code = 0); Brier score of the stated probabilities.

## 4. Hypotheses and predictions (written before data)
- **H1 (primary).** Gap recovery R = (FULL@48 − PLAIN@48) / (PLAIN@55 − PLAIN@48) on `exact` has a 95% CI
  lower bound above 0. Predicted point estimate: R ≥ 0.5.
  *Falsified if* the lower bound is ≤ 0. If the gap itself is not established (the CI of PLAIN@55 − PLAIN@48
  includes 0), H1 is reported as untestable, not as confirmed.
- **H2.** FULL@48 − PLAIN@55 on `exact`: report the point estimate and CI. Superiority is claimed only if the
  CI lower bound is above 0.
- **H3 (ablation).** Removing any one component lowers `exact`. Predicted order of contribution: ORACLE, LAB, INS,
  BLIND, ATT, EV > MEM, IDEA on `exact`; IDEA largest on `ideas`; ORACLE largest where tasks are oracle-rich.
  DATA and OUT are also ablated; no rank is predicted for them. Holm correction across all 10 ablations.
  ATT (attested, independence-aware checks) is also predicted to lower the share of wrong answers reported
  with p ≥ .9 ("silent errors").
- **H4 (baselines).** FULL@48 > TOOLS@48, SC5@48, BON5@48, and CONF@48 on `exact`. Holm correction across the 4
  baselines. BON5 and CONF get the same tool library as FULL. FULL vs BON5 isolates the protocol from the tools;
  FULL vs CONF compares against the closest prior art (allocation by self-confidence).
- **H5 (calibration).** In AMP runs, accuracy rises with the stated evidence level E. FULL@48 has a lower Brier
  score than PLAIN@48.
- **Predicted negative results.** R on `induction G` has a CI that includes 0. Recovery on `creative` and `ideas`
  is smaller than on `insight Q`.

- **H6 (safety endpoint).** The silent-error rate (items answered wrong with stated p ≥ .9) is lower in FULL@48 than in
  CONF@48 and noATT@48.
- **H7 (tracks).** Where seeds are run in both the app (Track A) and through the API runner (Track B), the per-cell
  difference has a CI that includes 0 (`analysis/compare_tracks.py`). If not, both tracks are reported separately.
- **Exploratory, labelled as such:** recovery curve across extra model pairs (`analysis/law.py`, at least 4 pairs
  before any fit is called a law); external ARC anchor with the isomorph contamination audit (`external/arc_anchor.py`).

- **H8 (governing / oracle gating).** FULL@48 exceeds PLAIN@55 (mean item accuracy) on the subset of items FULL
  backed with an external oracle, and does NOT exceed it on the non-oracle subset. Predicted: positive on the
  oracle subset, ≤ 0 on the other. This is the test that the edge is the external oracle, not the model. Removing
  the oracle doctrine (noORACLE) lowers `exact` the most among ablations on oracle-rich tasks.

## 5. Analysis (exactly what `grader/grade.py` does)
- Unit of analysis: the seed. With replicate runs, the mean over runs of a seed.
- CIs: percentile bootstrap over seeds, B = 10,000, fixed RNG seed. p-values: two-sided paired sign-flip
  permutation test (exact for n ≤ 16). Effect sizes: d_z and Cliff's δ.
- Multiplicity: Holm within each table (ablations; baselines). H1 is the single primary test and is not
  adjusted.

## 6. Stopping and exclusions
- The pilot (seeds 1–5) is used ONLY to estimate the standard deviation for the power table. It is included
  in the final analysis. The decision to run the extension (seeds 21–30) is made from the pilot's power table,
  before any primary-tier result is graded. There is no optional stopping on p-values.
- A run is repeated (same seed, same condition) only for a platform failure: an error message, code execution
  unavailable, or the chat cannot continue. Every repetition is logged in `plan.csv` notes. Refusals, wrong
  formats, and truncated answers are graded as they are.
- Memory chains: memory-enabled conditions attach the `amp_memory.json` of the previous run in the same cell
  (column `memory_from`). After each grading round, `grade.py` writes one feedback file per model from that
  model's FULL runs only (`amp_feedback_48.json`, `amp_feedback_55.json`); each is attached only to the following
  FULL runs of the same model. Ablations never receive another cell's memory or feedback.

## 7. Frozen files (SHA-256)
| file | sha256 |
|---|---|
__HASHES__
