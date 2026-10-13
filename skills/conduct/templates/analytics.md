<spec profile="analytics">
<goal>One sentence: the business/technical question the numbers must answer.</goal>
<data>
  datasets: paths/tables, grain (one row = ...), period, known quirks
  joins/keys: ...
</data>
<definitions>
  metric: formula, filters, period, units/currency, rounding
  (same metric name must mean the same thing across all slices)
</definitions>
<deliverable>numbers in chat | table file | chart | dashboard; language ru</deliverable>
<plan>
  1. analyst: data profiling (counts, nulls, duplicates, units) → caveats
  2. analyst: computation script(s) in run/analysis/ → evidence/analyst.jsonl
  3. formatter: tables/chart data
  4. orchestrator: interpretation → draft.md with [Cn]
  5. verify: fact-checker re-runs scripts and spot-checks inputs; code-verifier for SQL/py if complex
</plan>
<acceptance>
  - every number traces to a script line ([Cn] kind=calc) or a cited source
  - scripts re-run end to end without manual steps
  - caveats (data quality, definition limits) stated
</acceptance>
<assumptions>ASSUMPTION: ...</assumptions>
<open>OPEN: ...</open>
</spec>
