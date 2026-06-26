"""
Async SQLite connection manager for Auto-NguLo.
Uses aiosqlite for FastAPI async compatibility.
"""
import aiosqlite
import os
from config import DATABASE_PATH

_db: aiosqlite.Connection | None = None


async def get_db() -> aiosqlite.Connection:
    """Returns the singleton async SQLite connection."""
    global _db
    if _db is None:
        os.makedirs(os.path.dirname(DATABASE_PATH), exist_ok=True)
        _db = await aiosqlite.connect(DATABASE_PATH)
        _db.row_factory = aiosqlite.Row
        await _db.execute("PRAGMA journal_mode=WAL")
        await _db.execute("PRAGMA foreign_keys=ON")
    return _db


async def init_db():
    """Create all tables if they don't exist."""
    db = await get_db()
    await db.executescript("""
        CREATE TABLE IF NOT EXISTS config (
            key    TEXT PRIMARY KEY,
            value  TEXT NOT NULL
        );

        CREATE TABLE IF NOT EXISTS scripts (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            name            TEXT NOT NULL,
            description     TEXT DEFAULT '',
            repeat_count    INTEGER DEFAULT 1,
            delay_between_ms INTEGER DEFAULT 1000,
            created_at      TEXT DEFAULT (datetime('now')),
            updated_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE TABLE IF NOT EXISTS actions (
            id              INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id       INTEGER NOT NULL REFERENCES scripts(id) ON DELETE CASCADE,
            order_num       INTEGER NOT NULL,
            name            TEXT NOT NULL,
            action_type     TEXT NOT NULL,
            -- coordinates
            x               REAL,
            y               REAL,
            x2              REAL,
            y2              REAL,
            duration_ms     INTEGER DEFAULT 300,
            -- screenshot match
            template_path   TEXT DEFAULT '',
            template_path2  TEXT DEFAULT '',
            match_threshold REAL DEFAULT 0.80,
            retry_count     INTEGER DEFAULT 1,
            retry_delay_ms  INTEGER DEFAULT 1000,
            jump_on_success TEXT DEFAULT '',
            jump_on_fail    TEXT DEFAULT '',
            match_region_x     REAL DEFAULT NULL,
            match_region_y     REAL DEFAULT NULL,
            match_region_w     REAL DEFAULT NULL,
            match_region_h     REAL DEFAULT NULL,
            match_region_screen TEXT DEFAULT '',
            -- push key
            key_code        TEXT DEFAULT 'HOME',
            -- combo
            combo_action    TEXT DEFAULT 'select_all',
            -- fetch api
            api_url         TEXT DEFAULT '',
            api_method      TEXT DEFAULT 'GET',
            api_headers     TEXT DEFAULT '{}',
            api_body        TEXT DEFAULT '',
            api_save_to_var TEXT DEFAULT '',
            -- variable
            var_name        TEXT DEFAULT '',
            var_operation   TEXT DEFAULT 'set',
            var_value       TEXT DEFAULT '',
            -- type text
            text_content    TEXT DEFAULT '',
            text_speed_ms   INTEGER DEFAULT 50,
            -- jump
            jump_to         TEXT DEFAULT '',
            -- stop / kill — no extra fields needed
            -- if / condition
            condition_var   TEXT DEFAULT '',
            condition_op    TEXT DEFAULT 'eq',
            condition_value TEXT DEFAULT '',
            jump_on_true    TEXT DEFAULT '',
            jump_on_false   TEXT DEFAULT '',
            -- orientation
            orientation_value TEXT DEFAULT 'auto',
            -- launch_app / kill_app
            app_package     TEXT DEFAULT '',
            -- common
            use_match_result INTEGER DEFAULT 0,
            wait_ms         INTEGER DEFAULT 1000,
            wait_before_ms  INTEGER DEFAULT 500,
            wait_after_ms   INTEGER DEFAULT 500,
            created_at      TEXT DEFAULT (datetime('now'))
        );

        CREATE INDEX IF NOT EXISTS idx_actions_script_id ON actions(script_id);
        CREATE INDEX IF NOT EXISTS idx_actions_order ON actions(script_id, order_num);

        CREATE TABLE IF NOT EXISTS execution_logs (
            id          INTEGER PRIMARY KEY AUTOINCREMENT,
            script_id   INTEGER REFERENCES scripts(id) ON DELETE SET NULL,
            script_name TEXT DEFAULT '',
            status      TEXT DEFAULT 'running',
            log_json    TEXT DEFAULT '[]',
            success_count INTEGER DEFAULT 0,
            fail_count    INTEGER DEFAULT 0,
            total_actions INTEGER DEFAULT 0,
            duration_sec  REAL DEFAULT 0,
            started_at  TEXT DEFAULT (datetime('now')),
            ended_at    TEXT
        );

        -- Seed default password if not exists
        INSERT OR IGNORE INTO config (key, value) VALUES ('password', '123456');
    """)
    await db.commit()

    # Migration: add template_path2 column if it doesn't exist (v1.1+)
    try:
        await db.execute("ALTER TABLE actions ADD COLUMN template_path2 TEXT DEFAULT ''")
        await db.commit()
    except Exception:
        pass  # column already exists

    # Migration: add match_region columns (v1.2+)
    for col, col_type in [
        ('match_region_x', 'REAL DEFAULT NULL'),
        ('match_region_y', 'REAL DEFAULT NULL'),
        ('match_region_w', 'REAL DEFAULT NULL'),
        ('match_region_h', 'REAL DEFAULT NULL'),
        ('match_region_screen', "TEXT DEFAULT ''"),
    ]:
        try:
            await db.execute(f"ALTER TABLE actions ADD COLUMN {col} {col_type}")
            await db.commit()
        except Exception:
            pass  # column already exists

    # Migration: add new action type columns (v1.3+)
    for col, col_type in [
        ('jump_to', "TEXT DEFAULT ''"),
        ('condition_var', "TEXT DEFAULT ''"),
        ('condition_op', "TEXT DEFAULT 'eq'"),
        ('condition_value', "TEXT DEFAULT ''"),
        ('jump_on_true', "TEXT DEFAULT ''"),
        ('jump_on_false', "TEXT DEFAULT ''"),
        ('orientation_value', "TEXT DEFAULT 'auto'"),
        ('app_package', "TEXT DEFAULT ''"),
    ]:
        try:
            await db.execute(f"ALTER TABLE actions ADD COLUMN {col} {col_type}")
            await db.commit()
        except Exception:
            pass  # column already exists


async def close_db():
    """Close the database connection."""
    global _db
    if _db:
        await _db.close()
        _db = None
