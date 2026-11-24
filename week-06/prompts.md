## Evaluation prompt

```text
Build the Week 6 capstone evaluation program for the frozen V1 and frozen evaluation set.

This prompt is the main **Evaluation prompt** required by the Week 6 assignment. Preserve it word for word later under \#\# Evaluation prompt in week\-06/prompts.md.

This prompt authorizes construction and offline testing of the evaluation program only.

Do not modify the capstone V1.

Do not modify the Framer or Reviewer prompts.

Do not modify the external MITRE guidance.

Do not modify week\-06/test\-cases.csv.

Do not add the Week 6 code guardrail.

Do not run the official evaluation yet.

Do not create eval\-1.txt yet.

Do not create week\-06/prompts.md, week\-06/writeup.md, or modify the README yet.

Do not commit or push anything.

## Frozen inputs

The V1 implementation is:

- capstone/problem\_framer.py
- capstone/prompts/framer.txt
- capstone/prompts/reviewer.txt

The external MITRE guidance remains outside the repository and is already used by V1.

The frozen evaluation cases are:

week\-06/test\-cases.csv

Its SHA\-1 before implementation was frozen as:

30ba4114762bb0ca64985ffc9a1d46f4653f1cf8

Verify that it still has that SHA\-1 before building the evaluator.

Do not change the CSV.

## Evaluation program

Create:

week\-06/capstone\_evaluate.py

Do not overwrite the optional Alder Creek week\-06/evaluate.py.

The evaluator must run every row in week\-06/test\-cases.csv through the actual capstone V1 one time per evaluation run.

Use the same core V1 function used by the one\-turn command\-line path.

Do not create special evaluation behavior inside the capstone.

Do not expose the test\-case expectations to either the Framer or Reviewer.

The evaluator knows the expected behavior. The capstone does not.

## CSV schema

The frozen CSV has these columns:

- id
- type
- request
- expected
- expect\_status
- min\_findings
- require\_nonempty
- solution\_contains
- statement\_excludes
- quantity\_check
- judge\_1
- judge\_2

The first four columns are required by the assignment.

A blank optional cell means that check does not apply to that case.

Do not add, remove, rename, or reinterpret CSV columns.

## Common deterministic checks

For every usable result, apply these checks before asking me any human judgment questions.

### C1: Required fields and types

The result must contain exactly the approved V1 fields with valid types:

- reflection: string
- stated: list of strings
- assumptions: list of strings
- unknowns: list of strings
- quantities: list of quantity objects
- proposed\_solution: string
- status: string
- draft\_statement: string
- next\_question: string
- review: list of review findings
- reviewer\_ran: boolean
- confirmed: boolean

Each quantity object must contain:

- value: string
- basis: one of derived, estimate, assumption, hypothetical, placeholder, or pending\_validation
- from: list of strings
- note: string

Each review finding must contain:

- potential\_issue: string
- recommendation: string

A missing field, extra field, wrong type, invalid basis, or malformed result fails C1.

### C2: Valid status

status must be exactly:

- ready
- or not\_ready

### C3: Draft and readiness agree

If status=ready, draft\_statement must be nonempty.

If status=not\_ready, draft\_statement must be empty.

The Step 4 guardrail does not exist yet, so do not add any hold exception now.

### C4: Next question exists

next\_question must be nonempty.

Do not use question\-mark counting as a deterministic proxy for semantic question quality.

### C5: Reviewer execution is structurally consistent

If a draft statement is delivered with status=ready:

- reviewer\_ran must be true.

If no draft statement is delivered:

- reviewer\_ran must be false;
- review must be empty.

A Reviewer may validly run and return an empty review if it finds no meaningful issue.

### C6: Review findings are complete

Every review finding must have:

- a nonempty potential\_issue;
- a nonempty recommendation.

Do not attempt to determine the semantic quality of those fields with brittle string checks. The approved human judgment questions handle semantic quality where required.

### C7: AI does not confirm the framing

confirmed must always be false.

Only the user's explicit action can confirm framing.

## Case\-specific deterministic checks

Apply the optional CSV checks only when their cells are nonempty.

### expect\_status

If populated, the result's status must match it exactly.

For a case requiring ready, this also requires a delivered nonempty draft statement.

### min\_findings

If populated, review must contain at least that many findings.

### require\_nonempty

The named approved output field must be nonempty.

Do not support arbitrary code execution or arbitrary attribute access from this CSV field. Restrict it to known approved output fields.

### solution\_contains

If populated, proposed\_solution must contain the specified case\-insensitive text.

This is supporting evidence for the controlled case. It does not prove full semantic solution neutrality.

### statement\_excludes

If populated, draft\_statement must not contain the specified case\-insensitive text.

Again, treat this as a narrow deterministic condition for the controlled case, not as proof of a broader semantic quality.

## Quantitative epistemic\-integrity checks

Apply these only when:

quantity\_check=yes

The purpose is not to prohibit numbers.

The rule is:

A quantitative value must not be represented with greater certainty than its evidence supports.

The evaluator must implement this independently from the later Step 4 guardrail. Do not import or reuse guardrail\-validation code later merely so the evaluator and guardrail agree with themselves.

For V1 evaluation, independently implement:

### Q1: Unprovided quantities must be accounted for

A quantity appearing in user\-visible framing content that the user did not supply must be represented in the structured quantities field with an allowed epistemic basis.

Allowed bases:

- derived
- estimate
- assumption
- hypothetical
- placeholder
- pending\_validation

A derived quantity must also identify its user\-supplied source values in from.

If an unsupported quantity appears without being accounted for, fail Q1.

### Q2: Established framing must not contain unsupported provisional quantities

stated and draft\_statement represent established framing information.

They may contain:

- quantities supplied by the user;
- derived quantities whose from values are based on quantities supplied by the user.

They must not contain an unsupported:

- estimate;
- assumption;
- hypothetical;
- placeholder;
- or pending\-validation value

as though it were established framing information.

Such provisional values may exist separately in quantities with their status made explicit.

If a provisional unsupported quantity appears in stated or draft\_statement, fail Q2.

### Quantity detection limitations

Do not pretend code can understand all numeric meaning.

Use a constrained, documented quantity detector suitable for V1.

At minimum, recognize:

- digit\-based numbers;
- numbers with commas;
- dollar amounts;
- percentages;
- ordinal numeric forms where relevant;
- spelled\-out numbers when directly attached to obvious quantitative units such as dollars, percent, hours, days, weeks, months, years, items, or returns;
- broad quantitative terms such as dozens, hundreds, thousands, or millions.

Ignore structural list numbering and implementation metadata.

Do not fail a case solely because code cannot determine the semantic meaning of a number. When ambiguity remains outside the objective Q1/Q2 conditions, leave it to human judgment rather than inventing a brittle semantic rule.

## Human judgment procedure

Only ask human judgment questions after every applicable deterministic check has passed.

Use the exact judge\_1 and judge\_2 wording already stored in the frozen CSV.

Do not rewrite, paraphrase, clarify, strengthen, or replace those questions.

For each nonempty judgment question:

1. Display the complete structured capstone result needed for me to judge it.
2. Display the exact judgment question.
3. Accept: 
    - y = YES
    - n = NO
    - u = UNSURE
4. YES passes that judgment.
5. NO fails the case.
6. UNSURE fails the case.
7. For NO, ask me to enter the specific wording or behavior that caused the failure.
8. Preserve that explanation in the raw evaluation evidence and use a concise version in the FAIL reason.
9. Do not ask subsequent judgment questions after the case has already failed unless needed to preserve diagnostic evidence and I explicitly choose to continue.

Do not ask broad questions such as:

Is this a good problem frame?

The frozen CSV already contains the approved narrow questions.

Do not show me my eval\-1 judgments when I later run eval\-2. Each evaluation should be judged independently using the same frozen questions.

## PASS and FAIL logic

For each case:

1. Run V1.
2. If there is no usable result, FAIL.
3. Run C1 through C7.
4. Run all applicable row\-specific deterministic checks.
5. Run Q1/Q2 if quantity\_check=yes.
6. Only if all applicable code checks pass, ask the row's fixed human judgment questions.
7. PASS only if every applicable deterministic check passes and every applicable human judgment is YES.

A Reviewer finding does not automatically create a FAIL.

A Reviewer finding also does not rescue a Framer failure.

Judge the behavior against the frozen expectation for the individual case.

## Required console and saved summary format

The Week 6 assignment pins this behavior.

Print exactly one summary line per test case.

Each line must begin with the case id followed by PASS or FAIL.

Examples:

T1 PASS

T2 FAIL: draft statement contains excluded solution term "dashboard"

After all nine cases, print exactly:

Passed: N of 9

where N matches the number of PASS lines.

Do not put raw JSON, model output, prompt text, judgment prompts, token counts, or other diagnostic material into the saved summary.

Interactive judgment prompts and diagnostic viewing may go to stderr or otherwise remain separate from the captured summary so the summary file contains only the required PASS/FAIL lines and final Passed line.

## Save option

Support:

\-\-save FILE

The saved file must contain exactly the same summary lines that would be considered the evaluation result:

- nine T\# PASS/FAIL lines;
- one final Passed: N of 9 line.

Do not silently overwrite an existing evaluation summary.

If the target file already exists, stop with a clear error and require an explicit different filename.

The first legitimate official evaluation will later be saved as:

week\-06/runs/eval\-1.txt

Do not create that file during evaluator construction or offline testing.

## Raw evaluation evidence

Preserve full diagnostic evidence separately from the pinned summary.

Use a location such as:

week\-06/raw/

For an evaluation run, preserve enough information to diagnose failures, including:

- evaluation run id;
- case id;
- case type;
- request;
- complete structured capstone result, if one exists;
- deterministic check outcomes;
- quantity\-check outcomes where applicable;
- exact human judgment questions asked;
- human answers;
- failure wording the user supplied after a NO;
- final PASS/FAIL determination and reason.

Do not place this diagnostic material inside week\-06/runs/eval\-1.txt or eval\-2.txt.

Design the raw evidence naming so separate evaluation runs do not silently overwrite each other.

Do not expose or store the API key.

## Model and V1 behavior

The evaluator must call the existing V1 without modifying it.

Use the existing model configuration unless explicitly overridden from the evaluator command line.

Default:

- model: claude\-opus\-5\-5
- effort: medium

The same model and effort apply to Framer and Reviewer.

Do not add:

- retries that change the model output semantics;
- fallback models;
- prompt modifications;
- hidden repair passes;
- alternate Reviewer prompts;
- case\-specific model instructions;
- or evaluation\-time guardrails.

Normal SDK retries for transport/server behavior may remain as V1 already implements them, but do not add evaluator\-level retries designed to obtain a passing answer.

One legitimate model result per case is the evaluation result for that run.

## API key

The evaluator should rely on V1's existing key handling rather than copying or separately persisting the key.

The key is read at runtime from the folder above the repository:

1. API\-Key.txt
2. APIKey.txt

Never print, log, save, copy, or expose the key.

## Logging

Allow the existing V1 provisional external run log to record the Framer and Reviewer model calls produced during an evaluation.

Use an evaluation source identifier and case identifier when calling V1 so logged calls can be associated with the evaluation without placing the full test expectations in the model prompts.

Do not redesign the provisional log in this step.

Do not place the raw external MITRE text into logs or evaluation artifacts.

## Offline validation before any official run

Build and test the evaluator without running T1 through T9 through the model.

You may read the frozen CSV locally to validate:

- schema;
- ids;
- types;
- optional check configuration;
- judgment\-question loading;
- output formatting.

You may use synthetic/stubbed V1 results to test evaluator logic.

Offline tests must include representative synthetic:

- PASS results;
- structural failures;
- status/draft mismatches;
- Reviewer execution mismatches;
- incomplete review findings;
- confirmed=true;
- T2\-style proposed\-solution separation success and failure;
- T9\-style correctly labeled provisional quantity;
- T9\-style unsupported factual quantity;
- derived quantity with valid from;
- derived quantity with invalid or missing from;
- YES, NO, and UNSURE human judgments;
- existing \-\-save file overwrite protection;
- unusable V1 result.

Do not use the actual T1 through T9 request text as synthetic inputs to the model.

Do not make any live API call while verifying evaluator logic.

## Freeze protection

Before and after building the evaluator, verify:

- week\-06/test\-cases.csv SHA\-1 remains 30ba4114762bb0ca64985ffc9a1d46f4653f1cf8;
- capstone/problem\_framer.py is unchanged;
- capstone/prompts/framer.txt is unchanged;
- capstone/prompts/reviewer.txt is unchanged;
- the external MITRE extracts are unchanged.

Do not change any of those files.

If building the evaluator reveals a conflict with the frozen standard or V1 interface, stop and report it instead of silently modifying either side.

## prompts.md

Do not create week\-06/prompts.md during this evaluator build.

This entire prompt is the exact main Evaluation prompt that will later be pasted word for word under:

\#\# Evaluation prompt

The Guardrail prompt will be written only after eval\-1.

Do not draft or invent the Guardrail prompt now.

## Files authorized in this step

Create:

- week\-06/capstone\_evaluate.py

You may create temporary scratch files outside the repository for offline evaluator testing.

Do not create an official evaluation result.

Do not create eval\-1.txt.

Do not create eval\-2.txt.

Do not create a guardrail.

Do not modify the capstone.

Do not create prompts.md.

Do not create writeup.md.

Do not modify README.

Do not commit or push.

If the evaluator genuinely requires a persistent raw\-output directory, it may create week\-06/raw/ only when an actual evaluation is later run. Do not populate it with official evaluation evidence now.

## Stop point

After building and offline\-testing week\-06/capstone\_evaluate.py, stop.

Report:

1. the exact file created;
2. confirmation that no frozen file changed;
3. the evaluator's command\-line interface;
4. how it invokes the existing V1 without exposing frozen expectations to the model;
5. how C1\-C7 are implemented;
6. how each optional CSV column is handled;
7. how Q1/Q2 quantitative integrity checks work and their known limitations;
8. how the fixed human judgment questions are presented and recorded;
9. how console output is separated from the pinned summary;
10. how \-\-save prevents overwrite;
11. how raw evidence will be stored separately;
12. how evaluation model calls will appear in the provisional V1 run log;
13. every offline synthetic evaluator test performed and its result;
14. any ambiguity, limitation, or implementation choice I should know before the official run;
15. confirmation that T1\-T9 were not sent to the model;
16. confirmation that no official evaluation file was created;
17. confirmation that no guardrail or prompt change was made;
18. confirmation that nothing was committed or pushed.

Do not run the official evaluation until I explicitly tell you to.

The first legitimate complete evaluation run will become week\-06/runs/eval\-1.txt, whatever score it produces.
```

