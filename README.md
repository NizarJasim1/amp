# AMP — a pre-registered test of how much of a model generation is reachable by method

![python](https://img.shields.io/badge/python-3.10%2B-3776AB)
![dependencies](https://img.shields.io/badge/core-standard%20library%20only-555)
![tests](https://img.shields.io/badge/tests-134-2E7D32)
![design](https://img.shields.io/badge/design-pre--registered%20%C2%B7%20SHA--256%20frozen-8E44AD)

**AMP (Calibrated Evidence Lab)** is a one-file, text-only protocol plus a tested Python instrument library that a
language model carries inside an ordinary chat. This repository contains the protocol, the library, a benchmark
generator, an automated runner, a grader, and the full pre-registered study design used to answer one question:

> **What share of the capability gap between two model generations can the weaker model recover by method alone —
> with no weight change — and which component carries the effect?**

The study compares Claude Opus 4.8 and Claude Opus 5.5. The design, the analysis code, every test instance and the
answer key are frozen by SHA-256 before the first graded run, and anyone can rebuild the frozen kit byte-for-byte
from the generator in this repository and check those hashes.

---

## Contents
- [Core idea](#core-idea)
- [What is measured](#what-is-measured)
- [Study design](#study-design)
- [Results](#results)
- [Quick start](#quick-start)
- [Running the study](#running-the-study)
- [Security model of the automated runner](#security-model-of-the-automated-runner)
- [Threats to validity](#threats-to-validity)
- [Repository layout](#repository-layout)
- [Citation](#citation) · [License](#license)

---

## Core idea

A scaffold that only *organises thinking* lifts a stronger model as much as a weaker one, so it cannot explain a
weaker model catching up. AMP is built on the one mechanism that can: **correctness decided outside the model**.

1. **Evidence levels, derived rather than declared.** Every answer carries a level from E0 (guess) to E4. The level
   is computed by the library from what was actually executed, not from what the model says about itself.
2. **Oracle provenance is checked.** An answer reaches E3 only when an *external* oracle confirms it: example pairs
   given by the problem (`given`), a live system (`live`), or a shipped validator (`validator`). A reference the
   model wrote itself (`self`, e.g. its own brute force) is capped at E2, because it shares the model's reading of the
   problem. `given` is verified against the SHA-256 of the real problem files; `live` needs a receipt signed by the
   runner with a key that never enters the model's sandbox.
3. **Independence-aware verification.** Two checks that call the same helper, reuse each other's outputs, or share
   a representation can fail together. The registry predicts that shared-failure risk from the executed structure
   *before* any grading, turns it into a binding design for the next check, and verifies compliance.
4. **Calibrated compute allocation.** Effort goes to the item with the highest expected gain in correctness per
   unit of cost, using a calibration table learned from graded outcomes of earlier sessions.

The claim is deliberately scoped: the weaker model with AMP is compared with the **plain** stronger model on tasks
where an external check exists. It is **not** claimed to beat the stronger model when that model also runs AMP;
the `FULL@55` cell measures exactly that case.

## What is measured

| quantity | definition |
|---|---|
| **Gap recovery R** | `(FULL@48 − PLAIN@48) / (PLAIN@55 − PLAIN@48)` on exact answers, paired bootstrap CI over seeds. R = 1 means 4.8 + AMP equals plain 5.5. |
| **Direct comparison** | `FULL@48 − PLAIN@55`, reported with its CI; superiority is claimed only if the CI lies above 0. |
| **Component attribution** | 10 ablations, each removing exactly one component, Holm-corrected. |
| **Method vs tools** | baselines at equal model: plain tool use, self-consistency, best-of-5 *with the same library*, and confidence-based allocation (closest prior art). |
| **Oracle gating** | accuracy on oracle-backed vs other items; the edge is predicted to appear only on the former. |
| **Silent errors** | share of items answered wrong with stated probability ≥ 0.9. |
| **Calibration** | Brier score; accuracy by derived evidence level. |

## Study design

- **Fresh instances.** Each of 30 seeds generates its own test: 6 insight problems (7 families), 4 grid-induction
  puzzles (6 rule kinds), 2 precise-execution transcripts, 4 parameterised constructions, and 4 idea tasks scored
  on hidden instances. Every exact answer is checked at generation time against an independent brute force.
- **Conditions** are cells `CONDITION@MODEL`. All ablations are produced mechanically from one protocol source by
  deleting one tagged module, so each differs from `FULL` in exactly one component.
- **Plan.** 240 runs in tiers: pilot (seeds 1–5), primary (6–20), ablations (1–10), baselines (1–10), optional
  extension (21–30), randomised order within each seed block.
- **Statistics.** Unit = seed. Percentile bootstrap (B = 10,000, fixed seed), paired sign-flip permutation tests,
  d_z and Cliff's δ, Holm within each table. The pilot is used only to size the study; no optional stopping.
- **Pre-registration.** [`kit/PREREG.md`](kit/PREREG.md) lists hypotheses H1–H8, the predicted *negative* results,
  exclusion rules, and the SHA-256 of the answer key, the plan, every protocol variant and the analysis code.

## Results

Graded results are published here together with the raw answer files, so every number can be re-derived:

```bash
python kit/grader/grade.py runs/ kit            # → runs/results/REPORT.md, runs.csv
python analysis/plot_results.py runs/results/runs.csv --out results/
```

`results/summary.md` and the figures are generated from `runs.csv` only (means over seeds with 95% bootstrap CIs,
differences in absolute points). The full statistical report, including ablations, baselines, oracle gating and
calibration, is `REPORT.md` as written by the grader. Negative results are reported with the same prominence as
positive ones; the pre-registration predicts that rule induction shows no reliable recovery.

## Quick start

Requires Python ≥ 3.10. The core uses only the standard library.

```bash
make kit      # rebuild the study kit from the generator (byte-identical; writes kit/sealed/KEYS.json)
make test     # 134 tests, including a check that the rebuilt kit matches the pre-registered hashes
make mock     # offline end-to-end run: mock model → runner → grader
```

## Running the study

**Track A — in the Claude app (ecological).** Each run is an ordinary chat: attach the files listed for that run in
[`kit/RUNSHEET.md`](kit/RUNSHEET.md), send PART1–PART5 as files, save the answer JSON. Full instructions:
[`docs/RUNNING.md`](docs/RUNNING.md).

**Track B — through the API (scale).** The runner gives every model the same persistent Python tool, records full
transcripts and token cost, and attests provenance after each run.

```bash
cp runner/providers.example.json runner/providers.json   # fill model ids and prices; keys stay in env variables
chmod -R go-rwx kit/sealed
docker build -t amp-runner runner/
docker run --rm -e ANTHROPIC_API_KEY -v "$PWD:/amp" amp-runner \
    python /amp/runner/amp_runner.py --kit /amp/kit --runs /amp/runs --config /amp/runner/providers.json --tier P
python kit/grader/grade.py runs kit
```

`analysis/compare_tracks.py` measures agreement between the two tracks on shared seeds; `analysis/law.py` fits a
recovery curve across model pairs and refuses to call it a law with fewer than four pairs.

## Security model of the automated runner

Model-written code executes on the machine that runs Track B. The runner therefore:

- runs that code as a **separate, unprivileged OS user** with an environment built from scratch, so it cannot read
  the runner's process environment (where the API key lives), root-only files, or other runs;
- **probes before the first run** what that code could read, and refuses to start a real API run if the API key,
  the answer key, or other runs' files are readable;
- refuses a cross-check `verifier` that is itself one of the compared models, since that would feed one arm with
  the other arm's answers.

See [`SECURITY.md`](SECURITY.md).

## Threats to validity

Stated up front, with what the design does about each.

| threat | what the design does |
|---|---|
| **The library knows the benchmark.** The same author wrote the generator and the instruments, so `FULL` vs `PLAIN` mixes method with domain-specific tooling. | `BON5` and `CONF` receive the **same library**; `FULL` vs `BON5` isolates the protocol from the tools. The ARC anchor (`external/arc_anchor.py`) tests transfer to tasks the library was not written for, with an isomorph contamination audit. |
| **Self-verification is not independence.** | Same-model method pairs are marked `same_source` and cannot reach E3; self-written references are capped at E2; oracle claims that cannot be proven after the run are capped at E2 by the grader. |
| **Idea tasks repeat across seeds.** The four idea problems are fixed; hidden evaluation instances differ per seed. | Feedback is per model and from `FULL` runs only; the memory and outcome components are ablated (`noMEM`, `noOUT`) so their share of the effect is measured. |
| **Statistical power.** Ablation and baseline tiers use 10 seeds each. | The pilot produces a power table before the primary tier is graded; small component effects are reported as inconclusive, not as absent. |
| **Track A is run by hand.** | Run order is randomised and pre-registered; platform failures are the only allowed repeats; Track B replicates the cells without a human in the loop. |
| **Contamination.** | Instances are generated fresh per seed and the answer key is hashed before any run; the external anchor compares original vs isomorphic variants. |

## Repository layout

```
src/            protocol source (AMP_v6.src.md), amp_lab.py, benchmark generator, conditions, grader, statistics
kit/            the frozen study kit: PREREG.md, plan.csv, RUNSHEET.md, protocols/, tests/T1..T30/, grader/
                (kit/sealed/KEYS.json is not tracked; `make kit` regenerates it and the tests verify its hash)
runner/         Track B runner, sandbox, Dockerfile, provider configs
analysis/       gap-recovery curve, track concordance, figure generation
external/       ARC anchor and isomorph contamination audit
tests_code/     unit and regression tests
docs/           run guide, safety framing, mechanism simulations
```

The simulations in `docs/simulations/` use synthetic data: they demonstrate the mechanism and test the code; they
are not evidence about real models.

## Citation

See [`CITATION.cff`](CITATION.cff).

## License

Source-available for reading, evaluation and reproduction of the study; see [`LICENSE`](LICENSE).
