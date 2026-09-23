# Opus on a trivial turn

**Trap slug:** `opus-on-trivial-turn`  
**Gate:** `model-effort-route`  
**Expected offline decision:** `downgrade` / proceed=`true`  
**Expected source:** `fixture`

> Honesty note: this trap's runner result is fixture-backed unless `source=live` appears in the table. Fixture output proves offline gate wiring and threshold behavior; it is not proof that live Jev will score the situation the same way.

## 1. Situation

The user asks for a one-line UI label change in a known file while the session is running on a frontier/high tier.

## 2. Ungated default

Copilot CLI naturally keeps using the session's current model and effort; there is no built-in pause that asks whether this tiny edit needs Opus-level reasoning.

## 3. Measured evidence

docs/cool-use-cases.md §1 and telemetry/reports/baseline-2026-09-23.md: claude-opus-5 @ high is 50.3% of AI Units across 3,861 requests at 19.52 AIU/request, while gpt-5.6-luna @ medium is 0.33 AIU/request across 127 requests — about 60x cheaper.

## 4. Gated outcome

The gate routes the turn down to cheap_fast. The measured per-request comparison is 19.52 vs 0.33 AIU/request; exact savings for this turn remain fixture-backed until a live run is recorded.

## 5. Falsifier

If live Jev scores a trivial single-file label edit as deep/frontier-needed, or the cheaper tier causes a failed edit that requires retrying on the expensive tier, this trap is not helping.

## State sent to the gate

```json
{
  "user_request": "Change the button label from Save to Done in one JSX file.",
  "turn_kind": "edit",
  "blast_radius": "single_file",
  "context_size_tier": "small",
  "prior_attempts": 0,
  "current_tier": "frontier_high"
}
```
