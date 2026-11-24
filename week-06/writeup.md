## What I Built

I built the first version (V1) of my capstone, a problem-framing tool that helps one person turn a concern, opportunity, idea, or proposed solution into a tentative, solution-neutral problem frame. It is a small team with two roles. A Framer reflects what the user said, keeps stated information, assumptions, unknowns, and any proposed solution apart, drafts a problem statement when there is enough information, and asks one next question. When there is a draft, an independent Reviewer checks it against MITRE's ten-item problem-statement guidance and gives advice without rewriting it. Only the user can confirm the frame.

My evaluation set has nine cases: two Typical, five Edge case, one Should refuse, and one Guardrail. I settled the cases, their expected behavior, and the judgment questions before V1 was built. The evaluation program, capstone_evaluate.py, runs every case through V1 once. Code checks come first: the result's structure, the case's own checks, and, for the Guardrail case, the rules for quantities. Only if those pass does it show me the result and ask that case's two fixed yes/no questions. The Guardrail case, T9, is decided by code alone.

The guardrail is in capstone/guardrail.py. It enforces one rule: a quantity must not be shown with more certainty than its evidence supports.

## Why This Approach

Tool tested: Capstone, the V1 problem-framing tool in the capstone folder.

Guardrail: Output. After the Framer's result passes its structural checks and before the Reviewer runs, code checks that every quantity it finds in the stated facts and the draft problem statement was supplied by the user or properly declared as derived from the user's own quantities. If one was not, the framing is held: the status becomes not_ready, the draft is cleared, the Reviewer does not run, the user is told which amount was held and why, and the user decides whether to give evidence, mark it as provisional, or leave it unknown.

I chose this rule because an invented number in a problem statement can look like a fact, and an explicit unknown is better than manufactured completeness. Quantities are also something code can check. Whether a problem statement is truly solution-neutral or faithful to what the user meant needs judgment, so I kept those as fixed questions for a person instead of phrase checks.

The only changes between the two evaluations were the guardrail and its connection to V1. The test cases, the evaluation program, both role prompts, the model (claude-opus-5-5), and the effort setting (medium) stayed the same. Before eval-1, I made one round of three narrow prompt fixes based on smoke tests that did not use any of the nine cases.

The guardrail did not trip during eval-2, so it did not cause the higher score. T9 also passed in eval-1. T5 failed in eval-1 because the Reviewer said the day-shift observation replaced the user's original belief about the night shift. In eval-2 the Reviewer did not say that and I judged it a pass, but nothing was changed to fix it, so I treat the difference as variation between runs. The guardrail's hold behavior was tested separately with made-up Framer results.

The guardrail has limits. It compares number values, not their meaning or units, it does not check arithmetic, and it checks only the stated facts and the draft problem statement.

The MITRE guidance comes from the MITRE Innovation Toolkit's Problem Framing tool (https://itk.mitre.org/toolkit-tools/problem-framing/). It is licensed separately, so its text is kept outside this repository and V1 reads it at run time. It is short enough to give the model directly, so V1 does not use RAG.

## Example Run

```text
T1 PASS
T2 PASS
T3 PASS
T4 PASS
T5 PASS
T6 PASS
T7 PASS
T8 PASS
T9 PASS
Passed: 9 of 9
```

## Reflection

First evaluation: 8 of 9

After the guardrail: 9 of 9

Next fix: None. I would add a case with an already strong, well-developed problem statement to test whether the Reviewer recognizes when little or no additional feedback would add value instead of generating unnecessary recommendations.
