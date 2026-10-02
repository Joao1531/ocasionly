from fastapi import APIRouter, HTTPException
from pydantic import BaseModel

from . import ai, config, diagnostics

router = APIRouter(prefix="/api/settings")


def _public() -> dict:
    out = {}
    for name in config.DEFAULTS:
        value = config.get(name)
        if name in config.SECRETS:
            out[f"{name}_set"] = bool(value)
            out[f"{name}_hint"] = f"••••{value[-4:]}" if len(value) >= 8 else ("••••" if value else "")
        else:
            out[name] = value
    return out


@router.get("")
def get_settings():
    return _public()


class SettingsIn(BaseModel):
    LLM_BASE_URL: str | None = None
    LLM_API_KEY: str | None = None
    LLM_MODEL: str | None = None
    LLM_VISION_MODEL: str | None = None
    GEMINI_API_KEY: str | None = None
    TRYON_MODEL: str | None = None
    TRYON_BASE_URL: str | None = None


@router.put("")
def put_settings(body: SettingsIn):
    values = {k: v for k, v in body.model_dump().items() if v is not None}
    for field in ("LLM_BASE_URL", "TRYON_BASE_URL"):
        url = values.get(field)
        if url and not url.startswith(("http://", "https://")):
            raise HTTPException(400, "Os URLs têm de começar por http:// ou https://.")
    config.save(values)
    return _public()


@router.get("/usage")
def usage():
    return ai.USAGE


@router.get("/models")
def list_models():
    return diagnostics.models()


@router.post("/test/{kind}")
def run_test(kind: str):
    tests = {
        "text": diagnostics.text,
        "vision": diagnostics.vision,
        "gemini-key": diagnostics.gemini_key,
        "tryon": diagnostics.tryon_generation,
    }
    if kind not in tests:
        raise HTTPException(404)
    return tests[kind]()
