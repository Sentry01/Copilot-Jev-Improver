-- 06 — Main-agent vs subagent spend
-- Source: LOCAL  ~/.copilot/session-store.db  (table: assistant_usage_events)
-- Lever:  cost
-- Gates it justifies: subagent-spawn, factory-fleet-spawn
--
-- Delegation is the highest-variance cost decision available to the agent: one
-- `task` call or `run_factory` run can multiply a turn's cost many times over.
-- This sizes how much of the bill currently flows through delegated lanes.

SELECT
    CASE
        WHEN agent_id IS NULL OR agent_id = '' THEN 'main'
        ELSE 'subagent'
    END                                              AS lane,
    COUNT(*)                                         AS requests,
    COUNT(DISTINCT session_id)                       AS sessions,
    ROUND(SUM(total_nano_aiu) / 1e9, 2)              AS aiu,
    ROUND(SUM(total_nano_aiu) / 1e9 / COUNT(*), 2)   AS aiu_per_request,
    ROUND(AVG(duration_ms))                          AS avg_duration_ms
FROM assistant_usage_events
WHERE substr(created_at, 1, 10) >= date('now', :window)
GROUP BY lane
ORDER BY aiu DESC;
