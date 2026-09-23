# Bash instead of a built-in

**Trap slug:** `bash-instead-of-builtin`  
**Gate:** `tool-worth-it`  
**Expected offline decision:** `skip_tool` / proceed=`false`  
**Expected source:** `fixture`

> Honesty note: this trap's runner result is fixture-backed unless `source=live` appears in the table. Fixture output proves offline gate wiring and threshold behavior; it is not proof that live Jev will score the situation the same way.

## 1. Situation

Copilot is about to shell out to grep/find/cat for repo search and file reading even though built-in grep/glob/view are available.

## 2. Ungated default

Bash is a universal escape hatch and feels natural for developers; grep/find/cat work, but they bypass bounded tool output and add process latency.

## 3. Measured evidence

docs/cool-use-cases.md §§3–4: bash ran 2,060 times at 9.1s average (5.0h wall-clock); 831 of those calls (40.3%) did built-ins' work: 747 search, 44 list, 40 reads. Built-ins were much faster: view averaged 908ms and glob 629ms.

## 4. Gated outcome

The gate skips the bash command and forces the cheaper built-in path. The concrete saving is avoiding the 9.1s bash path in favor of grep/glob/view for this search/read task.

## 5. Falsifier

If the requested operation requires shell semantics the built-ins cannot express, or built-ins return incomplete data while bash succeeds, the gate is over-blocking.

## State sent to the gate

```json
{
  "user_goal": "Find every TODO marker under src/ before editing one file.",
  "already_have": "Copilot CLI has purpose-built grep/glob/view tools with bounded output for exactly this search/read/list work.",
  "proposed_tool": "bash: grep -R \"TODO\" src && find src -type f && cat src/components/Button.tsx",
  "est_cost_tier": "medium",
  "est_latency_ms": 9100
}
```
