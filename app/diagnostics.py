"""Testes aos modelos configurados: cada função devolve {ok, ms, ...} e nunca lança."""
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
    """Testa o modelo de texto e se consegue devolver JSON (a app precisa disso)."""
    def run():
        model = config.LLM_MODEL
        if not model:
            raise AIError("Define o modelo de texto.")
        raw = ai._chat([{"role": "user", "content": 'Responde APENAS com JSON: {"cor":"azul","numero":3}'}], model, json_mode=True)
        try:
            data = ai._extract_json(raw)
            json_ok = data.get("cor") == "azul"
        except AIError:
            json_ok = False
        return {"model": model, "reply": raw.strip()[:200], "json_ok": json_ok,
                "note": "" if json_ok else "Respondeu, mas não devolveu o JSON pedido. Os conselhos podem falhar com este modelo."}
    return _timed(run)


def vision() -> dict:
    """Envia um quadrado vermelho e pergunta a cor: confirma que o modelo vê mesmo imagens."""
    def run():
        model = config.LLM_VISION_MODEL
        if not model:
            raise AIError("Define o modelo com visão.")
        buf = io.BytesIO()
        Image.new("RGB", (160, 160), (220, 20, 20)).save(buf, "JPEG")
        import base64
        b64 = base64.b64encode(buf.getvalue()).decode()
        content = [
            {"type": "text", "text": "Qual é a cor dominante desta imagem? Responde numa só palavra, em português."},
            {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{b64}"}},
        ]
        raw = ai._chat([{"role": "user", "content": content}], model, json_mode=False)
        saw = any(w in raw.lower() for w in ("vermelh", "red", "encarnad", "rubro"))
        return {"model": model, "reply": raw.strip()[:200], "sees_image": saw,
                "note": "" if saw else "Respondeu, mas não identificou a cor: este modelo pode não aceitar imagens."}
    return _timed(run)


def models() -> dict:
    """Lista os modelos que o fornecedor de texto/visão diz ter (GET /models)."""
    if not (config.LLM_BASE_URL and config.LLM_API_KEY):
        return {"ok": False, "error": "Define o URL base e a chave primeiro.", "models": []}
    try:
        r = httpx.get(f"{config.LLM_BASE_URL}/models", headers=config.llm_headers(), timeout=15)
        r.raise_for_status()
        ids = sorted({m["id"] for m in r.json().get("data", []) if "id" in m})
        return {"ok": True, "models": ids}
    except (httpx.HTTPError, ValueError, KeyError) as e:
        return {"ok": False, "error": f"Não consegui listar os modelos ({e.__class__.__name__}). Escreve o nome à mão.", "models": []}


def gemini_key() -> dict:
    """Gratuito: valida a chave e confirma que o modelo do provador existe."""
    def run():
        if not config.tryon_key():
            raise AIError("Define a chave do provador.")
        try:
            r = httpx.get(f"{config.TRYON_BASE_URL}/models/{config.TRYON_MODEL}", headers=config.tryon_headers(), timeout=15)
        except httpx.HTTPError as e:
            raise AIError(f"Sem ligação ao provador ({e.__class__.__name__}).") from e
        if r.status_code in (400, 401, 403):
            raise AIError("Chave do provador inválida ou sem permissões.")
        if r.status_code == 404:
            raise AIError(f"O modelo «{config.TRYON_MODEL}» não foi encontrado neste endereço. Se usas o opencode, este fornecedor pode não ter modelos de imagem: confirma com o teste de geração.")
        r.raise_for_status()
        return {"model": config.TRYON_MODEL, "note": "Chave e modelo aceites. Isto não confirma a quota nem a faturação: usa o teste de geração."}
    return _timed(run)


def tryon_generation() -> dict:
    """Gera mesmo uma imagem com figuras sintéticas (custa uma geração) para confirmar que o Gemini devolve imagem."""
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
            raw = tryon.generate(names[0], [names[1]], ["t-shirt azul"])
        finally:
            for n in names:
                images.delete(n)
        out = images.save_bytes(raw, "tryon")
        return {"model": config.TRYON_MODEL, "image_url": f"/uploads/{out}", "note": "Recebi uma imagem. A qualidade com fotos reais vê-se no Provador."}
    return _timed(run)
