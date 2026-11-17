"""SQLite store for the append-and-query data that used to live in big JSON files (so far: rejected postings).

data/jobsearch.db  table `rejected`: one row per rejected posting URL (company, title, location, source, latest reason,
first/last seen), pruned after keep_days. The old data/rejected.json is imported once, then renamed rejected.json.migrated."""
import json
import os
import sqlite3

SCHEMA = """
CREATE TABLE IF NOT EXISTS rejected (
  key TEXT PRIMARY KEY, first_seen TEXT NOT NULL, last_seen TEXT NOT NULL,
  company TEXT, title TEXT, location TEXT, source TEXT, reason TEXT);
CREATE INDEX IF NOT EXISTS rejected_reason ON rejected(reason);
CREATE INDEX IF NOT EXISTS rejected_last_seen ON rejected(last_seen);
"""
COLS = ("key", "first_seen", "last_seen", "company", "title", "location", "source", "reason")


def connect(data_dir):
    conn = sqlite3.connect(os.path.join(data_dir, "jobsearch.db"), timeout=30)
    conn.row_factory = sqlite3.Row
    conn.executescript(SCHEMA)
    _import_legacy(conn, data_dir)
    return conn


def _import_legacy(conn, data_dir):
    """One-time: load rejected.json into the table (only when the table is empty), then park the file."""
    path = os.path.join(data_dir, "rejected.json")
    if not os.path.exists(path) or conn.execute("SELECT 1 FROM rejected LIMIT 1").fetchone():
        return
    try:
        old = json.load(open(path))
    except (OSError, ValueError):
        return
    with conn:
        conn.executemany("INSERT OR REPLACE INTO rejected VALUES (?,?,?,?,?,?,?,?)",
                         [(k, v.get("first_seen", ""), v.get("last_seen", ""), v.get("company", ""), v.get("title", ""),
                           v.get("location", ""), v.get("source", ""), v.get("reason", "")) for k, v in old.items()])
    n = conn.execute("SELECT COUNT(*) FROM rejected").fetchone()[0]
    if n == len(old):  # only park the original once every row made it across
        os.replace(path, path + ".migrated")


def record_rejects(data_dir, rejects, today, cutoff):
    """rejects: [(job, reason)]. Upsert each (keeping first_seen), then drop anything not seen since `cutoff`."""
    conn = connect(data_dir)
    with conn:
        for j, reason in rejects:
            key = j.get("url") or f"{j['company']}|{j['title']}"
            conn.execute("""INSERT INTO rejected VALUES (?,?,?,?,?,?,?,?)
                            ON CONFLICT(key) DO UPDATE SET company=excluded.company, title=excluded.title, location=excluded.location,
                              source=excluded.source, reason=excluded.reason, last_seen=excluded.last_seen""",
                         (key, today, today, j["company"], j["title"], j.get("location", ""), j.get("source_label") or j["source"], reason))
        conn.execute("DELETE FROM rejected WHERE last_seen < ?", (cutoff,))
    conn.close()


def rejected(data_dir, reason=None):
    """Rejected postings as dicts, optionally only one reason. [] if there is no database yet."""
    if not os.path.exists(os.path.join(data_dir, "jobsearch.db")) and not os.path.exists(os.path.join(data_dir, "rejected.json")):
        return []
    conn = connect(data_dir)
    rows = conn.execute("SELECT * FROM rejected" + (" WHERE reason = ?" if reason else ""), (reason,) if reason else ()).fetchall()
    conn.close()
    return [dict(r) for r in rows]
