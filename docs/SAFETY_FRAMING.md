# Framing for an evaluations / safety audience

## The question, restated
**How much of the next model generation's capability can be elicited from the current model by a cheap,
portable, text-only scaffold, with no weight change? And does the scaffold make the model more honest about
what it does not know?**

This matters to capability evaluations for one reason. An evaluation that does not elicit the model's best
performance underestimates what the model can do. If a one-file scaffold that anyone can attach recovers a
measurable share of a generation gap, then plain-prompt evaluation numbers carry a known downward bias of that
size.

## What is measured (all from `grade.py` / `law.py`)

| quantity | definition | why an evaluator cares |
|---|---|---|
| **Elicitation gap recovered, R** | (FULL@weak − PLAIN@weak) / (PLAIN@strong − PLAIN@weak), seed-bootstrap CI | the share of a generation's improvement that was latent in the weaker model and reachable by method |
| **Recovery curve** | R against gap size across ≥ 4 model pairs, slope with CI | whether the latent share is stable, or shrinks as gaps grow |
| **Cost to elicit** | cost(FULL@weak) / cost(PLAIN@strong) | how cheap the latent capability is to reach |
| **Silent-error rate** | share of items answered wrong with stated p ≥ 0.9 | overconfident wrong answers: the failure mode that misleads users and evaluators |
| **Calibration** | Brier score; accuracy by derived evidence level | whether stated confidence can be trusted |
| **Component attribution** | ablations (10 components) and matched baselines incl. closest prior art | which part of the scaffold carries the effect |
| **Contamination audit** | external set: original vs isomorph accuracy; own set: fresh instances, keys hashed before runs | the result is not memorisation |

## The two findings this design can produce
1. **Elicitation headroom.** A number with a CI for how far plain evaluation understates capability on checkable
   reasoning, and where it does *not* (pre-registered: rule induction, taste).
2. **Honesty under verification.** Agreement between checks that can fail together is a main source of confident
   errors. The attested-independence mechanism derives confidence from what was actually executed. Its effect on
   silent errors is measured directly (FULL vs noATT, FULL vs CONF).

## Scope of the superiority claim (stated plainly)
The weaker model with the scaffold closes or crosses the gap to the **plain** stronger model on oracle-rich tasks.
It is **not** claimed to beat the stronger model when that model also runs the scaffold: give both the same external
oracle and the stronger priors still win (the FULL@55 cell measures exactly this, and the simulation shows the same).
The value is elicitation — how much of the next generation is already reachable in this one — not a universal ranking.

## Responsible framing
- Report negative results as prominently as positive ones.
- The scaffold raises capability on checkable tasks. That is the point for elicitation, and it is also a reason
  to publish the measurement, so evaluators can account for it.
- No dangerous-capability domains are used in the benchmark.
