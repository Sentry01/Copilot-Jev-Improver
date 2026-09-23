-- 08 — Redundant tool calls: identical arguments, repeated within one session
-- Source: CLOUD session store (tool_executions + tool_requests). DuckDB dialect.
-- Lever:  cost, performance
-- Gates it justifies: redundant-tool-call
--
-- The cleanest possible waste signal: the exact same tool invoked with byte-identical
-- arguments more than once inside a single session. Every repeat past the first is a
-- call whose answer was already in hand.
--
-- NOTE: arguments_json can contain file paths, prompts and customer data. It is used
-- ONLY as a grouping key here and is never selected into the output or published.

WITH recent AS (
    SELECT session_id, tool_call_id, tool_name
    FROM tool_executions
    WHERE started_at >= now() - INTERVAL '30 days'
),
joined AS (
    SELECT r.session_id, r.tool_name, tr.arguments_json
    FROM recent r
    JOIN tool_requests tr
      ON tr.session_id = r.session_id
     AND tr.tool_call_id = r.tool_call_id
),
dupes AS (
    SELECT session_id, tool_name, arguments_json, COUNT(*) AS n
    FROM joined
    GROUP BY session_id, tool_name, arguments_json
    HAVING COUNT(*) > 1
)
SELECT
    tool_name,
    COUNT(*)     AS duplicated_argument_sets,
    SUM(n)       AS total_calls_in_those_sets,
    SUM(n - 1)   AS wasted_repeat_calls
FROM dupes
GROUP BY tool_name
ORDER BY wasted_repeat_calls DESC
LIMIT 25;
