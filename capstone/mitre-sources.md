# External MITRE Guidance

The tool's prompts use guidance from two MITRE Innovation Toolkit sources. The guidance text is not redistributed in this repository, and this project is not affiliated with or endorsed by MITRE.

## Sources

**1. Problem Framing (web page)**

- Source: MITRE Innovation Toolkit (ITK), Problem Framing
- Publisher: The MITRE Corporation
- Source URL: https://itk.mitre.org/toolkit-tools/problem-framing/
- Terms/License: the page links to no separate terms. Its footer states: "Material on this site is offered under a Creative Commons Attribution - Noncommercial-Share Alike license." No license version is given.
- Copyright/Attribution, from the page footer as saved on 2026-11-23: "Approved for Public Release; Distribution Unlimited Case #18-1663-5. Copyright © 2026 Innovation Toolkit - The MITRE Corporation. All Rights Reserved."

**2. Problem Framing Canvas V3 (PDF)**

- Source: Problem Framing Canvas V3, MITRE Innovation Toolkit
- Publisher: The MITRE Corporation
- Source URL: https://itk.mitre.org/wp-content/uploads/2021/01/Problem-Framing-Canvas-Color-Print.pdf
- Terms/License: the PDF gives no license or terms link.
- Copyright/Attribution, as printed on the PDF: "© 2020 The MITRE Corporation. All rights reserved. Approved for public release. Distribution unlimited PR_20-01469-4."

Check the current terms at the source before any use beyond running this tool for yourself.

## Files the tool needs

The tool reads two plain UTF-8 text files from a `Week8/Mitre` folder inside the folder that contains this repository (the same folder that holds the API key file):

- `Week8/Mitre/framer-guidance.txt`, used by the Framer
- `Week8/Mitre/reviewer-criteria.txt`, used by the Independent Review

Each file holds text taken word for word from the sources above, which the tool inserts unchanged into its prompts. Lines that start with `#` are notes and are ignored. If `framer-guidance.txt` is missing or empty, each turn stops with a clear error before any model call. If `reviewer-criteria.txt` is missing or empty, framing still works, but the report says the Independent Review could not be produced.

What each file contains:

- `framer-guidance.txt`:
  - the page's "How to use" Step 3 instruction;
  - the canvas's box questions on the problem and its symptoms, why it hasn't been solved, the assumptions and biases around it, who experiences it (when, where, and with what consequences), and who else does or does not have the problem;
  - Question Bank items 1, 3, 5, 7, and 9.
- `reviewer-criteria.txt`: the ten-item list of problem statements to avoid, with its lead-in sentence, as given on the canvas's Tool Tips page.
