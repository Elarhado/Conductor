<spec profile="build">
<goal>One sentence: the user-visible behaviour to add or change.</goal>
<context>
  project/engine/framework + version: ... (from lockfile/project file, not memory)
  modules touched (from MAP.md): ...
  cards read: .conductor/cards/...
</context>
<deliverable>Code changes in repo | new files | build artifact. Branch/commit policy if any.</deliverable>
<design>
  Decisions made by the orchestrator (data flow, interfaces, where state lives).
  Alternatives rejected and why (one line each).
</design>
<steps>
  1. builder: ... (files: ...)
  2. builder: ...
  each step small enough to verify on its own
</steps>
<acceptance>
  - observable behaviour: ...
  - build passes, linter/type check passes, tests: ... (existing + new)
  - no invented APIs: every new API call exists in installed version
  - dependents of changed files still work (codemap impact)
</acceptance>
<constraints>performance budgets, platforms, style, things that must not change</constraints>
<assumptions>ASSUMPTION: ...</assumptions>
<open>OPEN: ...</open>
</spec>
