"""Persistent MCP route policy and advisory trace metadata."""
import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

DEFAULT_CONFIG = {
    "routing": {"enabled": True, "classifier_timeout_ms": 1200, "confidence_threshold": 0.5,
                "fallback": "inherit"},
    "models": {"tiers": {"light": None, "small": None, "mid": None, "top": None}},
    "skills": {"max_recommendations": 3},
    "execution": {"max_parallel_agents": 3, "permission_escalation": "forbidden"},
    "telemetry": {"retention_days": 30, "store_prompt_content": False},
}


def sanitize(value, depth=0):
    if depth > 6:
        return "[OMITTED]"
    if isinstance(value, dict):
        result = {}
        for key, item in value.items():
            name = str(key).lower()
            if any(part in name for part in ("password", "secret", "api_key", "access_token", "authorization", "credential")):
                result[str(key)] = "[REDACTED]"
            elif any(part in name for part in ("prompt", "task_text", "source_code", "environment", "content", "body")):
                result[str(key)] = "[OMITTED]"
            else:
                result[str(key)] = sanitize(item, depth + 1)
        return result
    if isinstance(value, list):
        return [sanitize(item, depth + 1) for item in value[:100]]
    if isinstance(value, str):
        return value[:1000]
    return value


class Store:
    def __init__(self, path):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        with self.connect() as db:
            db.executescript("""
                CREATE TABLE IF NOT EXISTS metadata (key TEXT PRIMARY KEY, value TEXT NOT NULL);
                CREATE TABLE IF NOT EXISTS events (
                    id INTEGER PRIMARY KEY AUTOINCREMENT, trace_id TEXT NOT NULL,
                    event TEXT NOT NULL, created_at TEXT NOT NULL, data TEXT NOT NULL
                );
                CREATE INDEX IF NOT EXISTS events_trace_id_id ON events(trace_id,id);
                CREATE TABLE IF NOT EXISTS routes (
                    request_id TEXT PRIMARY KEY, route_id TEXT NOT NULL UNIQUE,
                    trace_id TEXT NOT NULL, response TEXT NOT NULL, created_at TEXT NOT NULL
                );
            """)
            db.execute("INSERT OR IGNORE INTO metadata(key,value) VALUES('config',?)", (json.dumps(DEFAULT_CONFIG),))

    @contextmanager
    def connect(self):
        db = sqlite3.connect(self.path, timeout=5)
        db.row_factory = sqlite3.Row
        try:
            yield db
            db.commit()
        except Exception:
            db.rollback()
            raise
        finally:
            db.close()

    def config(self):
        with self.connect() as db:
            return json.loads(db.execute("SELECT value FROM metadata WHERE key='config'").fetchone()[0])

    def save_config(self, config):
        with self.connect() as db:
            db.execute("UPDATE metadata SET value=? WHERE key='config'", (json.dumps(config),))

    def save_route(self, request_id, route_id, trace_id, response, events=()):
        created_at = datetime.now(timezone.utc).isoformat()
        with self.connect() as db:
            db.execute("BEGIN IMMEDIATE")
            existing = db.execute("SELECT response FROM routes WHERE request_id=?", (request_id,)).fetchone()
            if existing:
                return json.loads(existing[0]), False
            db.execute("INSERT INTO routes(request_id,route_id,trace_id,response,created_at) VALUES(?,?,?,?,?)",
                       (request_id, route_id, trace_id, json.dumps(response), created_at))
            for event, data in events:
                db.execute("INSERT INTO events(trace_id,event,created_at,data) VALUES(?,?,?,?)",
                           (trace_id, event, created_at, json.dumps(sanitize(data))))
            return response, True

    def route_by_request(self, value):
        with self.connect() as db:
            row = db.execute("SELECT response FROM routes WHERE request_id=? OR route_id=? OR trace_id=?",
                             (value, value, value)).fetchone()
        return json.loads(row[0]) if row else None

    def add_event(self, trace_id, event, data):
        created_at = datetime.now(timezone.utc).isoformat()
        clean = sanitize(data)
        with self.connect() as db:
            cursor = db.execute("INSERT INTO events(trace_id,event,created_at,data) VALUES(?,?,?,?)",
                                (trace_id, event, created_at, json.dumps(clean)))
            return {"id": cursor.lastrowid, "trace_id": trace_id, "event": event,
                    "created_at": created_at, "data": clean}

    def report_execution(self, trace_id, status, details=None):
        if not self.route_by_request(trace_id):
            raise ValueError("trace_id must identify a route known to Laya")
        data = {"reported_status": status, "provenance": "mcp_self_report", "verified": False,
                "details": details or {}}
        if len(json.dumps(data, ensure_ascii=False).encode()) > 16_384:
            raise ValueError("execution report exceeds 16 KiB")
        return self.add_event(trace_id, "execution.reported", data)

    def events(self, trace_id=None, limit=100):
        with self.connect() as db:
            rows = (db.execute("SELECT * FROM events WHERE trace_id=? ORDER BY id", (trace_id,)).fetchall()
                    if trace_id is not None else
                    db.execute("SELECT * FROM events ORDER BY id DESC LIMIT ?", (limit,)).fetchall())
        return [{"id": row["id"], "trace_id": row["trace_id"], "event": row["event"],
                 "created_at": row["created_at"], "data": json.loads(row["data"])} for row in rows]

    def traces(self, limit=100):
        with self.connect() as db:
            rows = db.execute("SELECT trace_id,MAX(id) AS last_id,MAX(created_at) AS updated_at,COUNT(*) AS event_count "
                              "FROM events GROUP BY trace_id ORDER BY last_id DESC LIMIT ?", (limit,)).fetchall()
        return [dict(row) for row in rows]

    def delete_trace(self, trace_id):
        with self.connect() as db:
            db.execute("DELETE FROM routes WHERE trace_id=?", (trace_id,))
            cursor = db.execute("DELETE FROM events WHERE trace_id=?", (trace_id,))
            return cursor.rowcount
