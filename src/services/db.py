from __future__ import annotations

import asyncio
import logging
from typing import Any, Callable, Optional

from google.cloud import firestore
from google.cloud.firestore_v1.async_transaction import async_transactional

from .firestore_client import get_async_client

logger = logging.getLogger(__name__)


class DB:
    """Tiny helper around Firestore to decouple direct SDK usage from app code.

    This is intentionally minimal: we only expose what we use.
    """

    def __init__(self, project_id: Optional[str] = None) -> None:
        self._client = get_async_client(project_id)

    # Shortcuts
    def collection(self, name: str) -> firestore.AsyncCollectionReference:
        return self._client.collection(name)

    @property
    def client(self) -> firestore.AsyncClient:
        return self._client

    # Transactions
    async def run_transaction(self, func: Callable[[firestore.AsyncTransaction], Any]) -> Any:
        @async_transactional
        async def _wrapper(tx: firestore.AsyncTransaction) -> Any:
            # Handle both async and sync functions if needed
            res = func(tx)
            if asyncio.iscoroutine(res):
                return await res
            return res

        try:
            return await _wrapper(self._client.transaction())
        except Exception:
            logger.exception("Firestore transaction failed")
            raise

    # Array operations
    @staticmethod
    def array_union(values: list[Any]) -> firestore.ArrayUnion:
        return firestore.ArrayUnion(values)


# Convenience singletons/utilities
_db_singleton: Optional[DB] = None


def get_db() -> DB:
    global _db_singleton
    if _db_singleton is None:
        _db_singleton = DB()
    return _db_singleton
