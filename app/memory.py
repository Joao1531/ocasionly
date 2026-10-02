"""Memória do estilista: factos aprendidos, histórico de pedidos e feedback."""
import json

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import ai, db
from .ai import AIError

router = APIRouter(prefix="/api")

MAX_MEMORIES = 100  # as mais recentes entram no prompt
HISTORY_IN_PROMPT = 5


# ---------- Medidas e tamanhos ----------
BODY_FIELDS = {
    "height_cm": ("Altura", "cm", (100, 250)),
    "weight_kg": ("Peso", "kg", (30, 300)),
}
SIZE_FIELDS = {
    "size_top": "t-shirts/camisas",
    "size_jacket": "casacos",
    "size_pants": "calças",
    "size_shorts": "calções",
    "size_shoes": "sapatos",
}


def get_body(c) -> dict:
    row = c.execute("SELECT value FROM profile WHERE key='body'").fetchone()
    try:
        data = json.loads(row["value"]) if row else {}
    except ValueError:
        data = {}
    return {k: str(data.get(k, "")) for k in [*BODY_FIELDS, *SIZE_FIELDS]}


def body_text(body: dict) -> str:
    parts = [f"{label}: {body[k]} {unit}" for k, (label, unit, _) in BODY_FIELDS.items() if body.get(k)]
    sizes = [f"{label} {body[k]}" for k, label in SIZE_FIELDS.items() if body.get(k)]
    if sizes:
        parts.append("Tamanhos habituais: " + "; ".join(sizes))
    return ". ".join(parts)


def profile_for_prompt(c) -> str:
    """Medidas estruturadas + perfil em texto livre, juntos, para entrar no prompt."""
    row = c.execute("SELECT value FROM profile WHERE key='text'").fetchone()
    return "\n".join(x for x in (body_text(get_body(c)), row["value"] if row else "") if x)


def memory_text(c) -> str:
    rows = c.execute("SELECT kind, text FROM memories ORDER BY id DESC LIMIT ?", (MAX_MEMORIES,)).fetchall()
    return "\n".join(f"- [{r['kind']}] {r['text']}" for r in reversed(rows))


def history_text(c) -> str:
    rows = list(reversed(c.execute("SELECT * FROM history ORDER BY id DESC LIMIT ?", (HISTORY_IN_PROMPT,)).fetchall()))
    lines = []
    for h in rows:
        outfits = json.loads(h["result"])
        fb = {(f["outfit_index"]): f for f in c.execute("SELECT * FROM feedback WHERE history_id=?", (h["id"],))}
        parts = []
        for n, o in enumerate(outfits):
            part = f"«{o['title']}» ({', '.join(o['item_names'])})"
            if n in fb:
                part += f" → {'gostou' if fb[n]['rating'] > 0 else 'não gostou'}" + (f" ({fb[n]['comment']})" if fb[n]["comment"] else "")
            parts.append(part)
        lines.append(f"- {h['created_at'][:10]}: pedido «{h['prompt']}» → sugeriste: " + "; ".join(parts))
    return "\n".join(lines)


def add_learned(c, learned: list[dict], source: str) -> list[dict]:
    """Guarda factos novos (sem duplicados) e devolve os que ficaram guardados."""
    saved = []
    have = {r["text"].lower() for r in c.execute("SELECT text FROM memories")}
    for x in learned:
        if x["text"].lower() in have:
            continue
        cur = c.execute("INSERT INTO memories (text, kind, source) VALUES (?,?,?)", (x["text"], x["kind"], source))
        have.add(x["text"].lower())
        saved.append({"id": cur.lastrowid, **x, "source": source})
    return saved


def save_history(c, prompt: str, result: dict) -> int:
    compact = [{"title": o.get("title", ""), "item_names": [i["name"] for i in o["items"]]} for o in result.get("outfits", [])]
    return c.execute("INSERT INTO history (prompt, result) VALUES (?,?)", (prompt, json.dumps(compact, ensure_ascii=False))).lastrowid


@router.get("/body")
def read_body():
    with db.conn() as c:
        return get_body(c)


class BodyIn(BaseModel):
    height_cm: str = ""
    weight_kg: str = ""
    size_top: str = ""
    size_jacket: str = ""
    size_pants: str = ""
    size_shorts: str = ""
    size_shoes: str = ""


