# /// script
# requires-python = ">=3.12"
# dependencies = ["pyyaml>=6.0"]
# ///
"""Fail-closed hygiene checks for docs/okf/project-dag.md."""

from __future__ import annotations

from collections import Counter
from pathlib import Path
import sys

import yaml

ROOT = Path(__file__).resolve().parents[1]
DEFAULT_PATH = ROOT / "docs" / "okf" / "project-dag.md"


def _frontmatter(text: str) -> str:
    if not text.startswith("---\n"):
        raise ValueError("project DAG must start with YAML frontmatter")
    end = text.find("\n---\n", 4)
    if end < 0:
        raise ValueError("project DAG is missing closing frontmatter delimiter")
    return text[4:end]


def _duplicates(values: list[str]) -> list[str]:
    counts = Counter(values)
    return sorted(value for value, count in counts.items() if count > 1)


def validate(path: Path) -> dict[str, int]:
    raw = path.read_bytes()
    controls = {
        "carriage_return": raw.count(b"\r"),
        "tab": raw.count(b"\t"),
    }
    if any(controls.values()):
        raise ValueError(
            "forbidden control characters: "
            + ", ".join(f"{name}={count}" for name, count in controls.items() if count)
        )

    text = raw.decode("utf-8")
    data = yaml.safe_load(_frontmatter(text))
    if not isinstance(data, dict):
        raise ValueError("frontmatter must parse to a mapping")

    fronts = data.get("fronts")
    if not isinstance(fronts, list) or not fronts:
        raise ValueError("frontmatter fronts must be a non-empty list")

    front_ids: list[str] = []
    kr_ids: list[str] = []
    for front in fronts:
        if not isinstance(front, dict):
            raise ValueError("every front must be a mapping")
        front_id = front.get("id")
        if not isinstance(front_id, str) or not front_id:
            raise ValueError("every front must have a non-empty string id")
        front_ids.append(front_id)

        key_results = front.get("key_results", [])
        if not isinstance(key_results, list):
            raise ValueError(f"front {front_id}: key_results must be a list")
        for kr in key_results:
            if not isinstance(kr, dict):
                raise ValueError(f"front {front_id}: every KR must be a mapping")
            kr_id = kr.get("id")
            if not isinstance(kr_id, str) or not kr_id:
                raise ValueError(f"front {front_id}: every KR needs a non-empty id")
            kr_ids.append(kr_id)

    duplicate_fronts = _duplicates(front_ids)
    duplicate_krs = _duplicates(kr_ids)
    cross_kind = sorted(set(front_ids) & set(kr_ids))
    if duplicate_fronts:
        raise ValueError("duplicate front ids: " + ", ".join(duplicate_fronts))
    if duplicate_krs:
        raise ValueError("duplicate key-result ids: " + ", ".join(duplicate_krs))
    if cross_kind:
        raise ValueError(
            "ids reused across front/KR namespaces: " + ", ".join(cross_kind)
        )

    return {
        "fronts": len(front_ids),
        "key_results": len(kr_ids),
        "carriage_returns": controls["carriage_return"],
        "tabs": controls["tab"],
    }


def main() -> int:
    path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_PATH
    try:
        summary = validate(path)
    except (OSError, UnicodeError, ValueError, yaml.YAMLError) as exc:
        print(f"project-dag hygiene: FAIL: {exc}", file=sys.stderr)
        return 1

    print(
        "project-dag hygiene: PASS "
        f"fronts={summary['fronts']} key_results={summary['key_results']} "
        "controls=0"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
