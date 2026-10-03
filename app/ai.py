import json
import re

import httpx

from . import config, db, images, vocab

TIMEOUT = httpx.Timeout(120.0)

# Usage since the server started (the provider returns `usage` in every response).
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
        raise AIError("The AI model is not configured. Open ⚙ Models and fill in the connection settings.")
    body = {"model": model, "messages": messages, "temperature": 0.7}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    try:
        r = _post(body)
        if r.status_code == 400 and json_mode:
            # Some models do not support response_format: try again without it.
            body.pop("response_format")
            r = _post(body)
        r.raise_for_status()
        data = r.json()
        _record(data)
        return data["choices"][0]["message"]["content"] or ""
    except httpx.HTTPStatusError as e:
        raise AIError(f"Model error ({e.response.status_code}): {e.response.text[:300]}") from e
    except (httpx.HTTPError, KeyError, IndexError) as e:
        raise AIError(f"Could not reach the model: {e}") from e


def _extract_json(text: str) -> dict:
    text = re.sub(r"<think>.*?</think>", "", text, flags=re.S).strip()
    fence = re.search(r"```(?:json)?\s*(.*?)```", text, flags=re.S)
    if fence:
        text = fence.group(1).strip()
    start, end = text.find("{"), text.rfind("}")
    if start == -1 or end == -1:
        raise AIError("The model did not return valid JSON.")
    try:
        return json.loads(text[start : end + 1])
    except json.JSONDecodeError as e:
        raise AIError("The model returned malformed JSON.") from e


KINDS = ("preference", "rule", "fact")


def _clean_learned(raw) -> list[dict]:
    out = []
    for x in raw if isinstance(raw, list) else []:
        text = (x.get("text") if isinstance(x, dict) else x) or ""
        text = str(text).strip()[:200]
        if text:
            kind = x.get("kind") if isinstance(x, dict) and x.get("kind") in KINDS else "fact"
            out.append({"text": text, "kind": kind})
    return out[:5]


ANALYZE_SIDE = 384  # colour/season/formality do not need high resolution: fewer tokens per photo
SEASONS = ("spring/summer", "autumn/winter", "all year")
FORMALITIES = ("sporty", "casual", "smart casual", "formal")


def analyze_item(image_name: str) -> dict:
    """Use a vision model to suggest the fields of a garment."""
    prompt = (
        "Analyse this garment and reply ONLY with JSON containing these keys: "
        '"name" (short English name; for accessories state the type: belt, hat, sunglasses, watch, etc.), '
        f'"category" (one of: {", ".join(db.CATEGORY_IDS)}; "sweater" includes hoodies, sweatshirts and knitted jumpers), '
        '"color" (main colour, in English), '
        f'"season" (one of: {", ".join(SEASONS)}), '
        f'"formality" (one of: {", ".join(FORMALITIES)}).'
    )
    content = [
        {"type": "text", "text": prompt},
        {"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{images.read_b64(image_name, ANALYZE_SIDE)}"}},
    ]
    data = _extract_json(_chat([{"role": "user", "content": content}], config.LLM_VISION_MODEL, json_mode=True))
    category = str(data.get("category", "")).strip().lower()
    season = vocab.LEGACY_SEASONS.get(str(data.get("season", "")).strip().lower(), str(data.get("season", "")).strip().lower())
    formality = vocab.LEGACY_FORMALITY.get(str(data.get("formality", "")).strip().lower(), str(data.get("formality", "")).strip().lower())
    return {
        "name": str(data.get("name", "")).strip(),
        "category": vocab.LEGACY_CATEGORIES.get(category, category) if vocab.LEGACY_CATEGORIES.get(category, category) in db.CATEGORY_IDS else "",
        "color": vocab.translate_color(str(data.get("color", ""))),  # also accepts Portuguese answers
        "season": season if season in SEASONS else "",
        "formality": formality if formality in FORMALITIES else "",
    }


