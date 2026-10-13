---
name: tokens
description: Show where tokens went in this project - per model and per agent, with the share handled by cheap workers. Use when the user asks about usage, limits, cost or delegation efficiency.
argument-hint: "[days]"
---

Run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/usage.py" report --days <N>` (default 7; use the argument if given).

Show the table to the user as is, then in Russian, at most 5 lines:
- which model/agent consumed the most and whether that matches the intent (Opus for decisions, Haiku/Sonnet for volume);
- the delegated share and one concrete suggestion if the main model did volume work (e.g. reading long files itself, web searching itself, re-reading the repo);
- note that "est. $" is an estimate from list prices, useful for comparing shares, not an exact plan-limit meter; exact remaining limits are in Claude Code's `/usage`.
