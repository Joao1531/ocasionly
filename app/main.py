import json

from fastapi import FastAPI, File, Form, HTTPException, UploadFile
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from . import ai, config, db, images, tryon
from .ai import AIError
from . import memory
from .importer import router as import_router
from .settings import router as settings_router
from .wishlist import router as wishlist_router
from .config import ROOT, UPLOAD_DIR

STATIC = ROOT / "app" / "static"

app = FastAPI(title="Ocasionly")
db.init()
app.include_router(wishlist_router)
app.include_router(memory.router)
app.include_router(settings_router)
app.include_router(import_router)


def _row(r) -> dict:
    d = dict(r)
    if "image" in d:
        d["image_url"] = f"/uploads/{d['image']}"
        d["thumb_url"] = f"/api/thumb/{d['image']}"
    return d


def _read_image(file: UploadFile, prefix: str) -> str:
    try:
        return images.save_upload(file.file.read(), prefix)
    except Exception:
        raise HTTPException(400, "Imagem inválida.")


def _ai_call(fn, *args):
    try:
        return fn(*args)
    except AIError as e:
        raise HTTPException(502, str(e))


@app.get("/api/status")
def status():
    return {**config.status(), "max_items": config.MAX_OUTFIT_ITEMS, "categories": [{"id": i, "label": l, "singular": n} for i, l, n in db.CATEGORIES]}


def _check_category(category: str) -> None:
    if category not in db.CATEGORY_IDS:
        raise HTTPException(400, f"Categoria inválida. Usa uma de: {', '.join(db.CATEGORY_IDS)}.")


# ---------- Peças ----------
@app.get("/api/items")
def list_items():
    with db.conn() as c:
        return [_row(r) for r in c.execute("SELECT * FROM items ORDER BY id DESC")]


@app.post("/api/items")
def create_item(
    image: UploadFile = File(...),
    name: str = Form(...),
    category: str = Form(""),
    color: str = Form(""),
    size: str = Form(""),
    brand: str = Form(""),
    model: str = Form(""),
    fit: str = Form(""),
    material: str = Form(""),
    season: str = Form(""),
    formality: str = Form(""),
    notes: str = Form(""),
):
    _check_category(category)
    fname = _read_image(image, "item")
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO items (name, category, color, size, brand, model, fit, material, season, formality, notes, image) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
            (name, category, color, size, brand, model, fit, material, season, formality, notes, fname),
        )
        return _row(c.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone())


class ItemUpdate(BaseModel):
    name: str
    category: str = ""
    color: str = ""
    size: str = ""
    brand: str = ""
    model: str = ""
    fit: str = ""
    material: str = ""
    season: str = ""
    formality: str = ""
    notes: str = ""


@app.put("/api/items/{item_id}")
def update_item(item_id: int, body: ItemUpdate):
    _check_category(body.category)
    with db.conn() as c:
        sets = ", ".join(f"{f}=?" for f in db.ITEM_FIELDS)
        c.execute(f"UPDATE items SET {sets} WHERE id=?", [getattr(body, f) for f in db.ITEM_FIELDS] + [item_id])
        row = c.execute("SELECT * FROM items WHERE id=?", (item_id,)).fetchone()
    if not row:
        raise HTTPException(404)
    return _row(row)


