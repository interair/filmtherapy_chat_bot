from __future__ import annotations

from typing import Optional

from ..container import container


# Centralized helpers for compact callback data encoding/decoding.
# This keeps router modules smaller and avoids scattering mapping logic.


async def _get_locations_list() -> list[str]:
    """Return a stable list of location names used for compact encoding.
    Falls back to built-in defaults if repository is unavailable.
    """
    try:
        models = await container.location_repository().get_all()
        locs = [l.name for l in models]
        if locs:
            return locs
    except Exception:
        pass
    # Fallback to built-in defaults to maintain deterministic encoding
    from ..services.calendar_service import LOCATIONS as DEFAULT_LOCS
    return list(DEFAULT_LOCS)


def encode_stype(stype: str) -> str:
    mapping = {
        "Очно": "F",           # Face-to-face
        "Песочная терапия": "S",  # Sand therapy
        "Онлайн": "O",         # Online
    }
    return mapping.get(stype, "F")


def decode_stype(code: str) -> str:
    rev = {
        "F": "Очно",
        "S": "Песочная терапия",
        "O": "Онлайн",
    }
    return rev.get(code, "Очно")


async def encode_loc(loc: Optional[str]) -> str:
    if not loc or loc == "none":
        return "N"  # None/Online
    locs = await _get_locations_list()
    try:
        idx = locs.index(loc)
        return str(idx)
    except ValueError:
        return "N"


async def decode_loc(code: str) -> Optional[str]:
    if code == "N":
        return None
    locs = await _get_locations_list()
    try:
        idx = int(code)
    except Exception:
        return None
    if 0 <= idx < len(locs):
        return locs[idx]
    return None