SYSTEM_TEMPLATE = """You are a personal stylist. You speak English, in a direct and friendly way.
You receive the user's wardrobe: each garment has an id, a file name and (when available) a photo. You also receive a request (event, weather, occasion).
Look at the photos and put together 2 to 3 outfits using ONLY garments from the list, referenced by id.
Consider: suitability for the event, weather/season, formality, colour and pattern combinations (look at the photos), sizes and the user's profile.
The wardrobe only has these categories: tshirt, shirt, sweater (hoodies, sweatshirts and knitted jumpers), shorts, trousers, socks, coat, shoes, accessories (belt, hat, sunglasses, watch, etc.; the type is in the name).
Each outfit must be wearable all at once: one T-shirt OR one shirt, with a sweater/hoodie on top if the weather or style calls for it (the sweater is the middle layer between the T-shirt/shirt and the coat), trousers OR shorts, socks if they are needed, a coat if the weather or the event calls for one, a pair of shoes suited to the event and, if they add to the look, accessories (a belt matching the shoes, a watch, sunglasses only if the event and weather make sense, a hat only if it works). Never two accessories of the same type. At most {max} garments; if there are more candidates, prioritise the ones that matter most to the look.
If an essential garment is missing, say so in "missing" instead of inventing garments.

MEASUREMENTS: the profile includes the user's height, weight and usual sizes (when provided). Use them properly:
- Compare the size of each chosen garment with the usual size for its category and say in "fit_note" whether it should fit well, loose or tight (e.g. "this shirt is L and you wear M: it will be loose on the shoulders"). Prefer garments whose size matches the usual one; if you choose one that does not match, justify it.
- If a garment has no size, or you do not know the usual size, do not make one up: say that the fit cannot be confirmed.
- Use height and weight for proportions: length of coats and sleeves, trousers that suit the person's height, cuts that flatter the silhouette.

MEMORY: you are a stylist who has known the user for a long time. You receive the base profile, the memory (what you have already learned) and the recent history of requests and reactions.
- Respect the memory as confirmed rules and tastes; do not ask again what you already know. If something in the request contradicts the memory, the current request wins.
- Use the history for continuity (the user may say "and with other shoes?") and to avoid repeating outfits the user rejected or that you suggested recently, unless they ask.
- In "learned" list new DURABLE facts that the user explicitly stated in the current request (tastes, rules, measurements, habits, restrictions, e.g. "I don't wear brown", "I prefer shirts untucked"). Do NOT store details of today's event, things already in the memory, or your own inferences. If there is nothing, return [].
Reply ONLY with JSON in this format:
{"outfits":[{"title":"...","item_ids":[1,2],"why":"why it works for this event","how_to_wear":"how to wear and combine it (sleeves, tucked in or out, etc.)","fit_note":"what will suit them best and why","missing":""}],
"general_tip":"short closing tip","learned":[{"text":"short, self-contained fact","kind":"preference|rule|fact"}]}"""

SYSTEM = SYSTEM_TEMPLATE.replace("{max}", str(config.MAX_OUTFIT_ITEMS))

MAX_IMAGES = 24       # photos sent per request
THUMB = 400           # longest side of the photos sent (fewer tokens per photo)
SHORTLIST_ABOVE = MAX_IMAGES  # above this many garments, a text-only shortlist is made first
MAX_CANDIDATES = 24

CATALOG_FIELDS = ("category", "name", "color", "size", "brand", "model", "fit", "material", "season", "formality", "notes")
CATALOG_HEADER = "id|category|name|color|size|brand|model|fit|material|season|formality|notes   (empty field = unknown)"


def catalog_line(it: dict) -> str:
    """One compact line per garment: far fewer tokens than one JSON object per garment."""
    return "|".join([str(it["id"])] + [str(it.get(k) or "").replace("|", "/").replace("\n", " ") for k in CATALOG_FIELDS])


SHORTLIST_SYSTEM = """You are a personal stylist. You receive the wardrobe catalogue (one garment per line), the user's profile and memory, and a request.
Choose up to {n} ids of the garments that are MOST relevant for putting together outfits for that request: event, weather, formality, memory rules, usual sizes.
Make sure there is enough variety: several options in each category that is needed (tops, bottoms, shoes, a coat if the weather calls for one, useful accessories).
Leave out garments that break memory rules (e.g. colours the user avoids) or that do not suit the request.
Reply ONLY with JSON: {{"ids":[1,2,3]}}"""


