import base64
import io
import uuid
from pathlib import Path

from PIL import Image, ImageOps, ImageStat

try:  # iPhone HEIC photos
    import pillow_heif

    pillow_heif.register_heif_opener()
except ImportError:
    pass

from .config import THUMB_DIR, UPLOAD_DIR

MAX_SIDE = 1280


def save_upload(raw: bytes, prefix: str) -> str:
    """Normalise (EXIF orientation, maximum size, JPEG) and save. Return the file name."""
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
    """Base64 of the stored JPEG; with `max_side` the image is downscaled (fewer tokens sent to the model)."""
    path = UPLOAD_DIR / name
    if max_side is None:
        return base64.b64encode(path.read_bytes()).decode()
    img = Image.open(path)
    img.thumbnail((max_side, max_side))
    buf = io.BytesIO()
    img.save(buf, "JPEG", quality=85)
    return base64.b64encode(buf.getvalue()).decode()


def thumb_path(name: str) -> Path | None:
    """Square thumbnail (192 px) created the first time it is requested. None if the image does not exist."""
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


def background_is_neutral(raw: bytes) -> bool:
    """Check that the backdrop of a generated image is plain and neutral (grey/white, evenly lit).

    The outer strips on the left, right and top are sampled (the bottom is skipped because feet and floor shadow live
    there). The backdrop passes if it is uniform (low variation), colourless (low saturation) and not dark.
    """
    img = Image.open(io.BytesIO(raw)).convert("RGB")  # measured at full resolution: downscaling would average texture away
    w, h = img.size
    m = max(4, int(min(w, h) * 0.06))
    strips = [img.crop((0, 0, m, h)), img.crop((w - m, 0, w, h)), img.crop((0, 0, w, m))]
    for strip in strips:
        stat = ImageStat.Stat(strip)
        r, g, b = stat.mean
        spread = sum(stat.stddev) / 3
        if max(r, g, b) - min(r, g, b) > 26:  # tinted: a coloured wall, sky, foliage...
            return False
        if spread > 14:  # busy: scenery, furniture, texture (a soft studio vignette stays well below this)
            return False
        if (r + g + b) / 3 < 95:  # dark backdrop
            return False
    return True
