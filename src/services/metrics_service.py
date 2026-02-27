from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

from .db import get_db, DB


@dataclass
class DailySummary:
    date: str
    new_users: int
    active_users: int


class MetricsRepository:
    """Firestore-backed repository for telemetry/metrics.

    Collections:
      - metrics_users: user documents keyed by user_id
      - metrics_daily: daily aggregate documents keyed by YYYY-MM-DD
          fields: new_users [array:string], active_users [array:string]
          subcollection features: documents keyed by feature_key with {count:int}
    """

    def __init__(self, db: Optional[DB] = None) -> None:
        self.db = db or get_db()
        self.users_col = self.db.collection("metrics_users")
        self.daily_col = self.db.collection("metrics_daily")

    # Low-level mutators used by the service
    async def add_new_user(self, user_id: int, date_str: str, demographics: Optional[Dict[str, Any]] = None) -> None:
        uid = str(user_id)
        # Create/update user record
        await self.users_col.document(uid).set(
            {
                "first_start": date_str,
                "demographics": demographics or {},
            },
            merge=True,
        )
        # Update daily aggregates
        await self.daily_col.document(date_str).set(
            {
                "new_users": DB.array_union([uid]),
                "active_users": DB.array_union([uid]),
            },
            merge=True,
        )

    async def add_active(self, user_id: int, date_str: str) -> None:
        uid = str(user_id)
        await self.daily_col.document(date_str).set(
            {"active_users": DB.array_union([uid])}, merge=True
        )

    async def inc_feature(self, date_str: str, feature_key: str, by: int = 1) -> None:
        # Sanitize feature_key to avoid Firestore path issues with special characters
        sanitized_key = feature_key.replace("/", "_").replace(":", "_")
        feat_ref = self.daily_col.document(date_str).collection("features").document(sanitized_key)

        async def _tx(tx) -> None:
            # Begin transaction by using the transaction-bound get
            snap = await tx.get(feat_ref)
            current = int(snap.get("count")) if getattr(snap, "exists", False) and snap.get("count") is not None else 0
            tx.set(feat_ref, {"count": current + int(by)}, merge=False)

        await self.db.run_transaction(_tx)

    async def update_demographics(self, user_id: int, demographics: Dict[str, Any]) -> None:
        uid = str(user_id)
        clean = {k: v for k, v in demographics.items() if v is not None}
        if not clean:
            return
        await self.users_col.document(uid).set({"demographics": clean}, merge=True)

    # Reads
    async def get(self) -> Dict[str, Any]:
        users: Dict[str, Any] = {}
        async for doc in self.users_col.stream():
            users[doc.id] = doc.to_dict() or {}

        daily: Dict[str, Any] = {}
        async for day_doc in self.daily_col.stream():
            rec = day_doc.to_dict() or {}
            # Load feature usage subcollection
            feats: Dict[str, int] = {}
            async for fdoc in self.daily_col.document(day_doc.id).collection("features").stream():
                d = fdoc.to_dict() or {}
                feats[fdoc.id] = int(d.get("count", 0))
            if feats:
                rec["feature_usage"] = feats
            daily[day_doc.id] = {
                "new_users": rec.get("new_users", []) or [],
                "active_users": rec.get("active_users", []) or [],
                "feature_usage": rec.get("feature_usage", {}),
            }

        return {"users": users, "daily": daily}


class MetricsService:
    def __init__(self, repo: MetricsRepository) -> None:
        if repo is None:
            raise ValueError("MetricsService requires repository to be provided via DI")
        self._repo = repo

    @staticmethod
    def _today_str(dt: Optional[datetime] = None) -> str:
        if dt is None:
            dt = datetime.now(timezone.utc)
        return dt.astimezone(timezone.utc).date().isoformat()

    async def record_start(self, user_id: int, language_code: Optional[str] = None, username: Optional[str] = None, first_name: Optional[str] = None, last_name: Optional[str] = None) -> None:
        today = self._today_str()
        demographics = {
            "lang": language_code,
            "username": username,
            "first_name": first_name,
            "last_name": last_name,
        }
        await self._repo.add_new_user(user_id=user_id, date_str=today, demographics={k: v for k, v in demographics.items() if v})
        await self._repo.inc_feature(today, "command:/start")

    async def record_interaction(self, user_id: int, feature_key: str) -> None:
        today = self._today_str()
        await self._repo.add_active(user_id=user_id, date_str=today)
        await self._repo.inc_feature(today, feature_key)

    async def record_demographics(self, user_id: int, demographics: Dict[str, Any]) -> None:
        await self._repo.update_demographics(user_id, demographics)

    async def daily_summaries(self, days: int = 14) -> List[DailySummary]:
        data = await self._repo.get()
        daily: Dict[str, Any] = data.get("daily", {})
        dates = sorted(daily.keys())
        # Get last N days including today
        today = datetime.now(timezone.utc).date()
        want = [(today - timedelta(days=i)).isoformat() for i in range(days)]
        out: List[DailySummary] = []
        for d in reversed(want):  # chronological ascending
            day = daily.get(d, {"new_users": [], "active_users": []})
            out.append(DailySummary(date=d, new_users=len(day.get("new_users", [])), active_users=len(day.get("active_users", []))))
        return list(reversed(out))

    async def feature_usage(self, days: int = 7, top_n: int = 10) -> List[Tuple[str, int]]:
        data = await self._repo.get()
        daily: Dict[str, Any] = data.get("daily", {})
        today = datetime.now(timezone.utc).date()
        want = {(today - timedelta(days=i)).isoformat() for i in range(days)}
        agg: Dict[str, int] = {}
        for d, rec in daily.items():
            if d in want:
                feats = rec.get("feature_usage", {})
                for k, v in feats.items():
                    agg[k] = agg.get(k, 0) + int(v)
        return sorted(agg.items(), key=lambda x: x[1], reverse=True)[:top_n]

    async def demographics(self) -> Dict[str, Dict[str, int]]:
        data = await self._repo.get()
        users: Dict[str, Any] = data.get("users", {})
        langs: Dict[str, int] = {}
        for _, rec in users.items():
            lang = (rec.get("demographics") or {}).get("lang") or "unknown"
            langs[lang] = langs.get(lang, 0) + 1
        return {"languages": dict(sorted(langs.items(), key=lambda x: x[1], reverse=True))}

    async def retention_next_day(self, days: int = 14) -> List[Tuple[str, float]]:
        """Compute next-day retention per cohort day: percent of new users on day D who are active on D+1."""
        data = await self._repo.get()
        daily: Dict[str, Any] = data.get("daily", {})
        today = datetime.now(timezone.utc).date()
        out: List[Tuple[str, float]] = []
        for i in range(days, 0, -1):
            d = (today - timedelta(days=i)).isoformat()
            d_next = (today - timedelta(days=i - 1)).isoformat()
            nu = set(daily.get(d, {}).get("new_users", []) or [])
            if not nu:
                out.append((d, 0.0))
                continue
            active_next = set(daily.get(d_next, {}).get("active_users", []) or [])
            rate = 100.0 * (len(nu & active_next) / len(nu)) if nu else 0.0
            out.append((d, round(rate, 1)))
        return out

    async def today_overview(self) -> Dict[str, Any]:
        today = self._today_str()
        data = await self._repo.get()
        day = data.get("daily", {}).get(today, {})
        return {
            "date": today,
            "new_users": len(day.get("new_users", []) or []),
            "active_users": len(day.get("active_users", []) or []),
        }
