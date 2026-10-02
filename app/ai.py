import json
import re

import httpx

from . import config, images

TIMEOUT = httpx.Timeout(120.0)

# Consumo desde que o servidor arrancou (o fornecedor devolve `usage` em cada resposta).
USAGE = {"calls": 0, "prompt_tokens": 0, "completion_tokens": 0}


def _record(data: dict) -> None:
    u = data.get("usage") or {}
    USAGE["calls"] += 1
    USAGE["prompt_tokens"] += int(u.get("prompt_tokens") or 0)
    USAGE["completion_tokens"] += int(u.get("completion_tokens") or 0)


def usage_since(start: dict) -> dict:
    return {k: USAGE[k] - start[k] for k in USAGE}


class AIError(Exception):
    pass


def _post(body: dict) -> httpx.Response:
    return httpx.post(
        f"{config.LLM_BASE_URL}/chat/completions",
        headers=config.llm_headers(),
        json=body,
        timeout=TIMEOUT,
    )


def _chat(messages: list, model: str, json_mode: bool = False) -> str:
    if not (config.LLM_BASE_URL and config.LLM_API_KEY and model):
        raise AIError("Modelo de IA não configurado. Preenche LLM_* no ficheiro .env.")
    body = {"model": model, "messages": messages, "temperature": 0.7}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = _post(body)
        if r.status_code == 400 and json_mode:
            # Alguns modelos não suportam response_format: tenta sem.
            body.pop("response_format")
            r = _post(body)
        r.raise_for_status()
        data = r.json()
        _record(data)
        return data["choices"][0]["message"]["content"] or ""
    except httpx.HTTPStatusError as e:
        raise AIError(f"Erro do modelo ({e.response.status_code}): {e.response.text[:300]}") from e
    except (httpx.HTTPError, KeyError, IndexError) as e:
        raise AIError(f"Falha a contactar o modelo: {e}") from e


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("O modelo não devolveu JSON válido.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise AIError("O modelo devolveu JSON inválido.") from e


KINDS = ("preferência", "regra", "facto")


def _clean_learned(raw) -> list[dict]:
    out = []
    for x in raw if isinstance(raw, list) else []:
        text = (x.get("text") if isinstance(x, dict) else x) or ""
        text = str(text).strip()[:200]
        if text:
            kind = x.get("kind") if isinstance(x, dict) and x.get("kind") in KINDS else "facto"
            out.append({"text": text, "kind": kind})
    return out[:5]


ANALYZE_SIDE = 384  # cor/estação/formalidade não precisam de resolução alta: menos tokens por foto


def analyze_item(image_name: str) -> dict:
    """Usa um modelo com visão para sugerir os campos de uma peça."""
    prompt = (
        "Analisa esta peça de roupa e responde APENAS com JSON com as chaves: "
        '"name" (nome curto em português de Portugal; para acessórios diz o tipo: cinto, chapéu, óculos de sol, relógio, etc.), "category" (uma de: t-shirt, camisa, camisola, calções, calças, meias, casaco, sapatos, acessórios; "camisola" inclui hoodies, sweats e camisolas de malha), "color" (cor principal), '
        '"season" (primavera/verão, outono/inverno ou todo o ano), '
        '"formality" (desportivo, casual, smart casual ou formal).'
    )
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{images.read_b64(image_name, ANALYZE_SIDE)}"}},
    ]
    data = _extract_json(_chat([{"role": "user", "content": content}], config.LLM_VISION_MODEL, json_mode=True))
    return {k: str(data.get(k, "")) for k in ("name", "category", "color", "season", "formality")}


