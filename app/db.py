"""SQLite: jobs, settings and measurements for the estimates."""
import json
import sqlite3
import threading
import time

from . import config

_lock = threading.RLock()
_conn: sqlite3.Connection | None = None

SCHEMA = """
CREATE TABLE IF NOT EXISTS jobs (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    kind TEXT NOT NULL,            -- movie | episode
    arr_id INTEGER NOT NULL,       -- movieId of seriesId
    file_id INTEGER NOT NULL,      -- movieFileId of episodeFileId
    title TEXT NOT NULL,
    subtitle TEXT DEFAULT '',
    path TEXT NOT NULL,
    preset TEXT NOT NULL,
    status TEXT NOT NULL,          -- queued | running | done | failed | skipped | cancelled
    stage TEXT DEFAULT '',
    progress REAL DEFAULT 0,
    fps REAL DEFAULT 0,
    speed REAL DEFAULT 0,
    eta REAL,
    cur_size INTEGER DEFAULT 0,
    size_before INTEGER DEFAULT 0,
    size_after INTEGER,
    est_size INTEGER,
    est_seconds REAL,
    message TEXT DEFAULT '',
    log TEXT DEFAULT '',
    position REAL NOT NULL,
    created REAL NOT NULL,
    started REAL,
    finished REAL
);
CREATE INDEX IF NOT EXISTS jobs_status ON jobs(status);
CREATE TABLE IF NOT EXISTS settings (key TEXT PRIMARY KEY, value TEXT NOT NULL);
CREATE TABLE IF NOT EXISTS observations (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    preset TEXT NOT NULL, bucket TEXT NOT NULL, codec TEXT NOT NULL,
    ratio REAL, fps REAL, source TEXT NOT NULL, created REAL NOT NULL,
    encoder TEXT NOT NULL DEFAULT 'qsv'
);
CREATE TABLE IF NOT EXISTS samples (
    key TEXT PRIMARY KEY,          -- kind:id:preset
    ratio REAL NOT NULL, fps REAL NOT NULL, created REAL NOT NULL
);
"""


def conn() -> sqlite3.Connection:
    global _conn
    if _conn is None:
        config.DATA_DIR.mkdir(parents=True, exist_ok=True)
        _conn = sqlite3.connect(config.DATA_DIR / "shrinkarr.db", check_same_thread=False, isolation_level=None)
        _conn.row_factory = sqlite3.Row
        _conn.execute("PRAGMA journal_mode=WAL")
        _conn.executescript(SCHEMA)
        cols = {r[1] for r in _conn.execute("PRAGMA table_info(jobs)")}
        if "source" not in cols:
            _conn.execute("ALTER TABLE jobs ADD COLUMN source TEXT NOT NULL DEFAULT 'manual'")
        if "not_before" not in cols:
            _conn.execute("ALTER TABLE jobs ADD COLUMN not_before REAL")
        for col in ("kept_path TEXT", "kept_until REAL", "orig_path TEXT", "renamed TEXT"):
            if col.split()[0] not in cols:
                _conn.execute(f"ALTER TABLE jobs ADD COLUMN {col}")
        if "encoder" not in {r[1] for r in _conn.execute("PRAGMA table_info(observations)")}:
            _conn.execute("ALTER TABLE observations ADD COLUMN encoder TEXT NOT NULL DEFAULT 'qsv'")
        _migrate(_conn)
        # Jobs that were running when the service stopped go back into the queue.
        _conn.execute("UPDATE jobs SET status='queued', stage='', progress=0 WHERE status='running'")
    return _conn


def _migrate(c: sqlite3.Connection):
    """Take over settings of installs configured through config.env, once."""
    have = {r[0]: json.loads(r[1]) for r in c.execute("SELECT key, value FROM settings")}
    if "_migrated_env" in have:
        return
    legacy = config.legacy_env()
    for k, v in legacy.items():
        if k not in have:
            c.execute("INSERT INTO settings(key, value) VALUES(?, ?)", (k, json.dumps(v)))
    if have.get("notify_method") == "mailrise":  # old name for sending through an SMTP relay
        c.execute("UPDATE settings SET value=? WHERE key='notify_method'", (json.dumps("email"),))
        if "notify_enabled" not in have:  # was on by default
            c.execute("INSERT INTO settings(key, value) VALUES('notify_enabled', 'true')")
    if (legacy.get("sonarr_url") or legacy.get("radarr_url")) and "setup_done" not in have:
        c.execute("INSERT INTO settings(key, value) VALUES('setup_done', 'true')")
    c.execute("INSERT OR REPLACE INTO settings(key, value) VALUES('_migrated_env', 'true')")


