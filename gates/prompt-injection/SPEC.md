# Gate: prompt-injection

**Name:** Prompt Injection Gate  
**Slug:** `prompt-injection`  
**Rank / source:** #16 honourable mention in `docs/cool-use-cases.md`  
**Primary lever:** safety

## Purpose

Before ingesting untrusted external text, refuse content that tries to steer the agent, override higher-priority instructions, exfiltrate secrets, or trigger destructive tool use.

## When to call

Call on content returned by web pages, web search, issue and PR comments, Slack or Teams messages, Jira tickets, email, calendars, transcripts, and other MCP reads before the agent treats that text as instructions or task context.

The gate is for **untrusted content**, not proposed output. It should run after cheap deterministic extraction of the returned text and before the model incorporates that text into its next reasoning step.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `untrusted_content` | string | The fetched, searched, or tool-returned text to inspect |
| `source_tool` | string | Tool that produced or will produce the content, such as `web_fetch`, `web_search`, `slack_read_thread`, or `workiq-fetch` |
| `source_kind` | string | `web_page` / `web_search` / `github_comment` / `mcp_result` / `email` / `chat` / `ticket` / `unknown` |
| `retrieval_context` | string | Why the agent fetched the content |
| `content_available` | boolean | Whether actual returned content is present, as opposed to only a URL/query before retrieval |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_consume` | `noul` | Belief that the content can be used as data/evidence without following embedded instructions |
| `injection_intent` | `choice` | `none`, `benign_discussion`, `role_override`, `tool_misuse`, `data_exfiltration`, `destructive_action` |
| `severity` | `score` | Ordered: `none`, `low`, `moderate`, `high`, `critical` |

No free-text questions.

## Thresholds

Consume only if `safe_to_consume >= 0.8`, `injection_intent` is one of `none` or `benign_discussion`, and `severity <= low`.

Deterministic hard rules run first and do not call Jev. They block direct attempts to override system/developer/user instructions, reveal hidden prompts, exfiltrate credentials or environment variables, or make the agent execute destructive commands. Obvious quoted or negated educational discussion is allowed locally so documentation and security advisories do not get blocked merely for mentioning attack strings.

## Fail mode

**Fail closed.** If Jev is unreachable or answers unusably, quarantine the content rather than ingesting it. Prompt injection acts through the user's real credentials and shell access, so allowing ambiguous untrusted instructions on an outage would be the unsafe choice.

A fixture-sourced block is surfaced as `ask` by the hook layer, not as an enforced deny, because recorded evidence is not live evidence.

## Expected efficiency win

This is a safety gate. It reduces the chance that third-party text can redirect the agent into leaking secrets, ignoring repository instructions, or running commands the user never intended.
