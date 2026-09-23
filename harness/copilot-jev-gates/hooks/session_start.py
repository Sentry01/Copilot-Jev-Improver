#!/usr/bin/env python3
"""sessionStart hook — tell the agent which gates are live.

Injects ``additionalContext`` describing what is enforced and what the operating
rules are. This matters for honesty as much as for behaviour: an agent that gets
a denial from a hook it does not know exists will usually try to work around it,
which is the opposite of what a gate is for.

Cheap by construction — reads the gate configs from disk, makes no network call.
"""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from harness import emit, gates_root  # noqa: E402


def main() -> int:
    try:
        root = gates_root()
        gates = []
        for config_path in sorted(root.glob("*/config.json")):
            try:
                config = json.loads(config_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            gates.append((config.get("slug", config_path.parent.name), config.get("fail_mode", "open")))
        if not gates:
            emit({})
            return 0
    except Exception:
        emit({})
        return 0

    mode = "live" if os.environ.get("TYPESAFE_API_KEY") else "fixture"
    closed = [slug for slug, fail_mode in gates if fail_mode == "closed"]

    lines = [
        f"[jev-gates] {len(gates)} Jev gates are active on this session via preToolUse hooks "
        f"(mode={mode}).",
        "If a tool call is denied with a '[jev: <gate>]' reason, that is a deliberate policy "
        "decision, not a transient error. Address the stated reason or explain why the call is "
        "necessary anyway. Do not attempt to route around it with a different tool.",
    ]
    if closed:
        lines.append(
            "Fail-closed gates (these block when they cannot be evaluated): " + ", ".join(sorted(closed)) + "."
        )
    if mode == "fixture":
        lines.append(
            "TYPESAFE_API_KEY is not set, so gates answer from recorded fixtures. Fixture-sourced "
            "blocks surface as a permission prompt rather than a hard denial, because a recorded "
            "answer is not live evidence."
        )

    emit({"additionalContext": " ".join(lines)})
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
