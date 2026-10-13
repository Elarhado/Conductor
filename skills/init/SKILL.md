---
name: init
description: Optional deep setup of Conductor in a project - writes all module cards up front with cheap agents and adds a short CLAUDE.md note. Not required; /conductor:conduct connects any project automatically on first use.
argument-hint: "[research|build|analytics]"
disable-model-invocation: true
---

# Deep setup (optional)

`/conductor:conduct` already connects a project on first use (map + config, cards filled lazily). Use this command only when the user wants every module card written now, or a CLAUDE.md note so plain chats without the command also follow the map.

Shorthand: `CM` = `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/codemap.py"`.

1. Check Python works: run `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" --version`. If it prints nothing or an error, tell the user (in Russian) to install Python 3.8+ or set the plugin option `python` (via `/plugin`), and stop.
2. Profile: use the argument if given; otherwise infer (code files → build; mostly .md/.pdf → research; .csv/.sql/.ipynb → analytics) and state your choice in one line.
3. Run `CM ensure` (connects the project if needed, otherwise syncs). Set `"profile"` in `.conductor/config.json`.
4. Read `.conductor/MAP.md`. If modules are grouped badly (one giant module, or dozens of tiny ones), propose `codemap.modules` globs in the config, apply them, rerun `CM init`.
5. Write cards: send `conductor:cartographer` (haiku) the module ids in batches of ~5, up to 3 agents in parallel. Skip vendored/generated modules.
6. Nothing to add to the project's `.gitignore`: `.conductor/.gitignore` already excludes bulky run data while map, cards and config stay in git.
7. Append to the project `CLAUDE.md` (create if missing) exactly this short block, unless it is already there:
```
## Conductor
Project map: .conductor/MAP.md (auto-maintained). Read module cards in .conductor/cards/ only for modules a task touches; do not scan the whole repo. Use /conductor:conduct for multi-step tasks.
```
8. Report in Russian: number of files and modules, cards written, and the two commands the user will use most (`/conductor:conduct <задача>`, `/conductor:tokens`).
