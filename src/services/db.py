from __future__ import annotations

from typing import Any, Callable, Optional
import logging

from google.cloud import firestore

from .firestore_client import get_client

logger = logging.getLogger(__name__)


class DB:
    """Tiny helper around Firestore to decouple direct SDK usage from app code.

    This is intentionally minimal: we only expose what we use.
    """

    def __init__(self, project_id: Optional[str] = None) -> None:
        self._client = get_client(project_id)

    # Shortcuts
    def collection(self, name: str) -> firestore.CollectionReference:
        return self._client.collection(name)

    @property
    def client(self) -> firestore.Client:
        return self._client

    # Transactions
    def run_transaction(self, func: Callable[[firestore.Transaction], Any]) -> Any:
        tx = self._client.transaction()
        try:
            # Firestore requires transaction to be begun before it's passed into API calls
            tx.begin()
            result = func(tx)
            tx.commit()
            return result
        except Exception as e:
            logger.exception("Firestore transaction failed; rolling back")
            try:
                tx.rollback()
            except Exception:
                logger.debug("Firestore transaction rollback failed", exc_info=True)
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
