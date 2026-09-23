-- 09 — Shell usage that duplicates purpose-built tools
-- Source: CLOUD session store (tool_executions + tool_requests). DuckDB dialect.
-- Lever:  cost, performance, safety
-- Gates it justifies: context-read-budget, tool-worth-it
--
-- Copilot CLI ships dedicated `view`, `grep` and `glob` tools and instructs the agent
-- to prefer them over shell equivalents. Shelling out to cat/grep/find instead is
-- worse on three axes: it returns unbounded output into context (read amplification),
-- it is slower, and it widens the command surface that has to be safety-checked.
--
-- This buckets bash invocations by intent to size that leak.
--
-- NOTE: arguments_json is matched against but never selected. Buckets only.

WITH recent AS (
    SELECT session_id, tool_call_id
    FROM tool_executions
    WHERE started_at >= now() - INTERVAL '30 days'
      AND tool_name = 'bash'
),
b AS (
    SELECT lower(COALESCE(tr.arguments_json, '')) AS a
    FROM recent r
    JOIN tool_requests tr
      ON tr.session_id = r.session_id
     AND tr.tool_call_id = r.tool_call_id
)
SELECT
    CASE
        WHEN a ILIKE '%"command":"cat %'
          OR a ILIKE '%"command":"head %'
          OR a ILIKE '%"command":"tail %'            THEN 'read_file_via_bash'
        WHEN a ILIKE '%grep %' OR a ILIKE '%rg %'    THEN 'search_via_bash'
        WHEN a ILIKE '%"command":"find %'
          OR a ILIKE '%"command":"ls %'              THEN 'list_via_bash'
        WHEN a ILIKE '%git %'                        THEN 'git'
        WHEN a ILIKE '%gh %'                         THEN 'gh_cli'
        WHEN a ILIKE '%python%' OR a ILIKE '%pytest%'
          OR a ILIKE '%npm %'   OR a ILIKE '%node %' THEN 'run_code_or_tests'
        WHEN a ILIKE '%curl%'   OR a ILIKE '%az %'   THEN 'network_or_cloud'
        ELSE 'other'
    END       AS category,
    COUNT(*)  AS calls
FROM b
GROUP BY category
ORDER BY calls DESC;
