-- 07 — Tool call mix, cost in wall-clock time, and failures
-- Source: CLOUD session store (views: tool_executions). DuckDB dialect.
--         Run via the Copilot CLI `session_store_sql` tool; these views are not
--         present in the local SQLite store.
-- Lever:  cost, performance
-- Gates it justifies: tool-worth-it, context-read-budget, mcp-route
--
-- Establishes which tools dominate, how slow they are, and where failures cluster.
-- Wall-clock seconds matter as much as call counts: a tool called 40 times at 9 s
-- each is a bigger latency problem than one called 400 times at 100 ms.

SELECT
    tool_name,
    COUNT(*)                                                      AS calls,
    SUM(CASE WHEN success THEN 0 ELSE 1 END)                      AS failures,
    ROUND(SUM(CASE WHEN success THEN 0 ELSE 1 END) * 100.0 / COUNT(*), 1) AS fail_pct,
    ROUND(AVG(CASE WHEN completed_at >= started_at THEN duration_ms END)) AS avg_ms,
    ROUND(SUM(CASE WHEN completed_at >= started_at THEN duration_ms END) / 1000.0) AS total_seconds
FROM tool_executions
WHERE started_at >= now() - INTERVAL '30 days'
GROUP BY tool_name
ORDER BY calls DESC
LIMIT 40;
