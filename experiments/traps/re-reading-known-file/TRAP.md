# Re-reading a known file

**Trap slug:** `re-reading-known-file`  
**Gate:** `redundant-tool-call`  
**Expected offline decision:** `reuse_cache` / proceed=`false`  
**Expected source:** `fixture`

> Honesty note: this trap's runner result is fixture-backed unless `source=live` appears in the table. Fixture output proves offline gate wiring and threshold behavior; it is not proof that live Jev will score the situation the same way.

## 1. Situation

Copilot is about to read an unchanged file/range that is already in the current context.

## 2. Ungated default

Agents often re-read a known file to feel certain before editing or summarizing. It is natural but expensive because the result is already in context.

## 3. Measured evidence

docs/cool-use-cases.md §5: grouping by session, tool name, and arguments found 253+ byte-identical repeat calls in 30 days, including 77 bash, 46 view, and 26 browser_snapshot repeats. The same document and baseline report show a 260.8:1 input:output ratio, so repeated reads mainly add context cost.

## 4. Gated outcome

The gate reuses cached context instead of calling view again. The saving is unmeasured in AIU for this exact file, but it avoids a known repeated input payload.


## Current offline status

This trap is intentionally **failing** in the current gate run. The redundant-tool-call gate's `_mutation_hint()` treats the phrase `no intervening mutation` as evidence of a mutation because it matches the substring `mutation`, so the gate calls the tool even though the state says the file is unchanged. That is a gate bug; this trap should remain red until the gate handles negated mutation language or the harness supplies structured mutation state.

## 5. Falsifier

If the file changed after the earlier read, or the previous read was outside the needed range, reusing cache would be stale and the trap should fail.

## State sent to the gate

```json
{
  "proposed_call": "view docs/cool-use-cases.md lines 1-260",
  "prior_calls": "The same file range was read earlier this turn and no write touched docs/cool-use-cases.md afterward.",
  "elapsed_since_prior": "less than 10 minutes; no intervening mutation",
  "volatility": "static"
}
```
