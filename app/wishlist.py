from urllib.parse import quote_plus

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import ai, db, images, memory, scrape
from .ai import AIError

router = APIRouter(prefix="/api")


def _row(r) -> dict:
    d = dict(r)
    d["image_url"] = f"/uploads/{d['image']}" if d.get("image") else ""
    d["bought"] = bool(d["bought"])
    return d


def _ensure_store(c, name: str) -> None:
    if name:
        c.execute("INSERT OR IGNORE INTO stores (name, interested) VALUES (?, 1)", (name,))


def _check_category(category: str) -> None:
    if category and category not in db.CATEGORY_IDS:
        raise HTTPException(400, "Categoria inválida.")


# ---------- Lojas ----------
class StoreIn(BaseModel):
    name: str = ""
    interested: bool = True


@router.get("/stores")
def list_stores():
    with db.conn() as c:
        rows = c.execute(
            "SELECT s.*, (SELECT COUNT(*) FROM wishlist w WHERE w.store = s.name COLLATE NOCASE) AS count FROM stores s ORDER BY s.name"
        )
        return [{**dict(r), "interested": bool(r["interested"])} for r in rows]


@router.post("/stores")
def add_store(body: StoreIn):
    name = body.name.strip()
    if not name:
        raise HTTPException(400, "Indica o nome da loja.")
    with db.conn() as c:
        c.execute(
            "INSERT INTO stores (name, interested) VALUES (?, ?) ON CONFLICT(name) DO UPDATE SET interested=excluded.interested",
            (name, int(body.interested)),
        )
    return {"ok": True}


@router.put("/stores/{store_id}")
def set_store(store_id: int, body: StoreIn):
    with db.conn() as c:
        c.execute("UPDATE stores SET interested=? WHERE id=?", (int(body.interested), store_id))
    return {"ok": True}


@router.delete("/stores/{store_id}")
def delete_store(store_id: int):
    with db.conn() as c:
        c.execute("DELETE FROM stores WHERE id=?", (store_id,))
    return {"ok": True}


# ---------- Lista de desejos ----------
class WishIn(BaseModel):
    url: str = ""
    title: str = ""
    store: str = ""
    category: str = ""
    price: str = ""
    notes: str = ""
    source: str = "link"  # link | ai | manual


@router.get("/wishlist")
def list_wishlist():
    with db.conn() as c:
        return [_row(r) for r in c.execute("SELECT * FROM wishlist ORDER BY bought, id DESC")]


@router.post("/wishlist")
def add_wish(body: WishIn):
    _check_category(body.category)
    url, title, store, price = body.url.strip(), body.title.strip(), body.store.strip(), body.price.strip()
    image = ""
    scraped = False
    if url and body.source == "link":
        try:
            meta, img = scrape.fetch_meta(url)
        except scrape.LinkError as e:
            raise HTTPException(400, str(e))
        scraped = bool(meta["title"])
        title = title or meta["title"]
        store = store or meta["store"]
        price = price or meta["price"]
        if img:
            try:
                image = images.save_upload(img, "wish")
            except Exception:
                image = ""
    if not title:
        if not url:
            raise HTTPException(400, "Indica um título ou um link.")
        title = url
    with db.conn() as c:
        if url and c.execute("SELECT 1 FROM wishlist WHERE url=?", (url,)).fetchone():
            raise HTTPException(409, "Este link já está guardado.")
        _ensure_store(c, store)
        cur = c.execute(
            "INSERT INTO wishlist (url, title, store, category, price, notes, image, source) VALUES (?,?,?,?,?,?,?,?)",
            (url, title, store, body.category, price, body.notes.strip(), image, body.source),
        )
        row = _row(c.execute("SELECT * FROM wishlist WHERE id=?", (cur.lastrowid,)).fetchone())
    row["scraped"] = scraped or not url or body.source != "link"
    return row


class WishUpdate(BaseModel):
    bought: bool | None = None
    notes: str | None = None


@router.put("/wishlist/{wish_id}")
def update_wish(wish_id: int, body: WishUpdate):
    with db.conn() as c:
        if body.bought is not None:
            c.execute("UPDATE wishlist SET bought=? WHERE id=?", (int(body.bought), wish_id))
        if body.notes is not None:
            c.execute("UPDATE wishlist SET notes=? WHERE id=?", (body.notes, wish_id))
        row = c.execute("SELECT * FROM wishlist WHERE id=?", (wish_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return _row(row)


@router.delete("/wishlist/{wish_id}")
def delete_wish(wish_id: int):
    with db.conn() as c:
        row = c.execute("SELECT image FROM wishlist WHERE id=?", (wish_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        c.execute("DELETE FROM wishlist WHERE id=?", (wish_id,))
    if row["image"]:
        images.delete(row["image"])
    return {"ok": True}


# ---------- Sugestões da IA ----------
class SuggestIn(BaseModel):
    prompt: str = ""


@router.post("/wishlist/suggest")
def suggest(body: SuggestIn):
    with db.conn() as c:
        items = [dict(r) for r in c.execute("SELECT * FROM items")]
        stores = [dict(r) for r in c.execute("SELECT name, interested FROM stores")]
        wishes = [r["title"] for r in c.execute("SELECT title FROM wishlist ORDER BY id DESC LIMIT 30")]
        profile = memory.profile_for_prompt(c)
        mem = memory.memory_text(c)
    if not items:
        raise HTTPException(400, "Adiciona primeiro algumas peças ao armário para eu perceber o teu estilo.")
    liked = [s["name"] for s in stores if s["interested"]]
    avoided = [s["name"] for s in stores if not s["interested"]]
    try:
        result = ai.suggest_purchases(body.prompt, items, profile, liked, avoided, wishes, mem)
    except AIError as e:
        raise HTTPException(502, str(e))
    by_id = {i["id"]: i for i in items}
    for s in result.get("suggestions", []):
        s["combines_with"] = [{"id": i, "name": by_id[i]["name"], "image_url": f"/uploads/{by_id[i]['image']}"} for i in s.get("combines_with", []) if i in by_id]
        if s.get("category") not in db.CATEGORY_IDS:
            s["category"] = ""
        if s.get("store") and s["store"].lower() in {a.lower() for a in avoided}:
            s["store"] = ""
        s["search_url"] = "https://www.google.com/search?q=" + quote_plus(f"{s.get('search_query') or s.get('title', '')} {s.get('store', '')}".strip())
    return result
