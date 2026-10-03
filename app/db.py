import sqlite3
import time
from contextlib import contextmanager

from . import vocab
from .config import DB_PATH

SCHEMA = """
CREATE TABLE IF NOT EXISTS items (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL,
    category TEXT NOT NULL DEFAULT '',
    color TEXT NOT NULL DEFAULT '',
    size TEXT NOT NULL DEFAULT '',
    brand TEXT NOT NULL DEFAULT '',
    season TEXT NOT NULL DEFAULT '',
    formality TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS people (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    image TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS tryons (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    person_id INTEGER NOT NULL,
    item_ids TEXT NOT NULL,
    image TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS stores (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL UNIQUE COLLATE NOCASE,
    interested INTEGER NOT NULL DEFAULT 1
);
CREATE TABLE IF NOT EXISTS wishlist (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    url TEXT NOT NULL DEFAULT '',
    title TEXT NOT NULL,
    store TEXT NOT NULL DEFAULT '',
    category TEXT NOT NULL DEFAULT '',
    price TEXT NOT NULL DEFAULT '',
    notes TEXT NOT NULL DEFAULT '',
    image TEXT NOT NULL DEFAULT '',
    source TEXT NOT NULL DEFAULT 'link',
    bought INTEGER NOT NULL DEFAULT 0,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS memories (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    text TEXT NOT NULL,
    kind TEXT NOT NULL DEFAULT 'fact',
    source TEXT NOT NULL DEFAULT 'user',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS history (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    prompt TEXT NOT NULL,
    result TEXT NOT NULL,
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS feedback (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    history_id INTEGER NOT NULL,
    outfit_index INTEGER NOT NULL,
    rating INTEGER NOT NULL,
    comment TEXT NOT NULL DEFAULT '',
    created_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP
);
CREATE TABLE IF NOT EXISTS profile (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);
"""

# (stored id, plural label, singular label)
CATEGORIES = [
    ("tshirt", "T-shirts", "T-shirt"),
    ("shirt", "Shirts", "Shirt"),
    ("sweater", "Hoodies/Sweaters", "Hoodie/Sweater"),
    ("shorts", "Shorts", "Shorts"),
    ("trousers", "Trousers", "Trousers"),
    ("socks", "Socks", "Socks"),
    ("coat", "Coats", "Coat"),
    ("shoes", "Shoes", "Shoes"),
    ("accessories", "Accessories", "Accessory"),
]
CATEGORY_IDS = [c[0] for c in CATEGORIES]

ITEM_FIELDS = ["name", "category", "color", "size", "brand", "model", "fit", "material", "season", "formality", "notes"]

# columns added after the first version: (table, column) -> definition
MIGRATIONS = {
    ("items", "model"): "TEXT NOT NULL DEFAULT ''",
    ("items", "fit"): "TEXT NOT NULL DEFAULT ''",
    ("items", "material"): "TEXT NOT NULL DEFAULT ''",
    ("items", "source_path"): "TEXT NOT NULL DEFAULT ''",
    ("items", "file_hash"): "TEXT NOT NULL DEFAULT ''",
    ("people", "file_hash"): "TEXT NOT NULL DEFAULT ''",
    ("people", "source_path"): "TEXT NOT NULL DEFAULT ''",
}


@contextmanager
def conn():
    c = sqlite3.connect(DB_PATH)
    c.row_factory = sqlite3.Row
    try:
        yield c
        c.commit()
    finally:
        c.close()


BACKUP_PATH = DB_PATH.with_name("wardrobe.pre-english-backup.db")


def _legacy_values_present(c) -> bool:
    """True if the database still holds values saved by the Portuguese versions of the app."""
    checks = [
        ("items", "category", vocab.LEGACY_CATEGORIES), ("wishlist", "category", vocab.LEGACY_CATEGORIES),
        ("items", "season", vocab.LEGACY_SEASONS), ("memories", "kind", vocab.LEGACY_KINDS),
    ]
    for table, column, mapping in checks:
        changed = [k for k, v in mapping.items() if k != v]
        marks = ",".join("?" * len(changed))
        if c.execute(f"SELECT 1 FROM {table} WHERE {column} IN ({marks}) LIMIT 1", changed).fetchone():
            return True
    return False


def migrate_vocabulary(c) -> dict:
    """One-time, idempotent migration of controlled vocabulary (categories, seasons, formality, memory kinds,
    colours, materials) from Portuguese to English. Free text (names, notes, memories) is never touched.
    A consistent backup of the database is written before the first change."""
    counts: dict = {}
    if not _legacy_values_present(c):
        return counts
    backup = BACKUP_PATH
    if backup.exists():  # never overwrite an older backup: keep it and write a fresh, timestamped one
        backup = BACKUP_PATH.with_name(f"wardrobe.pre-english-backup-{time.strftime('%Y%m%d-%H%M%S')}.db")
    src, dst = sqlite3.connect(DB_PATH), sqlite3.connect(backup)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()
    counts["_backup"] = backup.name

    def remap(table: str, column: str, mapping: dict) -> None:
        for old, new in mapping.items():
            if old != new:
                n = c.execute(f"UPDATE {table} SET {column}=? WHERE {column}=?", (new, old)).rowcount
                if n:
                    counts[f"{table}.{column}"] = counts.get(f"{table}.{column}", 0) + n

    remap("items", "category", vocab.LEGACY_CATEGORIES)
    remap("wishlist", "category", vocab.LEGACY_CATEGORIES)
    remap("items", "season", vocab.LEGACY_SEASONS)
    remap("items", "formality", vocab.LEGACY_FORMALITY)
    remap("memories", "kind", vocab.LEGACY_KINDS)
    for column, translate in (("color", vocab.translate_color), ("material", vocab.translate_material)):
        for (value,) in c.execute(f"SELECT DISTINCT {column} FROM items WHERE {column} != ''").fetchall():
            new = translate(value)
            if new != value:
                n = c.execute(f"UPDATE items SET {column}=? WHERE {column}=?", (new, value)).rowcount
                counts[f"items.{column}"] = counts.get(f"items.{column}", 0) + n
    return counts


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        for (table, column), definition in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
        counts = migrate_vocabulary(c)
    if counts:
        backup = counts.pop("_backup", "")
        print(f"[db] Migrated stored vocabulary to English (backup: {backup}): {counts}")
