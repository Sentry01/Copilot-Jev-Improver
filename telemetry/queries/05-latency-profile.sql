-- 05 — Latency profile by model and effort
-- Source: LOCAL  ~/.copilot/session-store.db  (table: assistant_usage_events)
-- Lever:  performance
-- Gates it justifies: model-effort-route, parallel-fanout
--
-- Establishes the latency budget a gate must fit inside. A Jev gate costs roughly
-- 300-500 ms, so gating a decision that only saves a 400 ms call is a net loss.
-- Gate the slow and expensive things, short-circuit everything else.

SELECT
    model,
    COALESCE(NULLIF(reasoning_effort, ''), '(none)') AS reasoning_effort,
    COUNT(*)                                         AS requests,
    ROUND(AVG(duration_ms))                          AS avg_duration_ms,
    ROUND(AVG(time_to_first_token_ms))               AS avg_ttft_ms,
    MAX(duration_ms)                                 AS max_duration_ms,
    ROUND(SUM(duration_ms) / 1000.0)                 AS total_seconds
FROM assistant_usage_events
WHERE substr(created_at, 1, 10) >= date('now', :window)
  AND duration_ms IS NOT NULL
GROUP BY model, reasoning_effort
HAVING COUNT(*) >= 10
ORDER BY total_seconds DESC;
