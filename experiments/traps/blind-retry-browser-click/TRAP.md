# Blind retry of a browser click

**Trap slug:** `blind-retry-browser-click`  
**Gate:** `retry-worth-it`  
**Expected offline decision:** `do_not_retry` / proceed=`false`  
**Expected source:** `fixture`

> Honesty note: this trap's runner result is fixture-backed unless `source=live` appears in the table. Fixture output proves offline gate wiring and threshold behavior; it is not proof that live Jev will score the situation the same way.

## 1. Situation

A browser_click failed and Copilot is about to repeat the same click with no changed selector, snapshot, auth state, or page state.

## 2. Ungated default

Browser automation failures invite one more click; the agent hopes the page settled even though nothing materially changed.

## 3. Measured evidence

docs/cool-use-cases.md §9: browser_click failed 22 of 28 times (78.6%), browser_navigate 31 of 52 times (59.6%), and browser_type 3 of 5 times (60%). Blind retry has negative expected value at those failure rates.

## 4. Gated outcome

The gate refuses an unchanged retry and forces a different path. The saving is avoided browser latency and agent turns; exact AIU for this click is unmeasured.

## 5. Falsifier

If unchanged retries after identical browser_click failures regularly succeed, or if the gate blocks a retry that has a concrete changed selector/snapshot, the trap is not helping.

## State sent to the gate

```json
{
  "failed_tool": "browser_click",
  "error_summary": "Click failed: element not found for selector text=Submit.",
  "attempt_number": 2,
  "change_since_last_attempt": "",
  "tool_historical_failure_rate": 0.786,
  "alternative_paths": "Take a fresh accessibility snapshot, use keyboard navigation, or inspect whether authentication/page state changed."
}
```
