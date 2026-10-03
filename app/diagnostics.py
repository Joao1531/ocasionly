"""Tests for the configured models: each function returns {ok, ms, ...} and never raises."""
import io
import time

import httpx
from PIL import Image, ImageDraw

from . import ai, config, images, tryon
from .ai import AIError


def _timed(fn) -> dict:
    t = time.time()
    try:
        out = fn()
        return {"ok": True, "ms": int((time.time() - t) * 1000), **out}
    except AIError as e:
        return {"ok": False, "ms": int((time.time() - t) * 1000), "error": str(e)}


def text() -> dict:
    """Test the text model, and whether it can return JSON (the app needs that)."""
    def run():
        model = config.LLM_MODEL
        if not model:
            raise AIError("Set the text model.")
        raw = ai._chat([{"role": "user", "content": 'Reply ONLY with JSON: {"color":"blue","number":3}'}], model, json_mode=True)
        try:
            data = ai._extract_json(raw)
            json_ok = data.get("color") == "blue"
        except AIError:
            json_ok = False
        return {"model": model, "reply": raw.strip()[:200], "json_ok": json_ok,
                "note": "" if json_ok else "It answered, but did not return the requested JSON. Styling advice may fail with this model."}
    return _timed(run)


def vision() -> dict:
    """Send a red square and ask for its colour: confirms that the model really sees images."""
    def run():
        model = config.LLM_VISION_MODEL
        if not model:
            raise AIError("Set the vision model.")
        buf = io.BytesIO()
        Image.new("RGB", (160, 160), (220, 20, 20)).save(buf, "JPEG")
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode()
        content = [
            {"type": "text", "text": "What is the dominant colour of this image? Answer in a single word."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]
        raw = ai._chat([{"role": "user", "content": content}], model, json_mode=False)
        saw = any(w in raw.lower() for w in ("red", "crimson", "scarlet", "vermelh"))
        return {"model": model, "reply": raw.strip()[:200], "sees_image": saw,
                "note": "" if saw else "It answered, but did not identify the colour: this model may not accept images."}
    return _timed(run)


def models() -> dict:
    """List the models the text/vision provider says it has (GET /models)."""
    if not (config.LLM_BASE_URL and config.LLM_API_KEY):
        return {"ok": False, "error": "Set the base URL and the key first.", "models": []}
    try:
        r = httpx.get(f"{config.LLM_BASE_URL}/models", headers=config.llm_headers(), timeout=15)
        r.raise_for_status()
        ids = sorted({m["id"] for m in r.json().get("data", []) if "id" in m})
        return {"ok": True, "models": ids}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"ok": False, "error": f"Could not list the models ({e.__class__.__name__}). Type the name by hand.", "models": []}


def gemini_key() -> dict:
    """Free: validates the key and confirms that the fitting-room model exists."""
    def run():
        if not config.tryon_key():
            raise AIError("Set the fitting-room key.")
        try:
            r = httpx.get(f"{config.TRYON_BASE_URL}/models/{config.TRYON_MODEL}", headers=config.tryon_headers(), timeout=15)
        except httpx.HTTPError as e:
            raise AIError(f"Could not reach the fitting-room provider ({e.__class__.__name__}).") from e
        if r.status_code in (400, 401, 403):
            raise AIError("Fitting-room key is invalid or lacks permissions.")
        if r.status_code == 404:
            raise AIError(f"The model «{config.TRYON_MODEL}» was not found at this address. If you use opencode, this provider may not have image models: confirm with the generation test.")
        r.raise_for_status()
        return {"model": config.TRYON_MODEL, "note": "Key and model accepted. This does not confirm quota or billing: use the generation test."}
    return _timed(run)


def tryon_generation() -> dict:
    """Really generate an image from synthetic figures (costs one generation) to confirm that the model returns an image."""
    def run():
        person = Image.new("RGB", (512, 768), (235, 235, 235))
        d = ImageDraw.Draw(person)
        d.ellipse((216, 80, 296, 160), fill=(200, 160, 130))
        d.rectangle((196, 170, 316, 420), fill=(150, 150, 150))
        d.rectangle((206, 420, 306, 700), fill=(90, 90, 110))
        shirt = Image.new("RGB", (400, 400), (240, 240, 240))
        ImageDraw.Draw(shirt).rectangle((80, 60, 320, 340), fill=(30, 70, 200))
        names = []
        for img, prefix in ((person, "tmp"), (shirt, "tmp")):
            buf = io.BytesIO()
            img.save(buf, "PNG")
            names.append(images.save_upload(buf.getvalue(), prefix))
        try:
            raw = tryon.generate(names[0], [names[1]], ["blue t-shirt"])
        finally:
            for n in names:
                images.delete(n)
        out = images.save_bytes(raw, "tryon")
        return {"model": config.TRYON_MODEL, "image_url": f"/uploads/{out}", "note": "Received an image. Quality with real photos can be judged in the Fitting room."}
    return _timed(run)
