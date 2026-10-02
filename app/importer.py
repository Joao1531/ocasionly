"""Importação em massa a partir de uma pasta do Mac, com uma subpasta por categoria."""
import hashlib
from pathlib import Path

from fastapi import APIRouter, HTTPException, Request
from pydantic import BaseModel

from . import ai, config, db, filenames, images
from .ai import AIError

router = APIRouter(prefix="/api/import")

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".webp", ".heic", ".heif"}
LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost"}
SINGULAR = {cid: singular for cid, _, singular in db.CATEGORIES}


def _local_only(request: Request) -> None:
    """Esta rota lê ficheiros do disco, por isso só aceita pedidos feitos a partir do próprio Mac."""
    if (request.client.host if request.client else "") not in LOCAL_HOSTS:
        raise HTTPException(403, "A importação de pastas só funciona abrindo a app no próprio Mac (localhost), não pelo telemóvel.")


def _root(dir_: str) -> Path:
    root = Path(dir_ or config.get("IMPORT_DIR")).expanduser().resolve()
    home = Path.home().resolve()
    if home not in (root, *root.parents):
        raise HTTPException(400, f"Escolhe uma pasta dentro da tua pasta pessoal ({home}).")
    if not root.is_dir():
        raise HTTPException(404, f"A pasta «{root}» não existe.")
    return root


def _file(root: Path, rel: str) -> Path:
    path = (root / rel).resolve()
    if root not in path.parents or not path.is_file() or path.suffix.lower() not in IMAGE_EXTS:
        raise HTTPException(400, "Ficheiro inválido.")
    return path


def _sha1(path: Path) -> str:
    return hashlib.sha1(path.read_bytes()).hexdigest()


def _known_hashes(c) -> tuple[set[str], set[str]]:
    items = {r["file_hash"] for r in c.execute("SELECT file_hash FROM items WHERE file_hash != ''")}
    people = {r["file_hash"] for r in c.execute("SELECT file_hash FROM people WHERE file_hash != ''")}
    return items, people


def name_key(path_or_name: str) -> str:
    """Chave do «mesmo nome»: sem pasta, sem extensão, sem maiúsculas nem acentos (NFC/NFD do macOS incluídos)."""
    return filenames.norm(Path(path_or_name).stem)


def _known_names(c) -> tuple[dict[str, str], dict[str, str]]:
    """Nome (chave) -> caminho do ficheiro que já foi importado com esse nome."""
    items = {name_key(r["source_path"]): r["source_path"] for r in c.execute("SELECT source_path FROM items WHERE source_path != ''")}
    people = {name_key(r["source_path"]): r["source_path"] for r in c.execute("SELECT source_path FROM people WHERE source_path != ''")}
    return items, people


def _category_of(root: Path, path: Path) -> str | None:
    rel = path.relative_to(root)
    return filenames.folder_category(rel.parts[0]) if len(rel.parts) > 1 else None


@router.get("/config")
def import_config():
    d = Path(config.get("IMPORT_DIR")).expanduser()
    return {"dir": str(d), "exists": d.is_dir()}


class ScanIn(BaseModel):
    dir: str = ""


@router.post("/scan")
def scan(body: ScanIn, request: Request):
    _local_only(request)
    root = _root(body.dir)
    config.save({"IMPORT_DIR": str(root)})
    with db.conn() as c:
        item_hashes, person_hashes = _known_hashes(c)
        item_names, person_names = _known_names(c)
    files, people, skipped, duplicates = [], [], [], []
    seen_names: dict[tuple[str, str], str] = {}  # (grupo, nome) -> primeiro ficheiro com esse nome nesta pasta
    seen_hashes: dict[tuple[str, str], str] = {}
    for path in sorted(root.rglob("*")):
        if not path.is_file() or path.name.startswith("."):
            continue
        rel = str(path.relative_to(root))
        if path.suffix.lower() not in IMAGE_EXTS:
            skipped.append({"rel": rel, "reason": "não é uma imagem"})
            continue
        digest, key = _sha1(path), name_key(path.name)
        is_person = len(path.relative_to(root).parts) == 1  # imagem solta na raiz: provavelmente uma foto tua
        category = None if is_person else _category_of(root, path)
        if not is_person and category is None:
            skipped.append({"rel": rel, "reason": f"pasta «{path.relative_to(root).parts[0]}» desconhecida"})
            continue
        group = "people" if is_person else "items"
        known_hashes, known_names = (person_hashes, person_names) if is_person else (item_hashes, item_names)
        if key in known_names:
            same_file = known_names[key] == rel
            status, reason = "imported", "já importada" if same_file else f"já existe uma foto com o mesmo nome ({known_names[key]})"
        elif digest in known_hashes:
            status, reason = "imported", "já importada (conteúdo igual)"
        elif (group, key) in seen_names:
            duplicates.append({"rel": rel, "of": seen_names[(group, key)], "reason": "mesmo nome"})
            continue
        elif (group, digest) in seen_hashes:
            duplicates.append({"rel": rel, "of": seen_hashes[(group, digest)], "reason": "conteúdo igual"})
            continue
        else:
            status, reason = "new", ""
            seen_names[(group, key)] = rel
            seen_hashes[(group, digest)] = rel
        if is_person:
            people.append({"rel": rel, "status": status, "reason": reason})
        else:
            parsed = filenames.parse(path.name, category, SINGULAR[category])
            files.append({"rel": rel, "category": category, "status": status, "reason": reason, **parsed})
    return {"dir": str(root), "files": files, "people": people, "skipped": skipped, "duplicates": duplicates}


