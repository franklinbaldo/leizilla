# /// script
# requires-python = ">=3.12"
# dependencies = ["okf-parser>=0.45.9"]
# ///
"""Validate and inspect the canonical Leizilla project DAG from authored OKF."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any

from okf_parser import load_bundle

MAP_PATH = "docs/okf/project-dag.md"
DEFAULT_STATUSES = {
    "open",
    "active",
    "blocked",
    "narrowed",
    "completed",
    "absorbed",
    "superseded",
    "abandoned",
}
DEFAULT_KINDS = {"root", "objective", "workstream", "gate", "research"}
DEFAULT_KR_STATUSES = {"open", "active", "blocked", "met", "missed"}
LIVE = {"open", "active", "blocked", "narrowed"}
LIVE_KR = {"open", "active", "blocked"}


def _require_text(obj: dict[str, Any], key: str, context: str) -> str:
    value = obj.get(key)
    if not isinstance(value, str) or not value.strip():
        raise SystemExit(f"{context} missing non-empty {key}")
    return value.strip()


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args()

    root = Path(__file__).resolve().parent.parent
    bundle = load_bundle(root)
    frame = (
        bundle.concepts.filter(bundle.concepts.path == MAP_PATH)
        .select("path", "concept_type", "frontmatter_json")
        .execute()
    )
    rows = frame.to_dict(orient="records")
    if len(rows) != 1:
        raise SystemExit(f"expected one canonical project DAG, found {len(rows)}")

    row = rows[0]
    if row["concept_type"] != "Project Map":
        raise SystemExit(f"{MAP_PATH} must remain a Project Map")

    fm = json.loads(row["frontmatter_json"])
    fronts = fm.get("fronts")
    if not isinstance(fronts, list) or not fronts:
        raise SystemExit("project DAG has no fronts")

    known_statuses = set(fm.get("known_statuses") or DEFAULT_STATUSES)
    known_kinds = set(fm.get("known_kinds") or DEFAULT_KINDS)
    known_kr_statuses = set(fm.get("known_kr_statuses") or DEFAULT_KR_STATUSES)

    ids: list[str] = []
    kr_ids: list[str] = []
    for front in fronts:
        if not isinstance(front, dict):
            raise SystemExit("every front must be an object")
        front_id = _require_text(front, "id", "front")
        kind = _require_text(front, "kind", front_id)
        status = _require_text(front, "status", front_id)
        _require_text(front, "objective", front_id)
        _require_text(front, "origin", front_id)
        _require_text(front, "next_action", front_id)

        if status not in known_statuses:
            raise SystemExit(f"unknown status {status} for {front_id}")
        if kind not in known_kinds:
            raise SystemExit(f"unknown kind {kind} for {front_id}")
        ids.append(front_id)

        key_results = front.get("key_results", [])
        if not isinstance(key_results, list):
            raise SystemExit(f"key_results must be a list for {front_id}")
        for kr in key_results:
            if not isinstance(kr, dict):
                raise SystemExit(f"key result entry must be an object for {front_id}")
            kr_id = _require_text(kr, "id", f"{front_id} key result")
            kr_status = _require_text(kr, "status", f"{front_id}::{kr_id}")
            _require_text(kr, "metric", f"{front_id}::{kr_id}")
            _require_text(kr, "current", f"{front_id}::{kr_id}")
            _require_text(kr, "target", f"{front_id}::{kr_id}")
            if kr_status not in known_kr_statuses:
                raise SystemExit(
                    f"unknown key-result status {kr_status} for {front_id}::{kr_id}"
                )
            if kr_status in LIVE_KR:
                _require_text(kr, "next_action", f"{front_id}::{kr_id}")
            kr_ids.append(kr_id)

    if len(ids) != len(set(ids)):
        raise SystemExit("duplicate project front ids")
    if len(kr_ids) != len(set(kr_ids)):
        raise SystemExit("duplicate key-result ids")
    overlap = sorted(set(ids) & set(kr_ids))
    if overlap:
        raise SystemExit("ids reused across front/KR namespaces: " + ", ".join(overlap))

    by = {front["id"]: front for front in fronts}
    for front in fronts:
        front_id = front["id"]
        parents = front.get("parents", [])
        if not isinstance(parents, list):
            raise SystemExit(f"parents must be a list for {front_id}")
        for parent in parents:
            if parent == front_id:
                raise SystemExit(f"self-parent: {front_id}")
            if parent not in by:
                raise SystemExit(f"unknown parent {parent} for {front_id}")

    visiting: set[str] = set()
    done: set[str] = set()

    def visit(node_id: str) -> None:
        if node_id in done:
            return
        if node_id in visiting:
            raise SystemExit(f"cycle detected at {node_id}")
        visiting.add(node_id)
        for parent in by[node_id].get("parents", []):
            visit(parent)
        visiting.remove(node_id)
        done.add(node_id)

    for front_id in ids:
        visit(front_id)

    children = {front_id: [] for front_id in ids}
    for front in fronts:
        for parent in front.get("parents", []):
            children[parent].append(front["id"])

    live = []
    for front in fronts:
        if front["status"] not in LIVE:
            continue
        live.append(
            {
                "id": front["id"],
                "kind": front["kind"],
                "status": front["status"],
                "parents": front.get("parents", []),
                "next_action": front["next_action"],
                "issues": front.get("issues", []),
                "live_key_results": [
                    {
                        "id": kr["id"],
                        "status": kr["status"],
                        "target": kr["target"],
                        "next_action": kr.get("next_action"),
                    }
                    for kr in front.get("key_results", [])
                    if kr["status"] in LIVE_KR
                ],
            }
        )

    payload = {
        "source": MAP_PATH,
        "state_model": fm.get("state_model"),
        "front_count": len(fronts),
        "key_result_count": len(kr_ids),
        "live_count": len(live),
        "blocked_count": sum(front["status"] == "blocked" for front in fronts),
        "roots": [front_id for front_id in ids if not by[front_id].get("parents")],
        "leaves": [front_id for front_id in ids if not children[front_id]],
        "live_leaves": [
            front_id
            for front_id in ids
            if not children[front_id] and by[front_id]["status"] in LIVE
        ],
        "live": live,
    }

    if args.json:
        print(json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True))
    else:
        print(
            f"{payload['front_count']} fronts; "
            f"{payload['key_result_count']} KRs; "
            f"{payload['live_count']} live; "
            f"{payload['blocked_count']} blocked"
        )
        print("live leaves:")
        for front_id in payload["live_leaves"]:
            front = by[front_id]
            parents = ", ".join(front.get("parents", [])) or "ROOT"
            print(
                f"- {front['status']}: {front_id} "
                f"[{front['kind']}] <- {parents}"
            )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
