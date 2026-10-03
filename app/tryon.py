import base64

import httpx

from . import config, images
from .ai import AIError

# The generated image must always have a plain, neutral backdrop, whatever the original photo looked like.
NEUTRAL_BACKGROUND = (
    "Place the person on a plain, seamless, neutral light-grey studio backdrop (about #EDEDED), evenly lit by soft studio light, "
    "with only a soft natural shadow under the feet. Replace the original background completely: no room, walls, furniture, "
    "scenery, objects, patterns, gradients or text."
)
STRICTER = (
    " IMPORTANT: the previous attempt did not have a plain background. The background MUST be one single flat neutral "
    "light-grey colour from edge to edge, with nothing else in it."
)


def _request(prompt: str, person_image: str, item_images: list[str]) -> bytes:
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
        raise AIError(f"Fitting-room error ({e.response.status_code}): {e.response.text[:300]}") from e
    except httpx.HTTPError as e:
        raise AIError(f"Could not reach the fitting-room provider: {e}") from e
    raise AIError("The model returned no image. Try another photo or other garments.")


def generate(person_image: str, item_images: list[str], item_labels: list[str]) -> bytes:
    """Fitting room (image-editing model): dress the person in the given garments, on a neutral background.

    The backdrop of the result is checked; if it is not plain and neutral, one more attempt is made with a stricter
    instruction, and the better-looking of the two is not guessed: the last attempt is returned either way.
    """
    if not config.tryon_key():
        raise AIError("The fitting room is not configured. Set the fitting-room key in ⚙ Models.")
    prompt = (
        "The first image is a photo of a person. The following images are garments: "
        + ", ".join(item_labels)
        + ". Generate a realistic full-body photo of the same person (same face, body and pose) wearing exactly these garments, "
        "replacing the corresponding clothing and footwear they are wearing; anything that is not listed stays as it is in the photo. "
        "Keep the colours, patterns and cuts of the garments faithful. "
        + NEUTRAL_BACKGROUND
        + " The whole body must be visible and centred, with no text and no watermarks."
    )
    raw = _request(prompt, person_image, item_images)
    if not images.background_is_neutral(raw):
        raw = _request(prompt + STRICTER, person_image, item_images)
    return raw
