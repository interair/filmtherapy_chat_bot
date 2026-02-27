from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from google.cloud import firestore


@lru_cache(maxsize=1)
def get_async_client(project_id: Optional[str] = None) -> firestore.AsyncClient:
    """Return a cached asynchronous Firestore client."""
    project = _get_project_id(project_id)
    return firestore.AsyncClient(project=project) if project else firestore.AsyncClient()


def _get_project_id(project_id: Optional[str] = None) -> Optional[str]:
    return (
        project_id
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
    )
