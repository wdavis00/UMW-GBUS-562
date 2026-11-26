# Example outputs: a confirmed session (synthetic scenario)

These are the two outputs the tool wrote at the end of one session that the user confirmed. They are byte-for-byte copies of what the tool produced, with nothing edited:

- [problem-framing-report.md](problem-framing-report.md) is the Human Problem-Framing Report. The Independent Review is its last section.
- [ai-handoff.md](ai-handoff.md) is the AI Portable State, also called the Follow-on AI Prompt. It contains no review content.

## Where they came from

- **Scenario:** a made-up nonprofit community music school whose director is considering hiring a part-time office manager. The person, the school and every detail are fictional. Claude invented the scenario and wrote the user's messages. No real person's information is involved.
- **Conversation:** the six-turn session first run interactively on 2026-11-25 (canonical log lines 70–75).
- **Run that produced these files:** 2026-11-26, at commit `975910d`, using `claude-opus-5-5` at medium effort. The tool's own end-of-session code built the frozen problem frame from that conversation and then ran the Independent Review. The two requests are canonical log lines 86 and 87.
- **Confirmation was simulated.** The script that ran the session supplied the answer "confirm". The tool did the rest exactly as it would for a person typing "confirm".
- **Product version:** the code and prompts that produced these files have not changed since `975910d`.

## How to use them

They show what the current tool produces. They are provisional showcase examples. A genuine session recorded for the final demo, on the final model, may replace them. They are not the course's unedited Example Run, which is a separate log line.
