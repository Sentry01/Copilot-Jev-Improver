# Factory for a one-liner

**Trap slug:** `factory-for-one-liner`  
**Gate:** `subagent-spawn`  
**Expected offline decision:** `inline` / proceed=`false`  
**Expected source:** `fixture`

> Honesty note: this trap's runner result is fixture-backed unless `source=live` appears in the table. Fixture output proves offline gate wiring and threshold behavior; it is not proof that live Jev will score the situation the same way.

## 1. Situation

Copilot is about to launch a factory/fleet for a typo or one-line label fix the parent can do directly.

## 2. Ungated default

Delegation is encouraged for complex work and keeps the main context clean, so it is natural to over-apply it to tiny tasks.

## 3. Measured evidence

docs/cool-use-cases.md §8 and telemetry/reports/baseline-2026-09-23.md: delegated lanes consumed 9.2% of AI Units; docs/cool-use-cases.md also records task calls averaging 174s. A factory can multiply that cost across many agents.

## 4. Gated outcome

The gate inlines the task and avoids a factory/fleet spawn. The saving is the delegated-lane startup/context cost; exact AIU for this one typo is unmeasured.

## 5. Falsifier

If the one-line task actually needs independent research, special tooling, or true parallelism, inline execution could be slower or lower quality and the trap is invalid.

## State sent to the gate

```json
{
  "task_description": "Spawn a factory fleet to change one typo in README copy.",
  "context_transfer_size": "Small: the parent already knows the file, typo, and desired replacement.",
  "parent_can_do_inline": "Yes. It is one bounded edit and one verification read.",
  "parallelism_benefit": "None; there are no independent workstreams.",
  "spawn_kind": "factory_fleet",
  "writes_to_shared_tree": false
}
```
