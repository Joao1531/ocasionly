import sqlite3
from contextlib import contextmanager

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
    kind TEXT NOT NULL DEFAULT 'facto',
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

# (id guardado, rótulo no plural, nome no singular)
CATEGORIES = [
    ("t-shirt", "T-shirts", "T-shirt"),
    ("camisa", "Camisas", "Camisa"),
    ("camisola", "Hoodies/Camisolas", "Hoodie/Camisola"),
    ("calções", "Calções", "Calções"),
    ("calças", "Calças", "Calças"),
    ("meias", "Meias", "Meias"),
    ("casaco", "Casacos", "Casaco"),
    ("sapatos", "Sapatos", "Sapatos"),
    ("acessórios", "Acessórios", "Acessório"),
]
CATEGORY_IDS = [c[0] for c in CATEGORIES]

ITEM_FIELDS = ["name", "category", "color", "size", "brand", "model", "fit", "material", "season", "formality", "notes"]

# colunas acrescentadas depois da primeira versão: (tabela, coluna) -> definição
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


def init() -> None:
    with conn() as c:
        c.executescript(SCHEMA)
        for (table, column), definition in MIGRATIONS.items():
            have = {r["name"] for r in c.execute(f"PRAGMA table_info({table})")}
            if column not in have:
                c.execute(f"ALTER TABLE {table} ADD COLUMN {column} {definition}")
