---
name: init
description: Set up Conductor in the current project - builds the project map, writes module cards with cheap agents, creates config and a short CLAUDE.md note. Run once per project.
argument-hint: "[research|build|analytics]"
disable-model-invocation: true
---

# Initialise Conductor in this project

Shorthand: `CM` = `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/codemap.py"`.

1. Check Python works: run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" --version`. If it prints nothing or an error, tell the user (in Russian) to install Python 3.8+ or set the plugin option `python` (via `/plugin`), and stop.
2. Profile: use the argument if given; otherwise infer (code files → build; mostly .md/.pdf → research; .csv/.sql/.ipynb → analytics) and state your choice in one line.
3. Run `CM init`. It scans without any model, writes `.conductor/map.json`, `.conductor/MAP.md`, card stubs, and `.conductor/config.json`. Set `"profile"` in the config.
4. Read `.conductor/MAP.md`. If modules are grouped badly (one giant module, or dozens of tiny ones), propose `codemap.modules` globs in the config, apply them, rerun `CM init`.
5. Write cards: send `conductor:cartographer` (haiku) the module ids in batches of ~5, up to 3 agents in parallel. Skip vendored/generated modules.
6. Add to `.gitignore` (create if missing): `.conductor/usage/` and `.conductor/runs/*/evidence/`. Keep `MAP.md`, `map.json`, `cards/`, `config.json` in git so the map travels with the repo.
7. Append to the project `CLAUDE.md` (create if missing) exactly this short block, unless it is already there:
```
## Conductor
Project map: .conductor/MAP.md (auto-maintained). Read module cards in .conductor/cards/ only for modules a task touches; do not scan the whole repo. Use /conductor:conduct for multi-step tasks.
```
8. Report in Russian: number of files and modules, cards written, and the two commands the user will use most (`/conductor:conduct <задача>`, `/conductor:tokens`).