@app.delete("/api/items/{item_id}")
def delete_item(item_id: int):
    with db.conn() as c:
        row = c.execute("SELECT image FROM items WHERE id=?", (item_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        c.execute("DELETE FROM items WHERE id=?", (item_id,))
    images.delete(row["image"])
    return {"ok": True}


@app.post("/api/items/analyze")
def analyze(image: UploadFile = File(...)):
    """Sugere campos a partir da foto. A imagem temporária é apagada."""
    fname = _read_image(image, "tmp")
    try:
        return _ai_call(ai.analyze_item, fname)
    finally:
        images.delete(fname)


# ---------- Perfil ----------
class Profile(BaseModel):
    text: str


@app.get("/api/profile")
def get_profile():
    with db.conn() as c:
        row = c.execute("SELECT value FROM profile WHERE key='text'").fetchone()
    return {"text": row["value"] if row else ""}


@app.put("/api/profile")
def put_profile(body: Profile):
    with db.conn() as c:
        c.execute("INSERT INTO profile (key, value) VALUES ('text', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value", (body.text,))
    return {"ok": True}


# ---------- Conselhos ----------
class Ask(BaseModel):
    prompt: str


@app.post("/api/advise")
def advise(body: Ask):
    with db.conn() as c:
        items = [dict(r) for r in c.execute("SELECT * FROM items")]
        profile = memory.profile_for_prompt(c)
        mem, hist = memory.memory_text(c), memory.history_text(c)
    if not items:
        raise HTTPException(400, "Adiciona primeiro algumas peças ao guarda-roupa.")
    result = _ai_call(ai.advise, body.prompt, items, profile, mem, hist)
    by_id = {i["id"]: _row(i) for i in items}
    for o in result.get("outfits", []):
        o["items"] = [by_id[i] for i in o["item_ids"]]
    with db.conn() as c:
        result["learned"] = memory.add_learned(c, result.get("learned", []), "ai")
        result["history_id"] = memory.save_history(c, body.prompt, result)
    return result


# ---------- Provador ----------
@app.get("/api/people")
def list_people():
    with db.conn() as c:
        return [_row(r) for r in c.execute("SELECT * FROM people ORDER BY id DESC")]


@app.post("/api/people")
def add_person(image: UploadFile = File(...)):
    fname = _read_image(image, "person")
    with db.conn() as c:
        cur = c.execute("INSERT INTO people (image) VALUES (?)", (fname,))
        return _row(c.execute("SELECT * FROM people WHERE id=?", (cur.lastrowid,)).fetchone())


@app.delete("/api/people/{person_id}")
def delete_person(person_id: int):
    with db.conn() as c:
        row = c.execute("SELECT image FROM people WHERE id=?", (person_id,)).fetchone()
        if not row:
            raise HTTPException(404)
        c.execute("DELETE FROM people WHERE id=?", (person_id,))
    images.delete(row["image"])
    return {"ok": True}


class TryOn(BaseModel):
    person_id: int
    item_ids: list[int]


@app.post("/api/tryon")
def do_tryon(body: TryOn):
    if not 1 <= len(body.item_ids) <= config.MAX_OUTFIT_ITEMS:
        raise HTTPException(400, f"Escolhe entre 1 e {config.MAX_OUTFIT_ITEMS} peças.")
    with db.conn() as c:
        person = c.execute("SELECT * FROM people WHERE id=?", (body.person_id,)).fetchone()
        marks = ",".join("?" * len(body.item_ids))
        items = c.execute(f"SELECT * FROM items WHERE id IN ({marks})", body.item_ids).fetchall()
    if not person or len(items) != len(set(body.item_ids)):
        raise HTTPException(404, "Pessoa ou peça não encontrada.")
    raw = _ai_call(tryon.generate, person["image"], [i["image"] for i in items], [i["name"] for i in items])
    fname = images.save_bytes(raw, "tryon")
    with db.conn() as c:
        c.execute("INSERT INTO tryons (person_id, item_ids, image) VALUES (?,?,?)", (body.person_id, json.dumps(body.item_ids), fname))
    return {"image_url": f"/uploads/{fname}"}


@app.get("/api/thumb/{name}")
def thumb(name: str):
    path = images.thumb_path(name)
    if not path:
        raise HTTPException(404)
    return FileResponse(path, headers={"Cache-Control": "public, max-age=31536000"})


app.mount("/uploads", StaticFiles(directory=UPLOAD_DIR), name="uploads")


NO_CACHE = {"Cache-Control": "no-cache"}  # o browser revalida sempre (ETag), por isso nunca fica com JS/CSS antigos


@app.get("/")
def index():
    return FileResponse(STATIC / "index.html", headers=NO_CACHE)


class FreshStaticFiles(StaticFiles):
    def file_response(self, *args, **kwargs):
        response = super().file_response(*args, **kwargs)
        response.headers["Cache-Control"] = "no-cache"
        return response


app.mount("/", FreshStaticFiles(directory=STATIC), name="static")
