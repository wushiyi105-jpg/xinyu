"""心语的持久层:每天一条情绪记录 + 分析结果。

日期用 ISO 字符串(YYYY-MM-DD),按日期做主键:同一天再记一次就是覆盖,
不留重复行,趋势算起来才干净。
"""

from __future__ import annotations

import json
import os
import sqlite3
import threading
from datetime import datetime, timezone

DEFAULT_PATH = os.path.join(os.path.dirname(os.path.dirname(__file__)), "data", "xinyu.db")


def _now() -> str:
    return datetime.now(timezone.utc).astimezone().strftime("%Y-%m-%d %H:%M:%S")


class Database:
    def __init__(self, path: str | None = None):
        self.path = path or os.environ.get("XINYU_DB") or DEFAULT_PATH
        os.makedirs(os.path.dirname(os.path.abspath(self.path)), exist_ok=True)
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self.path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._init()

    def _init(self) -> None:
        with self._lock:
            self._conn.executescript(
                """
                CREATE TABLE IF NOT EXISTS entries (
                    id INTEGER PRIMARY KEY AUTOINCREMENT,
                    date TEXT NOT NULL UNIQUE,
                    text TEXT NOT NULL,
                    mood TEXT DEFAULT '',
                    score INTEGER DEFAULT 0,
                    stressors TEXT DEFAULT '[]',
                    advice TEXT DEFAULT '',
                    created_at TEXT NOT NULL
                );
                """
            )
            self._conn.commit()

    def save_entry(self, date: str, text: str) -> int:
        """按日期覆盖写入,返回 id。"""
        with self._lock:
            self._conn.execute(
                "INSERT INTO entries(date, text, created_at) VALUES(?,?,?) "
                "ON CONFLICT(date) DO UPDATE SET text=excluded.text, created_at=excluded.created_at",
                (date, text.strip(), _now()),
            )
            row = self._conn.execute("SELECT id FROM entries WHERE date=?", (date,)).fetchone()
            self._conn.commit()
            return int(row["id"])

    def set_analysis(self, entry_id: int, mood: str, score: int, stressors: list[str], advice: str) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE entries SET mood=?, score=?, stressors=?, advice=? WHERE id=?",
                (mood, score, json.dumps(stressors, ensure_ascii=False), advice, entry_id),
            )
            self._conn.commit()

    def get_entry(self, key: str | int):
        with self._lock:
            if str(key).isdigit() and len(str(key)) <= 6:
                row = self._conn.execute("SELECT * FROM entries WHERE id=?", (int(key),)).fetchone()
            else:
                row = self._conn.execute("SELECT * FROM entries WHERE date=?", (str(key),)).fetchone()
            return self._row(row) if row else None

    def _row(self, row) -> dict:
        d = dict(row)
        try:
            d["stressors"] = json.loads(d.get("stressors") or "[]")
        except json.JSONDecodeError:
            d["stressors"] = []
        return d

    def list_entries(self, limit: int = 30) -> list[dict]:
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM entries ORDER BY date DESC LIMIT ?", (limit,)
            ).fetchall()
            return [self._row(r) for r in rows]

    def recent(self, days: int = 7) -> list[dict]:
        """最近 N 天(按日期升序),用于趋势。"""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM entries ORDER BY date DESC LIMIT ?", (days,)
            ).fetchall()
            return [self._row(r) for r in reversed(rows)]

    def delete_entry(self, entry_id: int) -> bool:
        with self._lock:
            cur = self._conn.execute("DELETE FROM entries WHERE id=?", (entry_id,))
            self._conn.commit()
            return cur.rowcount > 0

    def stats(self) -> dict:
        with self._lock:
            d = self._conn.execute("SELECT COUNT(*) c FROM entries").fetchone()
            a = self._conn.execute("SELECT COUNT(*) c FROM entries WHERE mood<>''").fetchone()
            return {"entries": d["c"], "analyzed": a["c"]}

    def close(self) -> None:
        with self._lock:
            self._conn.close()
