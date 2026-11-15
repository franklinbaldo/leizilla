"""Fakes for the batched harvest upload (ADR-0016), shared by harvest tests."""

from typing import Any, Dict, List
from unittest.mock import MagicMock

from leizilla.publisher import RawCapture


def batch_ok(pub: MagicMock, **fields: Any) -> MagicMock:
    """Make ``pub.upload_raw_batch`` succeed for every capture of every flush."""

    def _upload(
        item_id: str, captures: List[RawCapture], index_cache: Any = None
    ) -> List[Dict[str, Any]]:
        return [{"success": True, "item_id": item_id, **fields} for _ in captures]

    pub.upload_raw_batch.side_effect = _upload
    pub.request_derive.return_value = True
    return pub


def uploaded_captures(pub: MagicMock) -> List[RawCapture]:
    """Every capture handed to ``pub.upload_raw_batch``, in flush order."""
    return [
        capture
        for call in pub.upload_raw_batch.call_args_list
        for capture in call.args[1]
    ]