SYSTEM_TEMPLATE = """És um estilista pessoal. Falas português de Portugal, de forma direta e amigável.
Recebes o guarda-roupa do utilizador: cada peça tem um id, um ficheiro e (quando disponível) a fotografia. Recebes também um pedido (evento, clima, ocasião).
Olha para as fotografias e monta 2 a 3 outfits usando APENAS peças da lista, referenciadas pelo id.
Considera: adequação ao evento, clima/estação, formalidade, combinação de cores e padrões (vê as fotos), tamanhos e o perfil do utilizador.
O guarda-roupa só tem estas categorias: t-shirt, camisa, camisola (hoodies, sweats e camisolas de malha), calções, calças, meias, casaco, sapatos, acessórios (cinto, chapéu, óculos de sol, relógio, etc.; o tipo vem no nome).
Cada outfit deve ser vestível de uma só vez: uma t-shirt OU uma camisa, com uma camisola/hoodie por cima se o clima ou o estilo pedirem (a camisola faz de camada intermédia entre a t-shirt/camisa e o casaco), calças OU calções, meias se fizerem falta, um casaco se o clima ou o evento pedirem, um par de sapatos adequado ao evento e, se acrescentarem ao look, acessórios (cinto a condizer com os sapatos, relógio, óculos de sol só se o evento e o clima fizerem sentido, chapéu só se combinar). Nunca dois acessórios do mesmo tipo. No máximo {max} peças; se houver mais candidatas, prioriza as que mais contam para o look.
Se faltar uma peça essencial, diz isso em "missing" em vez de inventar peças.

MEDIDAS: o perfil inclui altura, peso e tamanhos habituais do utilizador (quando indicados). Usa-os a sério:
- Compara o tamanho de cada peça escolhida com o tamanho habitual da categoria e diz em "fit_note" se deve servir bem, ficar largo ou justo (ex.: «esta camisa é L e usas M: fica larga nos ombros»). Prefere peças cujo tamanho coincide com o habitual; se escolheres uma que não coincide, justifica.
- Se a peça não tem tamanho indicado ou não sabes o tamanho habitual, não inventes: diz que não é possível confirmar o ajuste.
- Usa a altura e o peso para proporções: comprimento de casacos e mangas, calças a condizer com a estatura, cortes que favorecem a silhueta.

MEMÓRIA: és um estilista que conhece o utilizador há muito tempo. Recebes o perfil base, a memória (o que já aprendeste) e o histórico recente de pedidos e reações.
- Respeita a memória como regras e gostos já confirmados; não voltes a perguntar o que já sabes. Se algo no pedido contradiz a memória, o pedido atual manda.
- Usa o histórico para dar continuidade (o utilizador pode dizer "e com outros sapatos?") e para não repetires outfits que ele recusou ou que já te sugeriu há pouco, salvo se ele pedir.
- Em "learned" lista novos factos DURÁVEIS que o utilizador afirmou de forma explícita no pedido atual (gostos, regras, medidas, hábitos, restrições, ex.: "Não uso castanho", "Prefere camisas por fora"). NÃO guardes detalhes do evento de hoje, nem coisas já presentes na memória, nem deduções tuas. Se não houver nada, devolve [].
Responde APENAS com JSON neste formato:
{"outfits":[{"title":"...","item_ids":[1,2],"why":"porque funciona para este evento","how_to_wear":"como vestir/combinar (mangas, por dentro/fora, etc.)","fit_note":"o que lhe ficará melhor e porquê","missing":""}],
"general_tip":"conselho final curto","learned":[{"text":"facto curto e autónomo","kind":"preferência|regra|facto"}]}"""

SYSTEM = SYSTEM_TEMPLATE.replace("{max}", str(config.MAX_OUTFIT_ITEMS))

MAX_IMAGES = 24       # fotos enviadas por pedido
THUMB = 400           # lado maior das fotos enviadas (menos tokens por foto)
SHORTLIST_ABOVE = MAX_IMAGES  # com mais peças que isto, primeiro escolhe-se uma lista curta só com texto
MAX_CANDIDATES = 24

CATALOG_FIELDS = ("category", "name", "color", "size", "brand", "model", "fit", "material", "season", "formality", "notes")
CATALOG_HEADER = "id|categoria|nome|cor|tamanho|marca|modelo|corte|material|estação|formalidade|notas   (campo vazio = desconhecido)"


