#!/usr/bin/env python3
"""Mine Copilot CLI usage telemetry into a redacted, publishable waste baseline.

Reads the local Copilot CLI session store, runs the SQL in telemetry/queries/,
enforces a publication allowlist, and writes an aggregate report.

    python3 telemetry/mine_waste.py
    python3 telemetry/mine_waste.py --window '-7 days' --stdout

This repository is public. Nothing that identifies a repo, path, branch, session,
or customer may reach an artifact, so every emitted cell is checked against
ALLOWED_COLUMNS and scanned by looks_identifying() before it is written.
"""
from __future__ import annotations

import argparse
import json
import re
import sqlite3
import sys
from datetime import datetime
from pathlib import Path
from typing import Any
from zoneinfo import ZoneInfo

SYD = ZoneInfo("Australia/Sydney")

REPO_ROOT = Path(__file__).resolve().parent.parent
QUERY_DIR = Path(__file__).resolve().parent / "queries"
REPORT_DIR = Path(__file__).resolve().parent / "reports"
DEFAULT_DB = Path.home() / ".copilot" / "session-store.db"

# Only queries whose source is the local store can be run by this script.
# The 0x-prefixed cloud queries are documented for reproduction via the
# `session_store_sql` tool and are intentionally not executed here.
LOCAL_QUERIES = [
    "01-cost-by-model-effort.sql",
    "02-initiator-split.sql",
    "03-token-shape-and-cache.sql",
    "04-session-cost-concentration.sql",
    "05-latency-profile.sql",
    "06-main-vs-subagent.sql",
]

# Publication allowlist. A column not named here never reaches an artifact.
ALLOWED_COLUMNS = {
    # dimensions
    "model", "reasoning_effort", "initiator", "lane", "category", "tool_name", "rank",
    # volumes
    "requests", "calls", "sessions", "failures",
    "duplicated_argument_sets", "total_calls_in_those_sets", "wasted_repeat_calls",
    # cost
    "aiu", "aiu_per_request", "pct_of_aiu", "cumulative_pct",
    # tokens
    "input_mtok", "cache_read_mtok", "cache_write_mtok", "output_mtok",
    "reasoning_mtok", "cache_pct", "input_output_ratio",
    # time
    "avg_duration_ms", "avg_ttft_ms", "max_duration_ms", "total_seconds", "avg_ms",
    # rates
    "fail_pct",
}

_UUID = re.compile(r"[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}", re.I)
_HOME_PATH = re.compile(r"(^[~/])|(/Users/)|(/home/)|(\\Users\\)")

# Headline claims are ignored below this many requests, so a handful of stray
# calls cannot masquerade as the most expensive configuration.
MIN_SAMPLE = 50


def looks_identifying(value: Any) -> bool:
    """True if a value could identify a person, machine, repo, or session."""
    if not isinstance(value, str):
        return False
    if _UUID.search(value):
        return True
    if _HOME_PATH.search(value):
        return True
    return len(value) > 64


class RedactionError(RuntimeError):
    """Raised when a query result would leak something publishable-unsafe."""


def check_rows(name: str, rows: list[dict[str, Any]]) -> None:
    for row in rows:
        for column, value in row.items():
            if column not in ALLOWED_COLUMNS:
                raise RedactionError(
                    f"{name}: column {column!r} is not in ALLOWED_COLUMNS. "
                    "Add it deliberately or drop it from the query."
                )
            if looks_identifying(value):
                raise RedactionError(
                    f"{name}: value in column {column!r} looks identifying "
                    "(uuid, home path, or over-long string)."
                )


def run_query(conn: sqlite3.Connection, path: Path, window: str) -> list[dict[str, Any]]:
    sql = path.read_text(encoding="utf-8")
    cur = conn.execute(sql, {"window": window})
    columns = [d[0] for d in cur.description]
    return [dict(zip(columns, row)) for row in cur.fetchall()]


def render_table(rows: list[dict[str, Any]]) -> str:
    if not rows:
        return "_No rows._\n"
    columns = list(rows[0].keys())
    out = ["| " + " | ".join(columns) + " |",
           "| " + " | ".join("---" for _ in columns) + " |"]
    for row in rows:
        out.append("| " + " | ".join("" if row[c] is None else str(row[c]) for c in columns) + " |")
    return "\n".join(out) + "\n"


