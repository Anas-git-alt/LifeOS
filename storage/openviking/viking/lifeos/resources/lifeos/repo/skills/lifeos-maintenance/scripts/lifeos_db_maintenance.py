#!/usr/bin/env python3
"""LifeOS SQLite maintenance helper.

Safe defaults:
- inspection is read-only
- cleanup is dry-run unless --apply is provided
- only known test/smoke patterns are targeted by default
"""

from __future__ import annotations

import argparse
import json
import sqlite3
from dataclasses import dataclass
from pathlib import Path
from typing import Iterable


DEFAULT_TEST_PREFIXES = ("smoke-", "proposal-", "temp-")
DEFAULT_TEST_SOURCES = ("smoke", "smoke_proposal", "temp_check", "integration_test")
DEFAULT_TEST_CREATORS = ("smoke", "assistant", "pytest", "test")


@dataclass
class CleanupPlan:
    job_ids: list[int]
    agent_names: list[str]


def connect_db(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.row_factory = sqlite3.Row
    return conn


def row_count(cur: sqlite3.Cursor, table: str) -> int:
    return int(cur.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


def quote_for_like(prefixes: Iterable[str]) -> str:
    parts = []
    for token in prefixes:
        parts.append(f"name LIKE '{token}%'")
    return " OR ".join(parts) if parts else "1=0"


def make_cleanup_plan(cur: sqlite3.Cursor, prefixes: tuple[str, ...]) -> CleanupPlan:
    like_jobs = quote_for_like(prefixes)
    like_agents = " OR ".join([f"agent_name LIKE '{prefix}%'" for prefix in prefixes]) or "1=0"
    like_sources = ", ".join([f"'{src}'" for src in DEFAULT_TEST_SOURCES])
    like_creators = ", ".join([f"'{creator}'" for creator in DEFAULT_TEST_CREATORS])

    job_rows = cur.execute(
        f"""
        SELECT id FROM scheduled_jobs
        WHERE ({like_jobs})
           OR ({like_agents})
           OR source IN ({like_sources})
           OR created_by IN ({like_creators})
        ORDER BY id
        """
    ).fetchall()
    job_ids = [int(r["id"]) for r in job_rows]

    agent_name_like = quote_for_like(prefixes)
    agent_rows = cur.execute(
        f"""
        SELECT name FROM agents
        WHERE ({agent_name_like})
           OR created_at IS NOT NULL AND description LIKE '%Smoke test%'
           OR created_at IS NOT NULL AND description LIKE '%Proposal agent%'
        ORDER BY id
        """
    ).fetchall()
    agent_names = [str(r["name"]) for r in agent_rows]

    return CleanupPlan(job_ids=job_ids, agent_names=agent_names)


def default_description(row: sqlite3.Row) -> str:
    target = f"#{row['target_channel']}" if row["target_channel"] else "its mapped channel"
    owner = row["agent_name"] or "system"
    return (
        f"{row['name']}: runs for agent '{owner}' on cron '{row['cron_expression']}' "
        f"in timezone '{row['timezone']}' and posts to {target}."
    )


def cmd_inspect(cur: sqlite3.Cursor) -> None:
    summary = {
        "scheduled_jobs": row_count(cur, "scheduled_jobs"),
        "agents": row_count(cur, "agents"),
        "pending_actions": row_count(cur, "pending_actions"),
        "audit_log": row_count(cur, "audit_log"),
        "job_run_logs": row_count(cur, "job_run_logs"),
    }
    print(json.dumps(summary, indent=2))
    print("\nJobs:")
    rows = cur.execute(
        """
        SELECT id, name, description, agent_name, source, created_by, cron_expression
        FROM scheduled_jobs ORDER BY id
        """
    ).fetchall()
    for row in rows:
        has_desc = bool((row["description"] or "").strip())
        print(
            f"- #{row['id']} {row['name']} | agent={row['agent_name']} "
            f"| source={row['source']} | created_by={row['created_by']} | desc={has_desc}"
        )


def cmd_cleanup(cur: sqlite3.Cursor, conn: sqlite3.Connection, apply: bool, prefixes: tuple[str, ...]) -> None:
    plan = make_cleanup_plan(cur, prefixes=prefixes)
    print("cleanup_plan", json.dumps({"job_ids": plan.job_ids, "agent_names": plan.agent_names}))
    if not apply:
        print("dry-run: no rows deleted. Re-run with --apply to commit.")
        return

    if plan.job_ids:
        q = ",".join(["?"] * len(plan.job_ids))
        cur.execute(f"DELETE FROM job_run_logs WHERE job_id IN ({q})", plan.job_ids)
        cur.execute(f"DELETE FROM scheduled_jobs WHERE id IN ({q})", plan.job_ids)

    if plan.agent_names:
        q = ",".join(["?"] * len(plan.agent_names))
        cur.execute(f"DELETE FROM agents WHERE name IN ({q})", plan.agent_names)

    cur.execute(
        """
        DELETE FROM pending_actions
        WHERE summary LIKE 'Create smoke-%'
           OR summary LIKE 'Create proposal-%'
           OR summary LIKE 'Create temp-%'
           OR result LIKE 'Created agent ''smoke-%'
           OR result LIKE 'Created agent ''proposal-%'
           OR result LIKE 'Created agent ''temp-%'
           OR result LIKE 'Created job #%smoke-%'
           OR result LIKE 'Created job #%proposal-%'
           OR result LIKE 'Created job #%temp-%'
        """
    )
    cur.execute(
        """
        DELETE FROM audit_log
        WHERE details LIKE '%smoke-%'
           OR details LIKE '%proposal-%'
           OR details LIKE '%temp-%'
        """
    )
    conn.commit()
    print("cleanup applied.")


def cmd_fill_descriptions(cur: sqlite3.Cursor, conn: sqlite3.Connection, apply: bool) -> None:
    rows = cur.execute(
        """
        SELECT id, name, description, agent_name, cron_expression, timezone, target_channel
        FROM scheduled_jobs ORDER BY id
        """
    ).fetchall()
    updates: list[tuple[str, int]] = []
    for row in rows:
        if (row["description"] or "").strip():
            continue
        updates.append((default_description(row), int(row["id"])))

    print(json.dumps({"jobs_missing_description": [job_id for _, job_id in updates]}, indent=2))
    if not apply:
        print("dry-run: no rows updated. Re-run with --apply to commit.")
        return
    if updates:
        cur.executemany("UPDATE scheduled_jobs SET description = ? WHERE id = ?", updates)
        conn.commit()
    print(f"updated {len(updates)} rows")


def main() -> int:
    parser = argparse.ArgumentParser(description="Maintain LifeOS production SQLite data safely.")
    parser.add_argument("--db", default="storage/lifeos.db", help="Path to lifeos.db")
    sub = parser.add_subparsers(dest="command", required=True)

    sub.add_parser("inspect", help="Show summary + jobs overview")

    cleanup = sub.add_parser("cleanup-test-artifacts", help="Delete smoke/proposal/temp test artifacts")
    cleanup.add_argument("--apply", action="store_true", help="Commit deletions (default is dry-run)")
    cleanup.add_argument(
        "--prefix",
        action="append",
        default=[],
        help="Additional test name prefixes (repeatable, e.g. --prefix scratch-)",
    )

    fill = sub.add_parser("fill-job-descriptions", help="Backfill missing job descriptions")
    fill.add_argument("--apply", action="store_true", help="Commit updates (default is dry-run)")

    args = parser.parse_args()
    db_path = Path(args.db)
    conn = connect_db(db_path)
    cur = conn.cursor()
    try:
        if args.command == "inspect":
            cmd_inspect(cur)
        elif args.command == "cleanup-test-artifacts":
            prefixes = tuple(DEFAULT_TEST_PREFIXES + tuple(args.prefix))
            cmd_cleanup(cur, conn, apply=bool(args.apply), prefixes=prefixes)
        elif args.command == "fill-job-descriptions":
            cmd_fill_descriptions(cur, conn, apply=bool(args.apply))
        return 0
    finally:
        conn.close()


if __name__ == "__main__":
    raise SystemExit(main())