def _shortlist(prompt: str, items: list[dict], profile: str, memory_text: str) -> list[int]:
    user = (
        f"Profile: {profile or 'not provided'}\nMemory:\n{memory_text or '(empty)'}\n\nCatalogue ({len(items)} garments):\n{CATALOG_HEADER}\n"
        + "\n".join(catalog_line(it) for it in items)
        + f"\n\nRequest: {prompt}"
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
    """With many garments, a first text-only call picks candidates; only those are sent with photos and full data.
    If a vision model is configured the stylist sees the photos of those garments; otherwise it uses the data only."""
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
            note = "The shortlist step failed: I used the whole catalogue, without photos."
    # Photos only when the set is small: at most MAX_IMAGES garments, or the shortlist worked.
    vision = bool(config.LLM_VISION_MODEL) and not note
    model = config.LLM_VISION_MODEL if vision else config.LLM_MODEL

    # The catalogue (and photos) go first and what changes on every request goes last: helps the provider's prompt cache.
    content = [{"type": "text", "text": f"Wardrobe ({len(items)} garments):\n{CATALOG_HEADER}"}]
    for n, it in enumerate(items):
        content.append({"type": "text", "text": catalog_line(it) + f"  (file {it['image']})"})
        if vision and n < MAX_IMAGES:
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{images.read_b64(it['image'], THUMB)}"}})
    content.append({"type": "text", "text": (
        f"User's base profile: {profile or 'not provided'}\n\nMemory (what you already know):\n{memory_text or '(empty)'}\n\n"
        f"Recent history:\n{history_text or '(no history)'}\n\nRequest: {prompt}")})

    data = _extract_json(_chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": content}], model, json_mode=True))
    data["learned"] = _clean_learned(data.get("learned"))
    valid = {it["id"] for it in items}
    for o in data.get("outfits", []):
        o["item_ids"] = [i for i in o.get("item_ids", []) if i in valid][: config.MAX_OUTFIT_ITEMS]
    data["usage"] = usage_since(start)
    data["considered"] = {"total": len(all_items), "sent": len(items), "photos": min(len(items), MAX_IMAGES) if vision else 0, "note": note}
    return data


SUGGEST_SYSTEM = """You are a personal stylist. You speak English.
Based on the user's wardrobe (garments with id), their profile (height, weight and sizes included: suggest sizes that will fit) and their stores, suggest 4 to 6 NEW garments worth buying:
garments that are missing, that go with several of the ones they already own, or that elevate their looks. Do not repeat garments they already own or items already on the wishlist.
For each suggestion choose a category (tshirt, shirt, sweater, shorts, trousers, socks, coat, shoes, accessories), give the ids of the wardrobe garments it goes with, and the store.
Stores: use ONLY stores from the "interested" list; never use the ones from the "not interested" list. If the interested list is empty, leave "store" empty.
Do not invent links or prices: give a short, precise "search_query" (garment type, colour, cut, material) so they can search for it.
Reply ONLY with JSON:
{"suggestions":[{"title":"...","category":"trousers","why":"why it suits them and what it goes with","combines_with":[1,2],"store":"","search_query":"..."}]}"""


def suggest_purchases(prompt: str, items: list[dict], profile: str, liked: list[str], avoided: list[str], wishes: list[str], memory_text: str = "") -> dict:
    wardrobe = CATALOG_HEADER + "\n" + "\n".join(catalog_line(it) for it in items)
    user = (
        f"Profile: {profile or 'not provided'}\n"
        f"Memory (tastes, rules and facts already confirmed; respect them):\n{memory_text or '(empty)'}\n"
        f"Interested stores: {', '.join(liked) or 'none provided'}\n"
        f"Not interested stores: {', '.join(avoided) or 'none'}\n"
        f"Already on the wishlist: {'; '.join(wishes) or 'nothing'}\n\n"
        f"Wardrobe:\n{wardrobe}\n\n"
        f"User's request: {prompt or 'Suggest what I am missing or what would improve my wardrobe the most.'}"
    )
    data = _extract_json(_chat([{"role": "system", "content": SUGGEST_SYSTEM}, {"role": "user", "content": user}], config.LLM_MODEL, json_mode=True))
    data["suggestions"] = [s for s in data.get("suggestions", []) if isinstance(s, dict) and s.get("title")]
    return data


FEEDBACK_SYSTEM = """You learn from the user's feedback on an outfit you suggested.
Extract 0 to 3 DURABLE, general facts about their tastes or rules (not about this specific event), as short self-contained sentences in English.
Do not repeat what is already in the memory. If the comment is only about this event, return [].
Reply ONLY with JSON: {"learned":[{"text":"...","kind":"preference|rule|fact"}]}"""


def learn_from_feedback(outfit_desc: str, rating: int, comment: str, memory_text: str) -> list[dict]:
    user = (
        f"Suggested outfit: {outfit_desc}\nReaction: {'liked it' if rating > 0 else 'did not like it'}\n"
        f"Comment: {comment}\n\nCurrent memory:\n{memory_text or '(empty)'}"
    )
    data = _extract_json(_chat([{"role": "system", "content": FEEDBACK_SYSTEM}, {"role": "user", "content": user}], config.LLM_MODEL, json_mode=True))
    return _clean_learned(data.get("learned"))