@router.put("/body")
def write_body(body: BodyIn):
    data = {k: v.strip()[:20] for k, v in body.model_dump().items()}
    for k, (label, _, (lo, hi)) in BODY_FIELDS.items():
        if data[k]:
            try:
                value = float(data[k].replace(",", "."))
            except ValueError:
                raise HTTPException(400, f"{label}: indica um número.")
            if k == "height_cm" and value < 3:  # "1,78" = metros
                value *= 100
            if not lo <= value <= hi:
                raise HTTPException(400, f"{label}: tem de estar entre {lo} e {hi}.")
            data[k] = f"{value:.0f}" if k == "height_cm" else f"{value:g}"
    with db.conn() as c:
        c.execute("INSERT INTO profile (key, value) VALUES ('body', ?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                  (json.dumps(data, ensure_ascii=False),))
    return data


# ---------- Memória ----------
class MemoryIn(BaseModel):
    text: str
    kind: str = "facto"


def _kind(kind: str) -> str:
    return kind if kind in ai.KINDS else "facto"


@router.get("/memories")
def list_memories():
    with db.conn() as c:
        return [dict(r) for r in c.execute("SELECT * FROM memories ORDER BY id DESC")]


@router.post("/memories")
def add_memory(body: MemoryIn):
    text = body.text.strip()[:200]
    if not text:
        raise HTTPException(400, "Escreve o que o estilista deve saber.")
    with db.conn() as c:
        saved = add_learned(c, [{"text": text, "kind": _kind(body.kind)}], "user")
    if not saved:
        raise HTTPException(409, "O estilista já sabe isto.")
    return saved[0]


@router.put("/memories/{memory_id}")
def edit_memory(memory_id: int, body: MemoryIn):
    text = body.text.strip()[:200]
    if not text:
        raise HTTPException(400, "O texto não pode ficar vazio.")
    with db.conn() as c:
        c.execute("UPDATE memories SET text=?, kind=? WHERE id=?", (text, _kind(body.kind), memory_id))
    return {"ok": True}


@router.delete("/memories/{memory_id}")
def delete_memory(memory_id: int):
    with db.conn() as c:
        c.execute("DELETE FROM memories WHERE id=?", (memory_id,))
    return {"ok": True}


# ---------- Histórico ----------
@router.get("/history")
def list_history():
    with db.conn() as c:
        rows = c.execute("SELECT * FROM history ORDER BY id DESC LIMIT 30").fetchall()
        out = []
        for h in rows:
            fb = {f["outfit_index"]: f["rating"] for f in c.execute("SELECT * FROM feedback WHERE history_id=?", (h["id"],))}
            outfits = json.loads(h["result"])
            out.append({"id": h["id"], "prompt": h["prompt"], "created_at": h["created_at"],
                        "outfits": [{**o, "rating": fb.get(n, 0)} for n, o in enumerate(outfits)]})
        return out


# ---------- Feedback ----------
class FeedbackIn(BaseModel):
    history_id: int
    outfit_index: int
    rating: int  # 1 = gostou, -1 = não gostou
    comment: str = ""


@router.post("/feedback")
def feedback(body: FeedbackIn):
    if body.rating not in (1, -1):
        raise HTTPException(400, "Avaliação inválida.")
    comment = body.comment.strip()[:300]
    with db.conn() as c:
        h = c.execute("SELECT * FROM history WHERE id=?", (body.history_id,)).fetchone()
        outfits = json.loads(h["result"]) if h else []
        if not h or not 0 <= body.outfit_index < len(outfits):
            raise HTTPException(404, "Outfit não encontrado.")
        c.execute("DELETE FROM feedback WHERE history_id=? AND outfit_index=?", (body.history_id, body.outfit_index))
        c.execute("INSERT INTO feedback (history_id, outfit_index, rating, comment) VALUES (?,?,?,?)",
                  (body.history_id, body.outfit_index, body.rating, comment))
        o = outfits[body.outfit_index]
        desc = f"«{o['title']}» ({', '.join(o['item_names'])}) para o pedido «{h['prompt']}»"
        mem = memory_text(c)
    learned: list[dict] = []
    if comment:
        try:
            learned = ai.learn_from_feedback(desc, body.rating, comment, mem)
        except AIError:
            learned = []  # o feedback fica guardado mesmo que a extração falhe
    with db.conn() as c:
        saved = add_learned(c, learned, "feedback")
    return {"ok": True, "learned": saved}