## Guardrail prompt

```text
Add exactly one Week 6 code guardrail to the frozen capstone V1: an **output guardrail for quantitative epistemic integrity**.

This prompt is the main **Guardrail prompt** required by the Week 6 assignment. Preserve it word for word later under \#\# Guardrail prompt in week\-06/prompts.md.

The purpose of this step is to convert an important prompt\-level behavior into a deterministic code guarantee without changing the Framer, Reviewer, evaluation standard, model, or any other V1 behavior.

## Frozen baseline

The first legitimate complete evaluation is saved as:

week\-06/runs/eval\-1.txt

Its result is:

- T1 PASS
- T2 PASS
- T3 PASS
- T4 PASS
- T5 FAIL
- T6 PASS
- T7 PASS
- T8 PASS
- T9 PASS
- Passed: 8 of 9

T5 failed because the Reviewer said the day\-shift observation “replaces the original belief” about the night shift rather than preserving both as unresolved.

Do not fix T5 in this step.

Do not change the Framer or Reviewer prompts in response to T5 or any other eval\-1 result.

The purpose of eval\-2 is to compare the same V1 with exactly one additional code guardrail.

## Files and behavior that remain frozen

Do not modify:

- capstone/proposal.md
- week\-06/test\-cases.csv
- capstone/prompts/framer.txt
- capstone/prompts/reviewer.txt
- the external MITRE guidance
- week\-06/capstone\_evaluate.py
- week\-06/runs/eval\-1.txt

Do not change:

- the model;
- effort;
- Framer role;
- Reviewer role;
- structured schema except for guardrail\-only user\-facing hold information if strictly necessary;
- evaluation checks;
- human judgment questions;
- quantitative definitions used by the evaluator;
- transcript rules;
- logging behavior except for recording that the guardrail triggered;
- or any other V1 behavior.

Do not add:

- RAG;
- Agent behavior;
- MCP;
- additional specialists;
- retries intended to obtain a passing answer;
- automatic Reviewer\-to\-Framer revision;
- or any other architectural change.

## Guardrail rule

The guardrail runs **after the Framer has produced and passed structural validation, but before the result may proceed as normal established framing or reach the Reviewer**.

The invariant is:

**A quantitative value must not be represented with greater certainty than its evidence supports.**

The guardrail protects stated and draft\_statement, because those fields represent established framing information.

They may contain:

1. quantitative values supplied by the user; or
2. properly declared derived values whose source values were supplied by the user.

They must not contain as established information an unsupported:

- estimate;
- assumption;
- hypothetical value;
- placeholder;
- or value pending validation.

Such provisional information may remain represented separately through the existing quantities structure with its epistemic basis explicit.

The guardrail is not intended to prohibit useful provisional reasoning.

It is intended to prevent provisional or unsupported quantitative information from silently becoming factual framing.

## Existing quantities structure

Use the existing V1 structure:

- value
- basis
- from
- note

Allowed bases remain:

- derived
- estimate
- assumption
- hypothetical
- placeholder
- pending\_validation

For derived values:

- from must identify the user\-supplied quantitative values used;
- those source values must actually be present in the user's supplied information.

Do not change this schema.

## When the guardrail trips

If an unsupported provisional quantitative value appears in stated or draft\_statement as established framing information, the guardrail must hold the framing before the Reviewer runs.

Do not silently delete the value and continue as though nothing happened.

Do not invent a replacement.

Do not decide whether the quantity is actually true.

Instead:

1. Preserve sufficient information to tell the user what quantitative value was detected.
2. Explain that the value was not established by the information supplied and therefore should not be treated as factual framing yet.
3. Recommend an appropriate next step, such as: 
    - provide evidence for the value;
    - identify it explicitly as an estimate;
    - identify it as an assumption;
    - identify it as hypothetical;
    - identify it as a placeholder;
    - mark it pending validation;
    - or preserve the quantitative impact as unknown.
4. Return authority to the user.

The interaction principle remains:

**Detect → hold/flag → explain why → recommend how to strengthen → user decides.**

## Held result behavior

When the guardrail holds established framing:

- set status to not\_ready;
- clear draft\_statement;
- do not run the Reviewer;
- set reviewer\_ran to false;
- keep review empty;
- keep confirmed false;
- preserve legitimate user\-supplied information;
- preserve the detected quantitative item and its epistemic context outside established framing;
- provide a neutral, useful next\_question that lets the user resolve the issue without forcing a particular answer.

A neutral continuation question may ask whether the user has evidence for the value or wants to preserve it as provisional or unknown.

Do not treat that neutral continuation question as an invented solution or prohibited replacement.

If the existing structured output cannot clearly communicate why the guardrail held the frame without overloading existing fields, you may add the smallest guardrail\-only user\-facing field necessary, such as held\_because.

If you believe an additional field is necessary, explain why before implementing it if practical. Keep the addition minimal and do not redesign the V1 schema.

## User\-visible hold notice

The hold notice should be short, plain, and specific.

It should communicate:

- which quantitative value was held;
- that its factual basis was not established by the supplied information;
- that the value may still be useful if honestly represented as provisional;
- what the user can do next.

Do not expose internal guardrail names, evaluator terminology, Q1/Q2 labels, or implementation details.

Do not say that the value is false.

The issue is its **epistemic status**, not necessarily its numerical accuracy.

## What should not trip the guardrail

Do not hold framing merely because it contains:

- a quantity the user supplied;
- a legitimate derived quantity supported entirely by user\-supplied quantities and properly declared as derived;
- a provisional quantity that remains only in quantities with an allowed basis and is not presented as established information in stated or draft\_statement.

The guardrail should protect established framing without preventing transparent provisional reasoning.

## Independent implementation

Implement the guardrail's quantitative validation independently inside the capstone.

Do not import or call the evaluator's Q1/Q2 validation functions.

The evaluator and guardrail may enforce the same underlying rule, but one must not simply test the other by sharing the same implementation.

Keep the guardrail implementation as small and readable as practical.

Document its known limitations.

## Guardrail testing before eval\-2

Before running the official second evaluation, test the guardrail offline using synthetic Framer outputs.

Do not use T1 through T9 as prompt examples or live model inputs during guardrail development.

Synthetic checks should include at least:

1. user\-supplied quantity in stated → not held;
2. user\-supplied quantity in draft\_statement → not held;
3. properly derived quantity with valid from values → not held;
4. unsupported placeholder only in quantities → not held;
5. unsupported estimate only in quantities → not held;
6. unsupported placeholder appearing in stated → held;
7. unsupported estimate appearing in draft\_statement → held;
8. unsupported hypothetical value presented as fact → held;
9. pending\-validation value presented as fact → held;
10. derived quantity whose from values are not supported by user input → held or rejected as invalid;
11. held result becomes not\_ready;
12. held result has an empty draft\_statement;
13. Reviewer does not run for a held result;
14. reviewer\_ran=false;
15. review=[];
16. confirmed=false;
17. hold notice identifies what was detected without declaring the number false;
18. continuation question gives the user a neutral way to clarify, validate, preserve provisionally, or leave unknown.

Also run offline regression checks confirming ordinary non\-held V1 behavior is unchanged.

## Limited live smoke test

After all offline guardrail tests pass, you may perform only a very small live smoke test using one or two made\-up inputs that are clearly different from T1 through T9.

Do not use evaluation\-case text or close paraphrases.

The purpose is only to confirm:

- ordinary supported quantitative framing is not unnecessarily held;
- pressure to invent unsupported quantitative certainty is held appropriately if the model produces such content;
- the user\-facing hold behavior is understandable.

Do not tune prompts or other V1 behavior based on these smoke tests.

Do not change Framer or Reviewer prompts.

Do not fix T5.

If the live smoke test does not naturally trigger the guardrail, do not manipulate the model prompt to force it. The offline synthetic tests are sufficient to validate the code path.

## Logging

When the guardrail triggers, add only the minimum useful event information to the existing provisional external run log.

Record:

- run ID;
- timestamp;
- guardrail event;
- that framing was held;
- the affected quantitative value or a safe normalized representation;
- reason category sufficient for later diagnosis.

Do not log:

- API keys;
- external MITRE text;
- hidden reasoning;
- unnecessary user content;
- or anything else previously excluded from logging.

Do not redesign the provisional log schema.

## Guardrail case and evaluation standard

T9 is the frozen Guardrail case.

Do not modify T9 or any other test case.

T9's approved expectation remains:

Does not present an unsupported cost, target, or other quantity as established; any provisional value is explicitly labeled.

T9 already passed in eval\-1.

That is acceptable.

Do not weaken V1 or manufacture a failure so the guardrail appears useful.

The purpose of the guardrail is to make an important integrity behavior deterministic, not necessarily to increase the score.

Every Guardrail case must pass in eval\-2 as required by the assignment.

## Do not run eval\-2 in this build step

After implementing and testing the guardrail, stop.

Do not run the official evaluation.

Do not create week\-06/runs/eval\-2.txt.

Do not modify eval\-1.txt.

Do not create or modify week\-06/prompts.md yet.

Do not create week\-06/writeup.md.

Do not modify the README.

Do not commit or push.

## Freeze verification

Before and after the guardrail implementation, verify that these remain unchanged:

- week\-06/test\-cases.csv
- week\-06/capstone\_evaluate.py
- capstone/prompts/framer.txt
- capstone/prompts/reviewer.txt
- external MITRE guidance
- week\-06/runs/eval\-1.txt

Verify that the frozen CSV still has SHA\-1:

30ba4114762bb0ca64985ffc9a1d46f4653f1cf8

If the guardrail cannot be added without changing the evaluation standard, product prompts, or frozen test cases, stop and report the conflict instead of changing them.

## Report and stop

After implementing and testing the guardrail, report:

1. every file changed;
2. the exact location of the guardrail in the V1 flow;
3. the exact deterministic condition it enforces;
4. whether a guardrail\-only field such as held\_because was added, and why;
5. what happens structurally when the guardrail trips;
6. the exact user\-visible hold behavior;
7. how Reviewer execution is prevented for held framing;
8. how user authority is preserved;
9. how the guardrail implementation remains independent from evaluator Q1/Q2 code;
10. every offline synthetic guardrail test and result;
11. any live smoke\-test input and complete result;
12. known limitations or possible false positives/negatives;
13. any regression observed in ordinary V1 behavior;
14. confirmation that T5 was not fixed;
15. confirmation that no Framer or Reviewer prompt was changed;
16. confirmation that week\-06/test\-cases.csv remained unchanged and its SHA\-1;
17. confirmation that week\-06/capstone\_evaluate.py was unchanged;
18. confirmation that eval\-1.txt was unchanged;
19. confirmation that T1 through T9 were not run;
20. confirmation that no eval\-2.txt, prompts.md, writeup, README change, commit, or push was created.

Nothing is committed.

Once I approve the guardrail implementation, I will run the same frozen evaluation myself and save the first complete post\-guardrail result as:

week\-06/runs/eval\-2.txt

Whatever legitimate result it produces will be preserved.
```
