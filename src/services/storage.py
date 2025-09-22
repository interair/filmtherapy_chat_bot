from __future__ import annotations

import logging
import os
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Generator

import orjson as _orjson

logger = logging.getLogger(__name__)

DATA_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data")

os.makedirs(DATA_DIR, exist_ok=True)

QUIZ_PATH = os.path.join(DATA_DIR, "quiz.json")

def read_json(path: str | Path, default: Any) -> Any:
    filepath = Path(path)
    if not filepath.exists():
        return default
    try:
        with open(filepath, "rb") as f:
            return _orjson.loads(f.read())
    except Exception:
        logger.exception("read_json: orjson read failed for %s", filepath)
        return default


def write_json(path: str | Path, data: Any) -> None:
    filepath = Path(path)
    storage = Storage(filepath.parent)
    with storage._atomic_write(filepath) as tmp_path:
        with open(tmp_path, "wb") as f:
            f.write(_orjson.dumps(data, option=(_orjson.OPT_INDENT_2 | _orjson.OPT_NON_STR_KEYS)))


# Simple schemas stored as plain dicts

class Storage:
    def __init__(self, data_dir: Path | None = None):
        if data_dir is None:
            data_dir = Path(__file__).resolve().parents[1] / "data"
        self.data_dir = Path(data_dir)
        self.data_dir.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def _atomic_write(self, filepath: Path) -> Generator[Path, None, None]:
        tmp_path = filepath.with_suffix(filepath.suffix + '.tmp')
        try:
            yield tmp_path
            os.replace(tmp_path, filepath)
        except Exception:
            logger.exception("Atomic write failed for %s", filepath)
            if tmp_path.exists():
                tmp_path.unlink()
            raise
