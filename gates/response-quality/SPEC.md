# Gate: response-quality

**Name:** Response Quality Gate  
**Slug:** `response-quality`  
**Rank / source:** #13 in `cool-use-cases.md`  
**Primary lever:** quality

## Purpose

Before sending a reply, ask whether the draft is complete, specific, on target, and supported by the supplied evidence. This catches vague, unsupported, or incomplete answers before they leave the agent.

## When to call

Immediately before a final chat reply or before handing a draft to an external-write gate for messages that leave the machine.

## State schema (agent-ops only)

| Field | Type | Notes |
| --- | --- | --- |
| `user_request` | string | What was asked |
| `draft` | string | The proposed reply |
| `success_criteria` | string | What a good answer must contain |
| `evidence_sources` | array | `[{tool, claim, excerpt}]` — supply this whenever claims came from tools |
| `unresolved` | string | Anything knowingly unanswered |

## Jev question map

| Key | Type | Role |
| --- | --- | --- |
| `ready_to_send` | `noul` | Belief the draft answers the ask |
| `send_quality` | `score` | Ordered: `unusable`, `weak`, `adequate`, `good`, `excellent` |
| `main_defect` | `choice` | `none`, `incomplete`, `vague`, `unsupported`, `off_target`, `too_long` |

No free-text questions.

## Thresholds

- **Send** if `ready_to_send.noul >= 0.65` and `send_quality >= adequate`
- Else **revise_response**

The `0.65` threshold is deliberate calibration history from the upstream grokbot gate: `0.7` false-held good sourced answers in Trap D. Do not raise it without re-running the response-quality trap suite. Always pass `evidence_sources`; omitting it is the known cause of false holds on sourced claims.

## Fail mode

The authoritative spec splits failure handling: closed for external sends and open for chat. This implementation uses the chat-path **fail-open** default (`send_response`) because the shared runner accepts one `open`/`closed` mode and external sends are separately guarded by the external-write gate.

## Expected efficiency win

Quality rework reduction. The cut-list evidence ranks this #13 and notes it was ported from grokbot-improver, where response quality was the #2 gate after measured false-hold calibration.