def catalog_line(it: dict) -> str:
    """Uma linha compacta por peça: bastante menos tokens do que um JSON por peça."""
    return "|".join([str(it["id"])] + [str(it.get(k) or "").replace("|", "/").replace("\n", " ") for k in CATALOG_FIELDS])


SHORTLIST_SYSTEM = """És um estilista pessoal. Recebes o catálogo do guarda-roupa (uma peça por linha), o perfil e a memória do utilizador e um pedido.
Escolhe até {n} ids das peças MAIS relevantes para montar outfits para esse pedido: evento, clima, formalidade, regras da memória, tamanhos habituais.
Garante variedade suficiente: várias opções de cada categoria necessária (parte de cima, parte de baixo, sapatos, casaco se o clima pedir, acessórios úteis).
Deixa de fora peças que quebram regras da memória (ex.: cores que o utilizador evita) ou que não servem ao pedido.
Responde APENAS com JSON: {{"ids":[1,2,3]}}"""


def _shortlist(prompt: str, items: list[dict], profile: str, memory_text: str) -> list[int]:
    user = (
        f"Perfil: {profile or 'não indicado'}\nMemória:\n{memory_text or '(vazia)'}\n\nCatálogo ({len(items)} peças):\n{CATALOG_HEADER}\n"
        + "\n".join(catalog_line(it) for it in items)
        + f"\n\nPedido: {prompt}"
    )
    data = _extract_json(_chat(
        [{"role": "system", "content": SHORTLIST_SYSTEM.format(n=MAX_CANDIDATES)}, {"role": "user", "content": user}],
        config.LLM_MODEL, json_mode=True))
    valid = {it["id"] for it in items}
    ids = []
    for i in data.get("ids", []):
        if isinstance(i, int) and i in valid and i not in ids:
            ids.append(i)
    return ids[:MAX_CANDIDATES]


def advise(prompt: str, items: list[dict], profile: str, memory_text: str = "", history_text: str = "") -> dict:
    """Com muitas peças, uma 1.ª chamada só de texto escolhe candidatas; só dessas se enviam fotos (e dados completos).
    Se houver modelo com visão, o estilista vê as fotos dessas peças; senão usa só os dados."""
    start = dict(USAGE)
    all_items = items
    note = ""
    if len(items) > SHORTLIST_ABOVE:
        try:
            ids = _shortlist(prompt, items, profile, memory_text)
        except AIError:
            ids = []
        if len(ids) >= 3:
            keep = set(ids)
            items = [it for it in items if it["id"] in keep]
        else:
            note = "A lista curta falhou: usei todo o catálogo, sem fotos."
    # Fotos só quando o conjunto é pequeno: ≤ MAX_IMAGES peças, ou a lista curta funcionou.
    vision = bool(config.LLM_VISION_MODEL) and not note
    model = config.LLM_VISION_MODEL if vision else config.LLM_MODEL

    # O catálogo (e as fotos) vai primeiro e o que muda a cada pedido vai no fim: ajuda a cache de prompt do fornecedor.
    content = [{"type": "text", "text": f"Guarda-roupa ({len(items)} peças):\n{CATALOG_HEADER}"}]
    for n, it in enumerate(items):
        content.append({"type": "text", "text": catalog_line(it) + f"  (ficheiro {it['image']})"})
        if vision and n < MAX_IMAGES:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{images.read_b64(it['image'], THUMB)}"}})
    content.append({"type": "text", "text": (
        f"Perfil base do utilizador: {profile or 'não indicado'}\n\nMemória (o que já sabes):\n{memory_text or '(vazia)'}\n\n"
        f"Histórico recente:\n{history_text or '(sem histórico)'}\n\nPedido: {prompt}")})

    data = _extract_json(_chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}], model, json_mode=True))
    data["learned"] = _clean_learned(data.get("learned"))
    valid = {it["id"] for it in items}
    for o in data.get("outfits", []):
        o["item_ids"] = [i for i in o.get("item_ids", []) if i in valid][: config.MAX_OUTFIT_ITEMS]
    data["usage"] = usage_since(start)
    data["considered"] = {"total": len(all_items), "sent": len(items), "photos": min(len(items), MAX_IMAGES) if vision else 0, "note": note}
    return data


