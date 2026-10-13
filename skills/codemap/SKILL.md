---
name: codemap
description: How to use and maintain the Conductor project map (.conductor/MAP.md, module cards, impact analysis) so changes touch and re-read only related files instead of scanning the whole project. Use when you need repository context, after edits, or when cards are stale.
---

# Conductor codemap

Shorthand: `CM` = `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/codemap.py"`.

## What exists

| Layer | Who writes it | Cost to read | What it answers |
|---|---|---|---|
| `.conductor/map.json` | script (hooks) | never read by models | file hashes, module of each file, dependency edges |
| `.conductor/MAP.md` | script | ~1–4k chars, injected at session start | which modules exist, sizes, module→module deps, which cards are stale |
| `.conductor/cards/<module>.md` | cartographer (haiku) | ≤ 60 lines each, read on demand | purpose, public interface, invariants, file list of one module |
| source files | humans/builder | expensive | details |

Read top-down and stop as soon as you have enough. Never glob or read the whole tree.

## Using it

- Which module? → MAP.md (already in context).
- How does module X work / what must not break? → its card.
- Who depends on file F? → `CM impact F` (direct dependents and affected modules). Re-check those after changing F.
- Where exactly is symbol S? → `conductor:finder` (haiku), starting from the card.

## Keeping it fresh (automatic)

- **SessionStart hook**: `CM sync` re-indexes only files whose size/mtime changed since last time (cheap, no model), then injects MAP.md.
- **PostToolUse hook on Edit/Write/MultiEdit/NotebookEdit**: re-indexes the edited file, marks its module card STALE, and tells you the direct dependents.
- **You**: at the end of a task, if cards of modules you touched are STALE, delegate to `conductor:cartographer` with exactly those module ids (`CM stale` lists them). Cards for modules you did not touch can stay stale until needed.

Edits made outside Claude Code (IDE, git pull) are caught by the next session's `sync`, or immediately with `CM sync`.

## Dependency detection

Automatic for: Python, JS/TS (relative imports, `@/` alias → `src/`), GDScript/`.tscn` (`res://`), Markdown links, HTML `src/href`.
Everything else (C#/Unity, C++, Go, SQL, notebooks, data files): annotate where it matters, in any comment:
```
// @map: depends=Assets/Scripts/Net/Lobby.cs, Assets/Scripts/Core/Events.cs
# @map: tags=economy, save-format
```
Override module grouping in `.conductor/config.json`:
```json
{"codemap": {"modules": {"net": ["Assets/Scripts/Net/*"], "ui": ["Assets/UI/**"]},
             "ignore": ["data/raw/*"]}}
```

## Non-code projects (research, analytics)

The same map indexes `.md`, `.csv`, `.sql`, `.ipynb`, etc. Use cards as the project's verified knowledge base: one card per topic, `purpose:` line, then verified facts with source URL and date. Link related notes with relative Markdown links so impact analysis works between them.

## Commands

`CM init` (full scan, card stubs) · `CM sync` · `CM update <files>` · `CM impact <files>` · `CM stale` · `CM fresh <modules>` · `CM render`
