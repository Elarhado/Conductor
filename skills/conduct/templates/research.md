<spec profile="research">
<goal>One sentence: what question must be answered and for whom.</goal>
<deliverable>Format (answer in chat | report file | table), language (ru), length.</deliverable>
<scope>
  geography: ... | period: ... | entities: ... | out of scope: ...
</scope>
<definitions>
  Fix every metric and term BEFORE research, e.g.
  - "subscribers" = ... (source's definition must match; otherwise report both, do not mix)
  - "launch" = commercial launch | announcement | pilot
</definitions>
<sources>
  prefer: regulators, official statistics, company IR/press releases, standards bodies, peer-reviewed
  acceptable: reputable industry media (mark secondary)
  avoid: ...
  freshness: newest available as of <date>; flag anything older than <N> months
</sources>
<questions>
  Q1 ...
  Q2 ...
</questions>
<plan>
  1. scout ×N (parallel by question group) → evidence/*.jsonl
  2. reader (local files, if any)
  3. analyst (only if calculations are needed)
  4. orchestrator: synthesis → draft.md with [Cn] markers
  5. verify loop (fact-checker) → render
</plan>
<acceptance>
  - every factual statement has [Cn] → verified claim
  - definitions consistent across all compared entities
  - conflicts between sources are shown, not hidden
  - NOT FOUND items stated explicitly
</acceptance>
<assumptions>ASSUMPTION: ...</assumptions>
<open>OPEN: ...</open>
</spec>