SUGGEST_SYSTEM = """És um estilista pessoal. Falas português de Portugal.
Com base no guarda-roupa do utilizador (peças com id), no perfil (altura, peso e tamanhos incluídos: sugere tamanhos que lhe sirvam) e nas lojas, sugere 4 a 6 peças NOVAS que valia a pena comprar:
peças que faltam, que combinam com várias das que já tem, ou que elevam os looks. Não repitas peças que ele já tem nem itens da lista de desejos.
Para cada sugestão escolhe uma categoria (t-shirt, camisa, camisola, calções, calças, meias, casaco, sapatos, acessórios), indica ids das peças do armário com que combina, e a loja.
Lojas: usa APENAS lojas da lista "com interesse"; nunca uses as da lista "sem interesse". Se a lista de interesse estiver vazia, deixa "store" vazio.
Não inventas links nem preços: dá uma "search_query" curta e precisa (tipo de peça, cor, corte, material) para ele pesquisar.
Responde APENAS com JSON:
{"suggestions":[{"title":"...","category":"calças","why":"porque lhe serve, com o que combina","combines_with":[1,2],"store":"","search_query":"..."}]}"""


def suggest_purchases(prompt: str, items: list[dict], profile: str, liked: list[str], avoided: list[str], wishes: list[str], memory_text: str = "") -> dict:
    wardrobe = CATALOG_HEADER + "\n" + "\n".join(catalog_line(it) for it in items)
    user = (
        f"Perfil: {profile or 'não indicado'}\n"
        f"Memória (gostos, regras e factos já confirmados; respeita-os):\n{memory_text or '(vazia)'}\n"
        f"Lojas com interesse: {', '.join(liked) or 'nenhuma indicada'}\n"
        f"Lojas sem interesse: {', '.join(avoided) or 'nenhuma'}\n"
        f"Já na lista de desejos: {'; '.join(wishes) or 'nada'}\n\n"
        f"Guarda-roupa:\n{wardrobe}\n\n"
        f"Pedido do utilizador: {prompt or 'Sugere o que me falta ou o que mais valorizaria o meu armário.'}"
    )
    data = _extract_json(_chat([{"role": "system", "content": SUGGEST_SYSTEM}, {"role": "user", "content": user}], config.LLM_MODEL, json_mode=True))
    data["suggestions"] = [s for s in data.get("suggestions", []) if isinstance(s, dict) and s.get("title")]
    return data


FEEDBACK_SYSTEM = """Aprendes com o feedback do utilizador sobre um outfit que sugeriste.
Extrai 0 a 3 factos DURÁVEIS e gerais sobre os gostos ou regras dele (não sobre este evento em concreto), em frases curtas e autónomas em português de Portugal.
Não repitas o que já está na memória. Se o comentário for só sobre este evento, devolve [].
Responde APENAS com JSON: {"learned":[{"text":"...","kind":"preferência|regra|facto"}]}"""


def learn_from_feedback(outfit_desc: str, rating: int, comment: str, memory_text: str) -> list[dict]:
    user = (
        f"Outfit sugerido: {outfit_desc}\nReação: {'gostou' if rating > 0 else 'não gostou'}\n"
        f"Comentário: {comment}\n\nMemória atual:\n{memory_text or '(vazia)'}"
    )
    data = _extract_json(_chat([{"role": "system", "content": FEEDBACK_SYSTEM}, {"role": "user", "content": user}], config.LLM_MODEL, json_mode=True))
    return _clean_learned(data.get("learned"))
