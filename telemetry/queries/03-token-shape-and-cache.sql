-- 03 — Token shape and cache effectiveness
-- Source: LOCAL  ~/.copilot/session-store.db  (table: assistant_usage_events)
-- Lever:  cost
-- Gates it justifies: context-read-budget  (and, importantly, what NOT to build)
--
-- If cache_pct is already high, prompt shaping is a dead end and the remaining
-- win is in avoiding turns and tools altogether. Measure before optimising.

SELECT
    ROUND(SUM(input_tokens)       / 1e6, 2)  AS input_mtok,
    ROUND(SUM(cache_read_tokens)  / 1e6, 2)  AS cache_read_mtok,
    ROUND(SUM(cache_write_tokens) / 1e6, 2)  AS cache_write_mtok,
    ROUND(SUM(output_tokens)      / 1e6, 2)  AS output_mtok,
    ROUND(SUM(reasoning_tokens)   / 1e6, 2)  AS reasoning_mtok,
    ROUND(SUM(cache_read_tokens) * 100.0 / NULLIF(SUM(input_tokens), 0), 2) AS cache_pct,
    ROUND(SUM(input_tokens) * 1.0 / NULLIF(SUM(output_tokens), 0), 1)       AS input_output_ratio
FROM assistant_usage_events
WHERE substr(created_at, 1, 10) >= date('now', :window);
