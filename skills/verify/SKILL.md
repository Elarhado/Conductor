---
name: verify
description: Circular verification loop for a Conductor run or any draft/answer/code - independent verifiers check every claim, the producer fixes, changed parts are re-checked until nothing is pending or refuted. Use before delivering any factual, analytical or code result.
argument-hint: "[run-id | path to draft] "
---

# Circular verification

Purpose: nothing reaches the user that an independent checker has not confirmed against evidence. A model that "knows where the error is when asked" was simply never asked — this loop asks every time, with a fresh context that did not write the work.

Shorthand: `RUNS` = `sh "${CLAUDE_PLUGIN_ROOT}/scripts/py.sh" "${CLAUDE_PLUGIN_ROOT}/scripts/runs.py"`.

## Inputs

- A run id (normal case, from `conductor:conduct`), or
- a file/answer to check standalone: create a run (`RUNS new --slug verify-<topic>`), copy the text to `<run>/draft.md`, then extract claims (step 1).

## Step 1 — Make every claim explicit (orchestrator, once)

Every statement that could be wrong becomes a ledger entry and gets a `[Cn]` marker in the draft: facts, numbers, dates, names of standards/products/versions, quotes, definitions, causal claims, code behaviour claims ("this API exists", "this function returns X"). Opinions and recommendations don't need claims, but the facts they rest on do.

Split compound sentences: one claim = one checkable statement.

## Step 2 — Round

```
RUNS phase --run <id> --set verifying
RUNS round --run <id>          # prints round number; stop at limit (default 4)
RUNS list --run <id> --status pending
```

Spawn verifiers. They must not see your reasoning, only the claims, the cited sources and the draft:
- facts/sources/definitions → `conductor:fact-checker` (sonnet). For more than ~25 pending claims split into batches by topic and run up to 3 in parallel.
- code → `conductor:code-verifier` (sonnet).
- calculations → `conductor:fact-checker` re-running the analyst's scripts, or `conductor:code-verifier` for complex SQL/Python.

Prompt (English):
```
RUN: .conductor/runs/<id>/
CHECK: claims <ids>   (list with: RUNS list --run <id> --ids <ids>)
DRAFT: .conductor/runs/<id>/draft.md
DEFINITIONS FIXED IN SPEC: <paste the <definitions> block>
RETURN: one line per claim "Cn | verified|refuted|unverifiable | reason | correct value + source", then UNTRACED list. ≤ 300 words.
```

## Step 3 — Apply verdicts (orchestrator)

For each verdict: `RUNS set --run <id> --id Cn --status <verdict> --note "<reason>"`.

Then fix the draft:
- **refuted** → replace with the corrected statement as a NEW claim (`RUNS add ...` with the verifier's source), mark the old one `retracted`, update the marker. Re-read the surrounding text: a wrong premise often makes the conclusion wrong too — re-derive conclusions that depended on it.
- **unverifiable** → either find another source (scout, one attempt) and add it as a new pending claim, or remove the statement, or keep it explicitly marked as unconfirmed if it is genuinely useful to the user.
- **UNTRACED** statements → add claims for them (pending) or delete them.
- **definition mismatch** → never "harmonise" numbers measured differently; either find comparable figures or present them separately with each definition.

You are the adjudicator when a verifier and the evidence disagree, but you may only overrule a `refuted` verdict by opening the source yourself and quoting the passage; record that in the note.

## Step 4 — Repeat on what changed

Next round checks only: new claims, claims whose text/source changed, and statements next to edits. Not the whole document again.

Stop when **all** hold:
- `RUNS summary` shows `pending = 0` and `refuted = 0`;
- `RUNS check --run <id> --file draft.md` exits 0 (no blockers: no unknown/unverified markers, no numbers without markers);
- for code: build + tests pass in the last code-verifier report and every acceptance criterion is met.

If the round limit is reached and something is still open: stop looping. Remove the open statements or mark them unconfirmed, set `RUNS phase --set awaiting_user` if the user's knowledge is required (internal company data, a choice between definitions), and ask one concise question in Russian. Only ask the user about things outside what tools can verify.

## Step 5 — Final adversarial read (orchestrator, short)

Before rendering, read the final draft once looking only for: conclusions stronger than the claims support, comparisons across different definitions, outdated "current" states, and silent omissions of conflicting evidence. Fix and, if you add facts, run one more round for them.

Then return to `conductor:conduct` step 6 (render and deliver), or, standalone, run `RUNS render` and report what was checked and what changed.

## Honesty rule

The gate guarantees that every statement shown to the user is either traced to a source an independent checker confirmed, or visibly marked unconfirmed. It cannot make a wrong primary source right; when the best available sources are weak or disagree, say so plainly.
