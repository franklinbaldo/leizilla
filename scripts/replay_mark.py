"""Replay a collected mark run through the current converter (offline, no API).

A real run leaves ``manifest.json`` (the plan, the texts) and the raw batch results
(``raw/<batch>.jsonl`` from ``collect``, or the batch results file itself). This feeds
the SAME model responses to ``teacher_mark.collect_mark`` with the code as it is now, so
a converter change can be judged on real answers without paying for them again.

    uv run scripts/replay_mark.py --manifest MANIFEST.json --raw RAW_DIR_OR_FILE \\
        --out OUT_DIR
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path
from typing import Any, Iterator, Optional

from leizilla import teacher_mark as tm


class _Batches:
    def __init__(self, by_batch: dict[str, list[dict[str, Any]]], fallback: list[Any]):
        self._by = by_batch
        self._all = fallback

    def results(self, batch_id: str) -> Iterator[dict[str, Any]]:
        yield from self._by.get(batch_id, self._all)


class _Messages:
    def __init__(self, batches: _Batches) -> None:
        self.batches = batches


class ReplayClient:
    """Plays ``client.messages.batches.results`` from raw result lines."""

    def __init__(self, raw: Path) -> None:
        files = sorted(raw.glob("*.jsonl")) if raw.is_dir() else [raw]
        by_batch: dict[str, list[dict[str, Any]]] = {}
        everything: list[dict[str, Any]] = []
        for path in files:
            lines = [
                json.loads(line)
                for line in path.read_text(encoding="utf-8").splitlines()
                if line.strip()
            ]
            by_batch[path.stem] = lines
            everything.extend(lines)
        self.messages = _Messages(_Batches(by_batch, everything))


def replay(manifest_path: Path, raw: Path, out_dir: Path) -> dict[str, Any]:
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    return tm.collect_mark(ReplayClient(raw), manifest, out_dir)


def main(argv: Optional[list[str]] = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--manifest", type=Path, required=True)
    parser.add_argument("--raw", type=Path, required=True)
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    summary = replay(args.manifest, args.raw, args.out)
    print(
        f"states {summary['states']}; marks used {summary['marks_used']}/"
        f"{summary['marks_answered']}; suspects {summary['suspects_by_type']}"
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
