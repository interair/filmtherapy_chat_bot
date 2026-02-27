from __future__ import annotations

import logging
from typing import Any, Callable, Optional

from google.cloud import firestore

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
        tx = self._client.transaction()
        # Use context manager API compatible with google-cloud-firestore v2+
        try:
            async with tx:
                return await func(tx)
        except Exception:
            logger.exception("Firestore transaction failed")
            # Context manager will handle rollback automatically where applicable
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
