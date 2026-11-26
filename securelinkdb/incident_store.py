"""
Lightweight SQLite persistence store for SecureLink incidents and adult reviews.

Replaces the volatile process-local incident deque while preserving legacy
REST/WebSocket payload compatibility and adding V4 human-review metadata.
"""

from __future__ import annotations

import copy
import json
import os
import sqlite3
import threading
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

VALID_REVIEW_STATUSES = ("PENDING_REVIEW", "CONFIRMED", "DISMISSED")


def _utc_iso_now() -> str:
    return datetime.now(timezone.utc).isoformat()


class IncidentStore:
    """Thread-safe local SQLite store for flagged incidents and uncertain-review items."""

    def __init__(self, db_path: str):
        self.db_path = os.path.abspath(db_path)
        db_dir = os.path.dirname(self.db_path)
        if db_dir:
            os.makedirs(db_dir, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(self.db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        with self._lock:
            self._init_schema()

    def _init_schema(self) -> None:
        cur = self._conn.cursor()
        try:
            cur.execute("PRAGMA journal_mode=WAL;")
            cur.execute("PRAGMA synchronous=NORMAL;")
        except sqlite3.DatabaseError:
            pass
        cur.execute(
            """
            CREATE TABLE IF NOT EXISTS incidents (
                id TEXT PRIMARY KEY,
                device_id TEXT NOT NULL,
                score REAL NOT NULL,
                level TEXT NOT NULL,
                category TEXT NOT NULL,
                intent TEXT,
                transcript TEXT NOT NULL,
                original_transcript TEXT NOT NULL,
                normalized_transcript TEXT NOT NULL,
                transcription_status TEXT NOT NULL,
                transcription_reason TEXT,
                confidence_json TEXT NOT NULL,
                human_review_required INTEGER NOT NULL DEFAULT 0,
                review_status TEXT NOT NULL DEFAULT 'NONE',
                reviewer_notes TEXT NOT NULL DEFAULT '',
                reviewed_by TEXT,
                reviewed_at TEXT,
                created_at TEXT NOT NULL,
                created_ts REAL NOT NULL,
                audio INTEGER NOT NULL DEFAULT 1,
                audio_authorized INTEGER NOT NULL DEFAULT 0,
                audio_url TEXT,
                local_audio_url TEXT,
                lan_audio_url TEXT,
                audio_review_url TEXT,
                audio_file TEXT,
                audio_token_hash TEXT,
                video INTEGER NOT NULL DEFAULT 0,
                duration TEXT,
                source TEXT,
                relayed_by TEXT,
                payload_json TEXT NOT NULL
            )
            """
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_incidents_created_ts ON incidents (created_ts DESC)"
        )
        cur.execute(
            "CREATE INDEX IF NOT EXISTS idx_incidents_review_status ON incidents (review_status)"
        )
        self._conn.commit()

    def _row_to_dict(self, row: sqlite3.Row) -> Dict[str, Any]:
        payload: Dict[str, Any] = {}
        raw_json = row["payload_json"]
        if raw_json:
            try:
                loaded = json.loads(raw_json)
                if isinstance(loaded, dict):
                    payload = loaded
            except Exception:
                payload = {}

        try:
            confidence = json.loads(row["confidence_json"]) if row["confidence_json"] else {}
        except Exception:
            confidence = {}

        payload.setdefault("event_type", "incident")
        payload["id"] = row["id"]
        payload["device_id"] = row["device_id"]
        payload["score"] = float(row["score"])
        payload["level"] = row["level"]
        payload["category"] = row["category"]
        payload["intent"] = row["intent"]
        payload["transcript"] = row["transcript"]
        payload["original_transcript"] = row["original_transcript"]
        payload["normalized_transcript"] = row["normalized_transcript"]
        payload["transcription_status"] = row["transcription_status"]
        payload["transcription_reason"] = row["transcription_reason"]
        payload["confidence"] = confidence
        payload["human_review_required"] = bool(row["human_review_required"])
        payload["review_status"] = row["review_status"]
        payload["reviewer_notes"] = row["reviewer_notes"] or ""
        payload["reviewed_by"] = row["reviewed_by"]
        payload["reviewed_at"] = row["reviewed_at"]
        payload["created_at"] = row["created_at"]
        payload["audio"] = bool(row["audio"])
        payload["audio_authorized"] = bool(row["audio_authorized"])
        payload["audio_url"] = row["audio_url"]
        payload["local_audio_url"] = row["local_audio_url"]
        payload["lan_audio_url"] = row["lan_audio_url"]
        payload["audio_file"] = row["audio_file"]
        payload["video"] = bool(row["video"])
        payload["duration"] = row["duration"]
        payload["source"] = row["source"]
        payload["relayed_by"] = row["relayed_by"]
        if row["audio_review_url"] is not None:
            payload["audio_review_url"] = row["audio_review_url"]
        payload.pop("audio_token_hash", None)
        return payload

    def save_incident(
        self,
        payload: Dict[str, Any],
        audio_token_hash: Optional[str] = None,
        created_ts: Optional[float] = None,
    ) -> Dict[str, Any]:
        """Persist a flagged or uncertain incident row and return normalized dict."""
        record = copy.deepcopy(payload)
        record.pop("audio_token_hash", None)
        created_at = str(record.get("created_at") or _utc_iso_now())
        ts_val = float(created_ts if created_ts is not None else time.time())
        record["created_at"] = created_at
        record.setdefault("event_type", "incident")
        record.setdefault("reviewer_notes", "")
        record.setdefault("reviewed_by", None)
        record.setdefault("reviewed_at", None)
        if not record.get("review_status"):
            record["review_status"] = (
                "PENDING_REVIEW" if record.get("human_review_required") else "NONE"
            )

        orig_transcript = str(record.get("original_transcript") or record.get("transcript") or "")
        record["original_transcript"] = orig_transcript
        record.setdefault("transcript", orig_transcript)
        record.setdefault("normalized_transcript", orig_transcript.lower().strip())
        confidence = dict(record.get("confidence") or {})
        record["confidence"] = confidence

        serialized = json.dumps(record, ensure_ascii=False)
        with self._lock:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO incidents (
                    id, device_id, score, level, category, intent,
                    transcript, original_transcript, normalized_transcript,
                    transcription_status, transcription_reason, confidence_json,
                    human_review_required, review_status, reviewer_notes,
                    reviewed_by, reviewed_at, created_at, created_ts,
                    audio, audio_authorized, audio_url, local_audio_url,
                    lan_audio_url, audio_review_url, audio_file, audio_token_hash,
                    video, duration, source, relayed_by, payload_json
                ) VALUES (
                    ?, ?, ?, ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?,
                    ?, ?, ?, ?, ?
                )
                """,
                (
                    str(record["id"]),
                    str(record.get("device_id") or ""),
                    float(record.get("score") or 0.0),
                    str(record.get("level") or "NORMAL"),
                    str(record.get("category") or "Conversational"),
                    record.get("intent"),
                    str(record.get("transcript") or orig_transcript),
                    orig_transcript,
                    str(record.get("normalized_transcript") or ""),
                    str(record.get("transcription_status") or "TRANSCRIBED"),
                    record.get("transcription_reason"),
                    json.dumps(confidence, ensure_ascii=False),
                    1 if record.get("human_review_required") else 0,
                    str(record.get("review_status") or "NONE"),
                    str(record.get("reviewer_notes") or ""),
                    record.get("reviewed_by"),
                    record.get("reviewed_at"),
                    created_at,
                    ts_val,
                    1 if record.get("audio", True) else 0,
                    1 if record.get("audio_authorized") else 0,
                    record.get("audio_url"),
                    record.get("local_audio_url"),
                    record.get("lan_audio_url"),
                    record.get("audio_review_url"),
                    record.get("audio_file"),
                    audio_token_hash,
                    1 if record.get("video") else 0,
                    record.get("duration"),
                    record.get("source"),
                    record.get("relayed_by"),
                    serialized,
                ),
            )
            self._conn.commit()
        return record

    def get_incident(self, incident_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
            return self._row_to_dict(row) if row is not None else None

    def list_incidents(
        self,
        limit: int = 50,
        review_status: Optional[str] = None,
        uncertain_only: bool = False,
        newest_first: bool = True,
    ) -> List[Dict[str, Any]]:
        limit_val = max(1, min(int(limit), 500))
        clauses: List[str] = []
        params: List[Any] = []
        if review_status:
            clauses.append("review_status = ?")
            params.append(review_status)
        if uncertain_only:
            clauses.append("transcription_status = ?")
            params.append("UNCERTAIN_TRANSCRIPTION")
        where_sql = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        query = (
            f"SELECT * FROM incidents {where_sql} "
            f"ORDER BY created_ts DESC, rowid DESC LIMIT ?"
        )
        params.append(limit_val)
        with self._lock:
            rows = self._conn.execute(query, params).fetchall()
            items = [self._row_to_dict(r) for r in rows]
        if not newest_first:
            items.reverse()
        return items

    def update_review(
        self,
        incident_id: str,
        review_status: str,
        reviewer_notes: Optional[str] = None,
        reviewed_by: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        status_clean = str(review_status or "").strip().upper()
        if status_clean not in VALID_REVIEW_STATUSES:
            raise ValueError(
                f"Invalid review_status '{review_status}'. Must be one of {VALID_REVIEW_STATUSES}."
            )
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM incidents WHERE id = ?",
                (incident_id,),
            ).fetchone()
            if row is None:
                return None

            current = self._row_to_dict(row)
            notes_val = current.get("reviewer_notes", "") if reviewer_notes is None else str(reviewer_notes)
            reviewer_val = current.get("reviewed_by") if reviewed_by is None else str(reviewed_by).strip() or None
            reviewed_at = _utc_iso_now()

            current["review_status"] = status_clean
            current["reviewer_notes"] = notes_val
            current["reviewed_by"] = reviewer_val
            current["reviewed_at"] = reviewed_at
            current["human_review_required"] = (status_clean == "PENDING_REVIEW")

            serialized = json.dumps(current, ensure_ascii=False)
            self._conn.execute(
                """
                UPDATE incidents
                SET review_status = ?,
                    reviewer_notes = ?,
                    reviewed_by = ?,
                    reviewed_at = ?,
                    human_review_required = ?,
                    payload_json = ?
                WHERE id = ?
                """,
                (
                    status_clean,
                    notes_val,
                    reviewer_val,
                    reviewed_at,
                    1 if current["human_review_required"] else 0,
                    serialized,
                    incident_id,
                ),
            )
            self._conn.commit()
            return current

    def get_authorized_audio_record(self, incident_id: str) -> Optional[Dict[str, Any]]:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT audio_token_hash, audio_file, device_id
                FROM incidents
                WHERE id = ? AND audio_token_hash IS NOT NULL AND audio_token_hash != ''
                """,
                (incident_id,),
            ).fetchone()
            if row is None or not row["audio_file"]:
                return None
            return {
                "token_hash": row["audio_token_hash"],
                "wav_filename": os.path.basename(row["audio_file"]),
                "device_id": row["device_id"],
            }

    def count_incidents(self) -> int:
        with self._lock:
            row = self._conn.execute("SELECT COUNT(*) AS cnt FROM incidents").fetchone()
            return int(row["cnt"]) if row is not None else 0

    def close(self) -> None:
        with self._lock:
            self._conn.close()
