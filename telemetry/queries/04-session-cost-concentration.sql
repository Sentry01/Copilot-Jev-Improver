-- 04 — Spend concentration across sessions
-- Source: LOCAL  ~/.copilot/session-store.db  (table: assistant_usage_events)
-- Lever:  cost
-- Gates it justifies: stop-vs-continue, subagent-spawn, factory-fleet-spawn
--
-- Agentic spend is heavily Pareto-distributed: a small number of runaway sessions
-- dominate the bill. This ranks sessions by AI Units and shows the cumulative
-- share, which sizes the prize for loop-termination gates.
--
-- NOTE: session_id is a local identifier and is NEVER published. The miner drops
-- it and publishes only the rank. See telemetry/README.md.

WITH per_session AS (
    SELECT
        session_id,
        SUM(total_nano_aiu) / 1e9 AS aiu,
        COUNT(*)                  AS requests,
        SUM(input_tokens)         AS input_tokens
    FROM assistant_usage_events
    WHERE substr(created_at, 1, 10) >= date('now', :window)
    GROUP BY session_id
),
ranked AS (
    SELECT
        aiu,
        requests,
        input_tokens,
        ROW_NUMBER() OVER (ORDER BY aiu DESC) AS rank
    FROM per_session
)
SELECT
    rank,
    ROUND(aiu, 2)                                          AS aiu,
    requests,
    ROUND(input_tokens / 1e6, 2)                           AS input_mtok,
    ROUND(aiu * 100.0 / (SELECT SUM(aiu) FROM ranked), 2)  AS pct_of_aiu,
    ROUND(
        SUM(aiu) OVER (ORDER BY rank) * 100.0 / (SELECT SUM(aiu) FROM ranked),
        2
    )                                                      AS cumulative_pct
FROM ranked
ORDER BY rank
LIMIT 15;
