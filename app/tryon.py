import base64

import httpx

from . import config, images
from .ai import AIError


def generate(person_image: str, item_images: list[str], item_labels: list[str]) -> bytes:
    """Provador virtual com Gemini (edição de imagem): veste a pessoa com as peças dadas."""
    if not config.tryon_key():
        raise AIError("Provador virtual não configurado. Define a chave do provador em ⚙ Modelos.")
    prompt = (
        "A primeira imagem é uma foto de uma pessoa. As imagens seguintes são peças de roupa: "
        + ", ".join(item_labels)
        + ". Gera uma foto realista da mesma pessoa (mesmo rosto, corpo, pose, fundo e iluminação) "
        "a vestir exatamente estas peças, substituindo a roupa e o calçado correspondentes que tem; o que não for indicado mantém-se como está na foto. "
        "Mantém as cores, padrões e cortes das peças fielmente. Corpo inteiro visível, sem texto nem marcas de água."
    )
    parts = [{"text": prompt}, {"inline_data": {"mime_type": "image/jpeg", "data": images.read_b64(person_image)}}]
    parts += [{"inline_data": {"mime_type": "image/jpeg", "data": images.read_b64(n)}} for n in item_images]
    url = f"{config.TRYON_BASE_URL}/models/{config.TRYON_MODEL}:generateContent"
    try:
        r = httpx.post(
            url,
            headers=config.tryon_headers(),
            json={"contents": [{"parts": parts}]},
            timeout=httpx.Timeout(180.0),
        )
        r.raise_for_status()
        for cand in r.json().get("candidates", []):
            for part in cand.get("content", {}).get("parts", []):
                inline = part.get("inlineData") or part.get("inline_data")
                if inline:
                    return base64.b64decode(inline["data"])
    except httpx.HTTPStatusError as e:
        raise AIError(f"Erro do provador ({e.response.status_code}): {e.response.text[:300]}") from e
    except httpx.HTTPError as e:
        raise AIError(f"Falha a contactar o provador: {e}") from e
    raise AIError("O modelo não devolveu nenhuma imagem. Tenta outra foto ou outras peças.")
