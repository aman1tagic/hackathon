from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timedelta, timezone
from threading import Lock
from typing import Any
from uuid import uuid4


class InMemoryOcrStore:
    def __init__(self, ttl_minutes: int = 60) -> None:
        self._ttl = timedelta(minutes=ttl_minutes)
        self._items: dict[str, tuple[datetime, dict[str, Any]]] = {}
        self._lock = Lock()

    def put(self, ocr_response: dict[str, Any]) -> str:
        ocr_id = str(uuid4())
        expires_at = datetime.now(timezone.utc) + self._ttl
        with self._lock:
            self._items[ocr_id] = (expires_at, deepcopy(ocr_response))
            self._cleanup_locked()
        return ocr_id

    def get(self, ocr_id: str) -> dict[str, Any] | None:
        with self._lock:
            self._cleanup_locked()
            item = self._items.get(ocr_id)
            if item is None:
                return None
            return deepcopy(item[1])

    def _cleanup_locked(self) -> None:
        now = datetime.now(timezone.utc)
        expired = [ocr_id for ocr_id, (expires_at, _) in self._items.items() if expires_at <= now]
        for ocr_id in expired:
            self._items.pop(ocr_id, None)


ocr_store = InMemoryOcrStore()

