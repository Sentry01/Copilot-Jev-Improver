-- 01 — Cost by model and reasoning effort
-- Source: LOCAL  ~/.copilot/session-store.db  (table: assistant_usage_events)
-- Lever:  cost
-- Gate it justifies: model-effort-route
--
-- total_nano_aiu is billed AI Units in nano-units; divide by 1e9 for AIU.
-- Shows which model/effort pair dominates spend, and cost per request, which is
-- the number that tells you whether an escalation to a pricier tier was worth it.

SELECT
    model,
    COALESCE(NULLIF(reasoning_effort, ''), '(none)')          AS reasoning_effort,
    COUNT(*)                                                  AS requests,
    ROUND(SUM(total_nano_aiu) / 1e9, 2)                       AS aiu,
    ROUND(SUM(total_nano_aiu) / 1e9 / COUNT(*), 2)            AS aiu_per_request,
    ROUND(
        SUM(total_nano_aiu) * 100.0 / NULLIF((
            SELECT SUM(total_nano_aiu)
            FROM assistant_usage_events
            WHERE substr(created_at, 1, 10) >= date('now', :window)
        ), 0),
        2
    )                                                         AS pct_of_aiu
FROM assistant_usage_events
WHERE substr(created_at, 1, 10) >= date('now', :window)
GROUP BY model, reasoning_effort
ORDER BY aiu DESC;