def q(sql: str, args=()) -> list[dict]:
    with _lock:
        return [dict(r) for r in conn().execute(sql, args).fetchall()]


def one(sql: str, args=()) -> dict | None:
    rows = q(sql, args)
    return rows[0] if rows else None


def exec(sql: str, args=()) -> int:
    with _lock:
        cur = conn().execute(sql, args)
        return cur.lastrowid


# --- settings --------------------------------------------------------------

_settings_cache: dict | None = None


def get_settings() -> dict:
    global _settings_cache
    if _settings_cache is None:
        s = dict(config.DEFAULT_SETTINGS)
        for r in q("SELECT key, value FROM settings WHERE key NOT LIKE '\\_%' ESCAPE '\\'"):
            if r["key"] in s:
                s[r["key"]] = json.loads(r["value"])
        _settings_cache = s
    return dict(_settings_cache)


def set_settings(values: dict) -> dict:
    global _settings_cache
    for k, v in values.items():
        if k not in config.DEFAULT_SETTINGS:
            continue
        if k in config.SECRET_SETTINGS and isinstance(v, str):
            if "•" in v:
                continue  # masked value from the web UI: leave unchanged
            v = v.strip()
        if isinstance(v, str) and k.endswith("_url"):
            v = v.strip().rstrip("/")
        exec("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", (k, json.dumps(v)))
    _settings_cache = None
    return get_settings()


# --- internal state (not shown in the settings) -----------------------------

def get_state(key: str, default=None):
    r = one("SELECT value FROM settings WHERE key=?", ("_" + key,))
    return json.loads(r["value"]) if r else default


def set_state(key: str, value):
    exec("INSERT OR REPLACE INTO settings(key, value) VALUES(?, ?)", ("_" + key, json.dumps(value)))


# --- jobs ------------------------------------------------------------------

def update_job(job_id: int, **fields):
    if not fields:
        return
    cols = ", ".join(f"{k}=?" for k in fields)
    exec(f"UPDATE jobs SET {cols} WHERE id=?", (*fields.values(), job_id))


def add_job(**f) -> int:
    pos = (one("SELECT MAX(position) AS p FROM jobs")["p"] or 0) + 1
    f.update(status="queued", position=pos, created=time.time())
    cols = ", ".join(f)
    return exec(f"INSERT INTO jobs({cols}) VALUES({', '.join('?' * len(f))})", tuple(f.values()))


def active_job_for(kind: str, file_id: int) -> dict | None:
    return one("SELECT * FROM jobs WHERE kind=? AND file_id=? AND status IN ('queued','running')", (kind, file_id))


# --- measurements for the estimates ----------------------------------------

def add_observation(preset, bucket, codec, ratio, fps, source, encoder):
    if ratio is not None and not 0.05 < ratio < 1.2:
        ratio = None  # unreliable measurement
    exec("INSERT INTO observations(preset, bucket, codec, ratio, fps, source, created, encoder) "
         "VALUES(?,?,?,?,?,?,?,?)", (preset, bucket, codec, ratio, fps, source, time.time(), encoder))


def observations(encoder: str | None = None) -> list[dict]:
    if encoder:
        return q("SELECT * FROM observations WHERE encoder=? ORDER BY id DESC LIMIT 500", (encoder,))
    return q("SELECT * FROM observations ORDER BY id DESC LIMIT 500")


def get_sample(key: str) -> dict | None:
    return one("SELECT * FROM samples WHERE key=?", (key,))


def set_sample(key: str, ratio: float, fps: float):
    exec("INSERT OR REPLACE INTO samples(key, ratio, fps, created) VALUES(?,?,?,?)", (key, ratio, fps, time.time()))