def derive_headlines(results: dict[str, list[dict[str, Any]]]) -> list[tuple[str, str]]:
    """Pull the handful of numbers that actually drive the gate ranking."""
    headlines: list[tuple[str, str]] = []

    cost = results.get("01-cost-by-model-effort", [])
    if cost:
        top = cost[0]
        headlines.append((
            "Dominant model/effort pair",
            f"`{top['model']} @ {top['reasoning_effort']}` = {top['pct_of_aiu']}% of AI Units "
            f"({top['requests']} requests, {top['aiu_per_request']} AIU/req)",
        ))
        priciest = max(
            (r for r in cost if (r["requests"] or 0) >= MIN_SAMPLE),
            key=lambda r: r["aiu_per_request"] or 0,
            default=None,
        )
        if priciest is not None:
            headlines.append((
                "Most expensive per request",
                f"`{priciest['model']} @ {priciest['reasoning_effort']}` = "
                f"{priciest['aiu_per_request']} AIU/req "
                f"({priciest['requests']} requests)",
            ))

    init = {r["initiator"]: r for r in results.get("02-initiator-split", [])}
    if "agent" in init and "user" in init:
        ratio = init["agent"]["requests"] / max(init["user"]["requests"], 1)
        headlines.append((
            "Autonomous turns per user turn",
            f"{ratio:.1f} ({init['agent']['requests']} agent vs {init['user']['requests']} user requests)",
        ))

    tok = results.get("03-token-shape-and-cache", [])
    if tok:
        headlines.append((
            "Cache hit rate",
            f"{tok[0]['cache_pct']}% of input tokens served from cache",
        ))
        headlines.append((
            "Input:output token ratio",
            f"{tok[0]['input_output_ratio']}:1 — cost is context, not generation",
        ))

    conc = results.get("04-session-cost-concentration", [])
    if conc:
        headlines.append((
            "Spend concentration",
            f"top session = {conc[0]['pct_of_aiu']}% of all AI Units; "
            f"top {len(conc)} = {conc[-1]['cumulative_pct']}%",
        ))

    lanes = {r["lane"]: r for r in results.get("06-main-vs-subagent", [])}
    if "subagent" in lanes:
        total = sum(r["aiu"] for r in lanes.values()) or 1
        headlines.append((
            "Subagent share of spend",
            f"{lanes['subagent']['aiu'] / total * 100:.1f}% of AI Units ran in delegated lanes",
        ))

    return headlines


def build_report(results: dict[str, list[dict[str, Any]]], window: str, as_of: str) -> str:
    headlines = derive_headlines(results)
    parts = [
        f"# Copilot CLI waste baseline\n",
        f"**As-of:** {as_of}  ",
        f"**Window:** `{window}`  ",
        "**Source:** local Copilot CLI session store (`assistant_usage_events`), one developer's machine  ",
        "**Redaction:** aggregate-only; enforced by `ALLOWED_COLUMNS` in `mine_waste.py`\n",
        "---\n",
        "## Headlines\n",
    ]
    if headlines:
        parts.append("| Measure | Value |")
        parts.append("| --- | --- |")
        for label, value in headlines:
            parts.append(f"| {label} | {value} |")
        parts.append("")
    else:
        parts.append("_No headline metrics could be derived._\n")

    parts.append("---\n")
    parts.append("## Detail\n")
    for name in LOCAL_QUERIES:
        key = name.removesuffix(".sql")
        title = key.split("-", 1)[1].replace("-", " ")
        parts.append(f"### {key[:2]} — {title}\n")
        parts.append(render_table(results.get(key, [])))
        parts.append("")

    parts.append("---\n")
    parts.append(
        "## Caveats\n\n"
        "- Single machine, single developer. Directional, not a population estimate.\n"
        "- `total_nano_aiu` is billed AI Units, which already fold in per-model multipliers;\n"
        "  it is not a dollar figure.\n"
        "- Tool-level findings (call mix, redundancy, failure rates, shell intent) come from the\n"
        "  cloud session store and are reproduced via the `session_store_sql` tool using\n"
        "  `queries/07`-`queries/09`. They are not produced by this script.\n"
    )
    return "\n".join(parts)


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--db", type=Path, default=DEFAULT_DB, help=f"session store (default: {DEFAULT_DB})")
    ap.add_argument("--window", default="-30 days", help="SQLite date modifier (default: '-30 days')")
    ap.add_argument("--out-dir", type=Path, default=REPORT_DIR)
    ap.add_argument("--stdout", action="store_true", help="print the report instead of writing files")
    args = ap.parse_args()

    if not args.db.exists():
        print(f"error: session store not found at {args.db}", file=sys.stderr)
        return 1

    # Read-only: telemetry mining must never mutate the user's session store.
    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    try:
        results: dict[str, list[dict[str, Any]]] = {}
        for name in LOCAL_QUERIES:
            path = QUERY_DIR / name
            if not path.exists():
                print(f"error: missing query {path}", file=sys.stderr)
                return 1
            key = name.removesuffix(".sql")
            rows = run_query(conn, path, args.window)
            check_rows(key, rows)
            results[key] = rows
    finally:
        conn.close()

    now = datetime.now(SYD)
    as_of = now.strftime("%Y-%m-%d %H:%M %Z")
    report = build_report(results, args.window, as_of)

    if args.stdout:
        print(report)
        return 0

    args.out_dir.mkdir(parents=True, exist_ok=True)
    stamp = now.strftime("%Y-%m-%d")
    md_path = args.out_dir / f"baseline-{stamp}.md"
    json_path = args.out_dir / f"baseline-{stamp}.json"

    md_path.write_text(report, encoding="utf-8")
    json_path.write_text(
        json.dumps(
            {
                "as_of": as_of,
                "window": args.window,
                "source": "local session store (assistant_usage_events)",
                "redaction": "aggregate-only; ALLOWED_COLUMNS enforced",
                "headlines": [{"measure": m, "value": v} for m, v in derive_headlines(results)],
                "results": results,
            },
            indent=2,
            ensure_ascii=False,
        )
        + "\n",
        encoding="utf-8",
    )
    print(f"wrote {md_path}")
    print(f"wrote {json_path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
