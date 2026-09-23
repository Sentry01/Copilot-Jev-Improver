# Gate: secret-exposure

**Name:** Secret Exposure Gate  
**Slug:** `secret-exposure`  
**Rank / source:** #10 in `docs/cool-use-cases.md`  
**Primary lever:** safety

## Purpose

Before writing, printing, committing, or sending content, ask Jev whether anything sensitive would escape. This protects credentials, customer data, personal data, and internal-only details from durable or external exposure.

## When to call

After deterministic scanners, allowlists, and ignore rules have run, and immediately before emitting content to a commit, log, artifact, third party, or user-visible surface.

## State schema

| Field | Type | Notes |
| --- | --- | --- |
| `proposed_output` | string | What is about to be written, printed or sent |
| `destination` | string | `commit` / `log` / `artifact` / `third_party` / `user_visible` |
| `contains_env_reference` | boolean | Does it interpolate environment values? |
| `repo_visibility` | string | `public` / `private` / `internal` |
| `data_classification` | string | `public` / `internal` / `customer` / `credential` |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `safe_to_emit` | `noul` | Belief nothing sensitive escapes |
| `exposure_kind` | `choice` | `none`, `credential`, `customer_data`, `personal_data`, `internal_only` |
| `severity` | `score` | Ordered: `none`, `low`, `moderate`, `high`, `critical` |

No free-text questions.

## Thresholds

Emit only if `safe_to_emit >= 0.85` and `exposure_kind = none`. This is deliberately the highest bar in the library because blocking a message is cheap and leaking a key is not.

## Fail mode

**Fail closed.** Always block on missing answers or Jev failure. Failing open would be wrong because this repo is public and the environment contains credentials for systems such as Kusto, Slack, Salesforce, Microsoft Graph, Seismic, and TypeSafe.

This is a **second line of defence**, not the first. Deterministic scanners, allowlists, and ignore rules run first because they are exact; Jev catches contextual misses.

## Expected efficiency win

This is a safety gate. It avoids incident response, secret rotation, public-repo cleanup, and customer-data exposure. The telemetry evidence is the environment and repo context: credentials are present, the repo is public, and the telemetry pipeline already needed enforced redaction controls.
