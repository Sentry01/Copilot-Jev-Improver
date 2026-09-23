-- 02 — Who initiates the spend: user turns vs autonomous agent turns
-- Source: LOCAL  ~/.copilot/session-store.db  (table: assistant_usage_events)
-- Lever:  cost, performance
-- Gates it justifies: stop-vs-continue, tool-worth-it, plan-vs-act
--
-- The headline efficiency number for an agentic CLI is the ratio of autonomous
-- model calls to user-initiated ones. A high ratio means most of the bill is the
-- agent talking to itself, which is exactly what loop gating targets.

SELECT
    COALESCE(NULLIF(initiator, ''), '(none)')        AS initiator,
    COUNT(*)                                         AS requests,
    ROUND(SUM(total_nano_aiu) / 1e9, 2)              AS aiu,
    ROUND(SUM(total_nano_aiu) / 1e9 / COUNT(*), 2)   AS aiu_per_request,
    ROUND(AVG(duration_ms))                          AS avg_duration_ms,
    ROUND(AVG(time_to_first_token_ms))               AS avg_ttft_ms
FROM assistant_usage_events
WHERE substr(created_at, 1, 10) >= date('now', :window)
GROUP BY initiator
ORDER BY aiu DESC;