class ItemIn(BaseModel):
    dir: str = ""
    rel: str
    analyze: bool | str = "none"  # none | missing (só peças sem cor no nome) | all


@router.post("/item")
def import_item(body: ItemIn, request: Request):
    _local_only(request)
    root = _root(body.dir)
    path = _file(root, body.rel)
    category = _category_of(root, path)
    if category is None:
        raise HTTPException(400, "Esta pasta não corresponde a nenhuma categoria.")
    digest = _sha1(path)
    with db.conn() as c:
        if name_key(path.name) in _known_names(c)[0]:
            return {"skipped": True, "reason": "mesmo nome"}
        if digest in _known_hashes(c)[0]:
            return {"skipped": True, "reason": "conteúdo igual"}
        count = c.execute("SELECT COUNT(*) AS n FROM items WHERE category=?", (category,)).fetchone()["n"]
    f = filenames.parse(path.name, category, SINGULAR[category])
    f["name"] = f["name"] or f"{SINGULAR[category]} {count + 1}"
    try:
        fname = images.save_upload(path.read_bytes(), "item")
    except Exception:
        raise HTTPException(400, f"Não consegui abrir a imagem «{body.rel}».")
    mode = "all" if body.analyze is True else ("none" if body.analyze in (False, "none", "") else str(body.analyze))
    if config.status()["vision"] and (mode == "all" or (mode == "missing" and not f["color"])):
        try:
            guess = ai.analyze_item(fname)
            for k in ("color", "season", "formality"):
                f[k] = f.get(k) or guess.get(k, "")
        except AIError:
            pass  # a análise é opcional: a peça entra na mesma
    f.setdefault("season", "")
    f.setdefault("formality", "")
    with db.conn() as c:
        cur = c.execute(
            "INSERT INTO items (name, category, color, size, brand, model, fit, material, season, formality, notes, image, source_path, file_hash) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)",
            (f["name"], category, f["color"], f["size"], f["brand"], f["model"], f["fit"], f["material"], f["season"], f["formality"], "", fname, body.rel, digest),
        )
        row = dict(c.execute("SELECT * FROM items WHERE id=?", (cur.lastrowid,)).fetchone())
    row["image_url"], row["thumb_url"] = f"/uploads/{fname}", f"/api/thumb/{fname}"
    return row


@router.post("/person")
def import_person(body: ItemIn, request: Request):
    _local_only(request)
    root = _root(body.dir)
    path = _file(root, body.rel)
    digest = _sha1(path)
    with db.conn() as c:
        if name_key(path.name) in _known_names(c)[1]:
            return {"skipped": True, "reason": "mesmo nome"}
        if digest in _known_hashes(c)[1]:
            return {"skipped": True, "reason": "conteúdo igual"}
    try:
        fname = images.save_upload(path.read_bytes(), "person")
    except Exception:
        raise HTTPException(400, f"Não consegui abrir a imagem «{body.rel}».")
    with db.conn() as c:
        cur = c.execute("INSERT INTO people (image, file_hash, source_path) VALUES (?, ?, ?)", (fname, digest, body.rel))
        row = dict(c.execute("SELECT * FROM people WHERE id=?", (cur.lastrowid,)).fetchone())
    row["image_url"] = f"/uploads/{fname}"
    return row
