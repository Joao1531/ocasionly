import base64
import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps

try:  # fotos HEIC do iPhone
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

from .config import THUMB_DIR, UPLOAD_DIR

MAX_SIDE = 1280


def save_upload(raw: bytes, prefix: str) -> str:
    """Normaliza (orientação EXIF, tamanho máximo, JPEG) e grava. Devolve o nome do ficheiro."""
    img = ImageOps.exif_transpose(Image.open(io.BytesIO(raw)))
    if img.mode not in ("RGB", "L"):
        background = Image.new("RGB", img.size, "white")
        background.paste(img, mask=img.convert("RGBA").split()[-1])
        img = background
    else:
        img = img.convert("RGB")
    img.thumbnail((MAX_SIDE, MAX_SIDE))
    name = f"{prefix}-{uuid.uuid4().hex[:12]}.jpg"
    img.save(UPLOAD_DIR / name, "JPEG", quality=88)
    return name


def save_bytes(raw: bytes, prefix: str) -> str:
    return save_upload(raw, prefix)


def read_b64(name: str, max_side: int | None = None) -> str:
    """Base64 do JPEG guardado; com `max_side` reduz a imagem (menos tokens enviados ao modelo)."""
    path = UPLOAD_DIR / name
    if max_side is None:
        return base64.b64encode(path.read_bytes()).decode()
    img = Image.open(path)
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def thumb_path(name: str) -> Path | None:
    """Miniatura quadrada (192 px) criada à primeira vez que é pedida. None se a imagem não existe."""
    src = UPLOAD_DIR / Path(name).name
    if not src.is_file():
        return None
    dst = THUMB_DIR / src.name
    if not dst.exists():
        ImageOps.fit(Image.open(src).convert("RGB"), (192, 192)).save(dst, "JPEG", quality=82)
    return dst


def delete(name: str) -> None:
    Path(UPLOAD_DIR / name).unlink(missing_ok=True)
    Path(THUMB_DIR / name).unlink(missing_ok=True)
