from __future__ import annotations

import json

import sqlite3
import threading
from datetime import datetime, timezone
from pathlib import Path

from assistant.formatting import normalize_tags, one_tag


def _iso(moment: datetime) -> str:
    if moment.tzinfo is None:
        raise ValueError("timezone-aware datetime required")
    return moment.astimezone(timezone.utc).replace(microsecond=0).isoformat()


class Database:
    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self._lock = threading.RLock()
        self._conn = sqlite3.connect(path, check_same_thread=False, timeout=10)
        self._conn.row_factory = sqlite3.Row
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._migrate()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def _migrate(self) -> None:
        self._create_tables()
        columns = {row["name"] for row in self._conn.execute("PRAGMA table_info(reminders)")}
        if "repeat_minutes" not in columns:
            self._conn.execute("ALTER TABLE reminders ADD COLUMN repeat_minutes INTEGER")
        if "until_at" not in columns:
            self._conn.execute("ALTER TABLE reminders ADD COLUMN until_at TEXT")
        self._conn.commit()

    def _create_tables(self) -> None:
        self._conn.executescript(
            """
            CREATE TABLE IF NOT EXISTS reminders (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                text TEXT NOT NULL,
                due_at TEXT NOT NULL,
                created_at TEXT NOT NULL,
                sent INTEGER NOT NULL DEFAULT 0,
                attempts INTEGER NOT NULL DEFAULT 0
            );
            CREATE TABLE IF NOT EXISTS notes (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                body TEXT NOT NULL,
                tags TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS messages (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                role TEXT NOT NULL,
                content TEXT NOT NULL,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS assignments (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                title TEXT NOT NULL,
                course TEXT NOT NULL DEFAULT '',
                notes TEXT NOT NULL DEFAULT '',
                due_at TEXT NOT NULL,
                sent TEXT NOT NULL DEFAULT '[]',
                done_at TEXT,
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS meds (
                day TEXT PRIMARY KEY,
                nudges INTEGER NOT NULL DEFAULT 0,
                next_at TEXT,
                taken_at TEXT
            );
            CREATE TABLE IF NOT EXISTS bedtime (
                night TEXT PRIMARY KEY,
                last_slot INTEGER,
                messages TEXT NOT NULL DEFAULT '[]',
                done_at TEXT
            );
            CREATE TABLE IF NOT EXISTS jobs (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                instruction TEXT NOT NULL,
                repeat_minutes INTEGER NOT NULL,
                next_at TEXT NOT NULL,
                until_at TEXT,
                memory TEXT NOT NULL DEFAULT '',
                active INTEGER NOT NULL DEFAULT 1,
                failures INTEGER NOT NULL DEFAULT 0,
                last_run_at TEXT,
                last_result TEXT NOT NULL DEFAULT '',
                created_at TEXT NOT NULL
            );
            CREATE TABLE IF NOT EXISTS pc_tasks (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                user_id INTEGER NOT NULL,
                channel_id INTEGER,
                message_id INTEGER,
                plan TEXT NOT NULL,
                status TEXT NOT NULL DEFAULT 'pending',
                created_at TEXT NOT NULL
            );
            CREATE INDEX IF NOT EXISTS idx_reminders_due ON reminders(sent, due_at);
            CREATE INDEX IF NOT EXISTS idx_notes_user ON notes(user_id, updated_at);
            CREATE INDEX IF NOT EXISTS idx_messages_user ON messages(user_id, id);
            """
        )
        self._conn.commit()

    def _rows(self, sql: str, params: tuple = ()) -> list[dict]:
        with self._lock:
            cursor = self._conn.execute(sql, params)
            return [dict(row) for row in cursor.fetchall()]

    def add_reminder(
        self,
        user_id: int,
        text: str,
        due_at: datetime,
        repeat_minutes: int | None = None,
        until_at: datetime | None = None,
    ) -> dict:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO reminders (user_id, text, due_at, created_at, repeat_minutes, until_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    text.strip(),
                    _iso(due_at),
                    now,
                    repeat_minutes,
                    _iso(until_at) if until_at else None,
                ),
            )
            self._conn.commit()
            reminder_id = cursor.lastrowid
        found = self.get_reminder(user_id, reminder_id)
        if found is None:
            raise RuntimeError("reminder was not saved")
        return found

    def get_reminder(self, user_id: int, reminder_id: int) -> dict | None:
        rows = self._rows(
            "SELECT * FROM reminders WHERE id = ? AND user_id = ?",
            (reminder_id, user_id),
        )
        return rows[0] if rows else None

    def list_reminders(self, user_id: int) -> list[dict]:
        return self._rows(
            """
            SELECT * FROM reminders
            WHERE user_id = ? AND sent = 0
            ORDER BY due_at ASC, id ASC
            """,
            (user_id,),
        )

    def due_reminders(self, now: datetime) -> list[dict]:
        return self._rows(
            """
            SELECT * FROM reminders
            WHERE sent = 0 AND due_at <= ?
            ORDER BY due_at ASC, id ASC
            """,
            (_iso(now),),
        )

    def cancel_reminder(self, user_id: int, reminder_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                """
                SELECT * FROM reminders
                WHERE id = ? AND user_id = ? AND sent = 0
                """,
                (reminder_id, user_id),
            ).fetchone()
            if row is None:
                return None
            saved = dict(row)
            self._conn.execute("DELETE FROM reminders WHERE id = ?", (reminder_id,))
            self._conn.commit()
            return saved

    def mark_reminder_sent(self, reminder_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE reminders SET sent = 1 WHERE id = ?",
                (reminder_id,),
            )
            self._conn.commit()

    def reschedule_reminder(self, reminder_id: int, due_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE reminders SET due_at = ?, attempts = 0 WHERE id = ?",
                (_iso(due_at), reminder_id),
            )
            self._conn.commit()

    def bump_reminder_attempt(self, reminder_id: int) -> int:
        with self._lock:
            self._conn.execute(
                "UPDATE reminders SET attempts = attempts + 1 WHERE id = ?",
                (reminder_id,),
            )
            self._conn.commit()
            row = self._conn.execute(
                "SELECT attempts FROM reminders WHERE id = ?",
                (reminder_id,),
            ).fetchone()
            return int(row["attempts"]) if row else 0

    def add_note(self, user_id: int, title: str, body: str, tags: str = "") -> dict:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO notes (user_id, title, body, tags, created_at, updated_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, title.strip(), body.strip(), normalize_tags(tags), now, now),
            )
            self._conn.commit()
            note_id = cursor.lastrowid
        found = self.get_note(user_id, note_id)
        if found is None:
            raise RuntimeError("note was not saved")
        return found

    def get_note(self, user_id: int, note_id: int) -> dict | None:
        rows = self._rows(
            "SELECT * FROM notes WHERE id = ? AND user_id = ?",
            (note_id, user_id),
        )
        return rows[0] if rows else None

    def update_note(
        self,
        user_id: int,
        note_id: int,
        *,
        title: str | None = None,
        body: str | None = None,
        tags: str | None = None,
    ) -> dict | None:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            ).fetchone()
            if row is None:
                return None
            current = dict(row)
            new_title = current["title"] if title is None else title.strip()
            new_body = current["body"] if body is None else body.strip()
            new_tags = current["tags"] if tags is None else normalize_tags(tags)
            self._conn.execute(
                """
                UPDATE notes
                SET title = ?, body = ?, tags = ?, updated_at = ?
                WHERE id = ? AND user_id = ?
                """,
                (new_title, new_body, new_tags, now, note_id, user_id),
            )
            self._conn.commit()
            updated = self._conn.execute(
                "SELECT * FROM notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            ).fetchone()
            return dict(updated) if updated else None

    def delete_note(self, user_id: int, note_id: int) -> dict | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            ).fetchone()
            if row is None:
                return None
            saved = dict(row)
            self._conn.execute(
                "DELETE FROM notes WHERE id = ? AND user_id = ?",
                (note_id, user_id),
            )
            self._conn.commit()
            return saved

    def search_notes(self, user_id: int, query: str = "", tag: str = "") -> list[dict]:
        sql = "SELECT * FROM notes WHERE user_id = ?"
        params: list = [user_id]
        cleaned = query.strip()
        if cleaned:
            escaped = (
                cleaned.replace("\\", "\\\\").replace("%", "\\%").replace("_", "\\_")
            )
            like = f"%{escaped}%"
            sql += " AND (title LIKE ? ESCAPE '\\' OR body LIKE ? ESCAPE '\\' OR tags LIKE ? ESCAPE '\\')"
            params.extend([like, like, like])
        needle = one_tag(tag)
        if needle:
            sql += " AND (',' || replace(lower(tags), ' ', '') || ',') LIKE ?"
            params.append(f"%,{needle},%")
        sql += " ORDER BY updated_at DESC, id DESC"
        return self._rows(sql, tuple(params))

    def add_message(self, user_id: int, role: str, content: str, keep: int = 40) -> None:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO messages (user_id, role, content, created_at)
                VALUES (?, ?, ?, ?)
                """,
                (user_id, role, content, now),
            )
            self._conn.execute(
                """
                DELETE FROM messages
                WHERE user_id = ?
                  AND id NOT IN (
                    SELECT id FROM messages
                    WHERE user_id = ?
                    ORDER BY id DESC
                    LIMIT ?
                  )
                """,
                (user_id, user_id, keep),
            )
            self._conn.commit()

    def recent_messages(self, user_id: int, limit: int = 12) -> list[dict]:
        rows = self._rows(
            """
            SELECT role, content FROM messages
            WHERE user_id = ?
            ORDER BY id DESC
            LIMIT ?
            """,
            (user_id, limit),
        )
        rows.reverse()
        return rows

    def clear_messages(self, user_id: int) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM messages WHERE user_id = ?", (user_id,))
            self._conn.commit()

    def add_pc_task(self, user_id: int, plan: str, channel_id: int | None = None) -> int:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            cursor = self._conn.execute(
                "INSERT INTO pc_tasks (user_id, channel_id, plan, created_at) VALUES (?, ?, ?, ?)",
                (user_id, channel_id, plan, now),
            )
            self._conn.commit()
            return int(cursor.lastrowid)

    def get_pc_task(self, task_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM pc_tasks WHERE id = ?", (task_id,))
        return rows[0] if rows else None

    def set_pc_task_message(self, task_id: int, channel_id: int, message_id: int) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE pc_tasks SET channel_id = ?, message_id = ? WHERE id = ?",
                (channel_id, message_id, task_id),
            )
            self._conn.commit()

    def claim_pc_task(self, task_id: int, old: str, new: str) -> bool:
        """Move a task from one status to another. False if it was not in old."""
        with self._lock:
            cursor = self._conn.execute(
                "UPDATE pc_tasks SET status = ? WHERE id = ? AND status = ?",
                (new, task_id, old),
            )
            self._conn.commit()
            return cursor.rowcount == 1

    def add_job(
        self,
        user_id: int,
        instruction: str,
        repeat_minutes: int,
        next_at: datetime,
        until_at: datetime | None = None,
    ) -> dict:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO jobs (user_id, instruction, repeat_minutes, next_at, until_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (
                    user_id,
                    instruction.strip(),
                    repeat_minutes,
                    _iso(next_at),
                    _iso(until_at) if until_at else None,
                    now,
                ),
            )
            self._conn.commit()
            job_id = int(cursor.lastrowid)
        return self.get_job(user_id, job_id)

    def get_job(self, user_id: int, job_id: int) -> dict | None:
        rows = self._rows("SELECT * FROM jobs WHERE id = ? AND user_id = ?", (job_id, user_id))
        return rows[0] if rows else None

    def list_jobs(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM jobs WHERE user_id = ? AND active = 1 ORDER BY next_at ASC, id ASC",
            (user_id,),
        )

    def due_jobs(self, now: datetime) -> list[dict]:
        return self._rows(
            "SELECT * FROM jobs WHERE active = 1 AND next_at <= ? ORDER BY next_at ASC, id ASC",
            (_iso(now),),
        )

    def update_job(self, job_id: int, **fields) -> None:
        allowed = {"next_at", "memory", "active", "failures", "last_run_at", "last_result"}
        sets, values = [], []
        for key, value in fields.items():
            if key not in allowed:
                raise ValueError(f"unknown job field {key}")
            if isinstance(value, datetime):
                value = _iso(value)
            sets.append(f"{key} = ?")
            values.append(value)
        if not sets:
            return
        with self._lock:
            self._conn.execute(f"UPDATE jobs SET {', '.join(sets)} WHERE id = ?", (*values, job_id))
            self._conn.commit()

    def cancel_job(self, user_id: int, job_id: int) -> dict | None:
        found = self.get_job(user_id, job_id)
        if found is None or not found["active"]:
            return None
        self.update_job(job_id, active=0)
        return found

    def get_bedtime(self, night: str) -> dict | None:
        rows = self._rows("SELECT * FROM bedtime WHERE night = ?", (night,))
        return rows[0] if rows else None

    def save_bedtime(self, night: str, last_slot: int, messages: list[str]) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bedtime (night, last_slot, messages) VALUES (?, ?, ?)
                ON CONFLICT(night) DO UPDATE SET last_slot = excluded.last_slot, messages = excluded.messages
                """,
                (night, last_slot, json.dumps(messages)),
            )
            self._conn.commit()

    def finish_bedtime(self, night: str) -> None:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO bedtime (night, done_at) VALUES (?, ?)
                ON CONFLICT(night) DO UPDATE SET done_at = excluded.done_at
                """,
                (night, now),
            )
            self._conn.commit()

    def get_meds(self, day: str) -> dict | None:
        rows = self._rows("SELECT * FROM meds WHERE day = ?", (day,))
        return rows[0] if rows else None

    def save_meds(self, day: str, nudges: int, next_at: datetime) -> None:
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO meds (day, nudges, next_at) VALUES (?, ?, ?)
                ON CONFLICT(day) DO UPDATE SET nudges = excluded.nudges, next_at = excluded.next_at
                """,
                (day, nudges, _iso(next_at)),
            )
            self._conn.commit()

    def take_meds(self, day: str) -> None:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            self._conn.execute(
                """
                INSERT INTO meds (day, taken_at) VALUES (?, ?)
                ON CONFLICT(day) DO UPDATE SET taken_at = excluded.taken_at
                """,
                (day, now),
            )
            self._conn.commit()

    def meds_taken_days(self, limit: int = 400) -> list[str]:
        rows = self._rows(
            "SELECT day FROM meds WHERE taken_at IS NOT NULL ORDER BY day DESC LIMIT ?", (limit,)
        )
        return [row["day"] for row in rows]

    def add_assignment(self, user_id: int, title: str, course: str, notes: str, due_at: datetime) -> dict:
        now = _iso(datetime.now(timezone.utc))
        with self._lock:
            cursor = self._conn.execute(
                """
                INSERT INTO assignments (user_id, title, course, notes, due_at, created_at)
                VALUES (?, ?, ?, ?, ?, ?)
                """,
                (user_id, title, course, notes, _iso(due_at), now),
            )
            self._conn.commit()
            new_id = int(cursor.lastrowid)
        return self._rows("SELECT * FROM assignments WHERE id = ?", (new_id,))[0]

    def list_assignments(self, user_id: int) -> list[dict]:
        return self._rows(
            "SELECT * FROM assignments WHERE user_id = ? AND done_at IS NULL ORDER BY due_at ASC, id ASC",
            (user_id,),
        )

    def open_assignments(self) -> list[dict]:
        return self._rows("SELECT * FROM assignments WHERE done_at IS NULL ORDER BY due_at ASC")

    def _open_assignment(self, user_id: int, assignment_id: int) -> dict | None:
        rows = self._rows(
            "SELECT * FROM assignments WHERE id = ? AND user_id = ? AND done_at IS NULL",
            (assignment_id, user_id),
        )
        return rows[0] if rows else None

    def complete_assignment(self, user_id: int, assignment_id: int) -> dict | None:
        row = self._open_assignment(user_id, assignment_id)
        if row is None:
            return None
        with self._lock:
            self._conn.execute(
                "UPDATE assignments SET done_at = ? WHERE id = ?",
                (_iso(datetime.now(timezone.utc)), assignment_id),
            )
            self._conn.commit()
        return row

    def move_assignment(self, user_id: int, assignment_id: int, due_at: datetime) -> dict | None:
        """New due date. Reminders start over from now, so past ones don't all fire at once."""
        if self._open_assignment(user_id, assignment_id) is None:
            return None
        with self._lock:
            self._conn.execute(
                "UPDATE assignments SET due_at = ?, sent = '[]', created_at = ? WHERE id = ?",
                (_iso(due_at), _iso(datetime.now(timezone.utc)), assignment_id),
            )
            self._conn.commit()
        return self._open_assignment(user_id, assignment_id)

    def remove_assignment(self, user_id: int, assignment_id: int) -> dict | None:
        rows = self._rows(
            "SELECT * FROM assignments WHERE id = ? AND user_id = ?", (assignment_id, user_id)
        )
        if not rows:
            return None
        with self._lock:
            self._conn.execute("DELETE FROM assignments WHERE id = ?", (assignment_id,))
            self._conn.commit()
        return rows[0]

    def mark_assignment_sent(self, assignment_id: int, sent: list[str]) -> None:
        with self._lock:
            self._conn.execute(
                "UPDATE assignments SET sent = ? WHERE id = ?", (json.dumps(sent), assignment_id)
            )
            self._conn.commit()
