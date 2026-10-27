# CLAUDE.md

Guidance for Claude Code when working in this repository.

## Project context

- This repo holds coursework for **GBUS 562: AI Language Models** (University of Mary Washington, MS in AI in Business). The focus is building software tools that use Large Language Models.
- The repo already contains work from previous weeks. Content is organized into one folder per week (`week-01/`, `week-02/`, ...), and each week's work is listed in the "Weekly Work" section of `README.md`.
  - `week-01/connect4.html`: single-page Connect Four game (HTML/CSS/JS) with a minimax/alpha-beta computer opponent and a two-player mode.
- When adding a new week's work, create the matching `week-NN/` folder and update the "Weekly Work" section of `README.md`.
- GitHub remote: `https://github.com/wdavis00/UMW-GBUS-562` (public-facing; treat everything committed as published).

## Anthropic API key — SECURITY RULES (always follow)

- The Anthropic API key lives in `../APIKey.txt`, i.e. the parent folder **outside** this repo:
  `/Users/wdavis/Library/CloudStorage/OneDrive-Personal/School/UMW-MS in AI in Business/GBUS-562/APIKey.txt`
- Use this key whenever we build something that connects to Claude.
- **NEVER publish the key to GitHub or anywhere else.** Specifically:
  - Never copy `APIKey.txt` into the repo, and never hard-code the key in source files, notebooks, HTML/JS, config files, comments, READMEs, commit messages, or PR descriptions.
  - Code must read the key at runtime — from the `ANTHROPIC_API_KEY` environment variable, or by reading `../APIKey.txt` (resolved relative to the repo) — never embed its value.
  - Never print or log the key (or display it in tool output); if a debug check is needed, only confirm that it loaded (e.g. its length or first few characters).
  - Browser-only apps (plain HTML/JS) must not contain the key, since anything shipped to the browser is public. Use a small local backend (e.g. Python) that reads the key and calls the API.
  - Before every commit, check the staged diff (`git diff --cached`) for anything resembling a key (`sk-ant-...`). If found, stop and remove it before committing.
  - `.gitignore` excludes `APIKey.txt`, `*.key`, and `.env` as a safety net — keep those entries.

## Building with Claude

- Use the official Anthropic SDK (`anthropic` for Python) and default to the latest, most capable Claude models unless the assignment calls for something else.
