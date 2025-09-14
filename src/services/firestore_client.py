from __future__ import annotations

import os
from functools import lru_cache
from typing import Optional

from google.cloud import firestore


@lru_cache(maxsize=1)
def get_client(project_id: Optional[str] = None) -> firestore.Client:
    """Return a cached Firestore client.

    Project ID resolution order:
    - explicit project_id argument
    - GOOGLE_CLOUD_PROJECT / GCP_PROJECT / GCLOUD_PROJECT env vars
    - default application credentials project
    """
    project = (
        project_id
        or os.getenv("GOOGLE_CLOUD_PROJECT")
        or os.getenv("GCP_PROJECT")
        or os.getenv("GCLOUD_PROJECT")
    )
    return firestore.Client(project=project) if project else firestore.Client()
