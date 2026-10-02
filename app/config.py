import json
import os
import uuid
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parent.parent
load_dotenv(ROOT / ".env")

DATA_DIR = Path(os.getenv("WARDROBE_DATA_DIR") or ROOT / "data")  # WARDROBE_DATA_DIR serve para testes não tocarem nos teus dados
UPLOAD_DIR = DATA_DIR / "uploads"
DB_PATH = DATA_DIR / "wardrobe.db"
THUMB_DIR = DATA_DIR / "thumbs"
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)
THUMB_DIR.mkdir(parents=True, exist_ok=True)

# Máximo de peças por outfit / provador (mais peças numa só imagem reduz a fidelidade do Gemini).
MAX_OUTFIT_ITEMS = 8

# --- Definições dos modelos ---
# Valores vêm do ficheiro data/settings.json (editado no ecrã Definições) e, na falta deles, do .env.
SETTINGS_PATH = DATA_DIR / "settings.json"
DEFAULTS = {
    "LLM_BASE_URL": "",
    "LLM_API_KEY": "",
    "LLM_MODEL": "",
    "LLM_VISION_MODEL": "",
    "GEMINI_API_KEY": "",
    "TRYON_MODEL": "gemini-2.5-flash-image",
    # API estilo Gemini (generateContent). Por defeito a da Google; pode apontar para outro fornecedor.
    "TRYON_BASE_URL": "https://generativelanguage.googleapis.com/v1beta",
    "IMPORT_DIR": str(Path.home() / "Desktop" / "Roupa"),
}
SECRETS = {"LLM_API_KEY", "GEMINI_API_KEY"}


def _overrides() -> dict:
    try:
        return json.loads(SETTINGS_PATH.read_text())
    except (OSError, ValueError):
        return {}


def get(name: str) -> str:
    ov = _overrides()
    value = ov[name] if name in ov else os.getenv(name, DEFAULTS[name])
    value = (value or "").strip()
    return value.rstrip("/") if name in ("LLM_BASE_URL", "TRYON_BASE_URL") else value


def save(values: dict) -> None:
    """Grava só chaves conhecidas; uma chave secreta vazia significa 'não alterar'."""
    ov = _overrides()
    for name, value in values.items():
        if name not in DEFAULTS or not isinstance(value, str):
            continue
        if name in SECRETS and not value.strip():
            continue
        ov[name] = value.strip()
    SETTINGS_PATH.write_text(json.dumps(ov, ensure_ascii=False, indent=2))
    SETTINGS_PATH.chmod(0o600)


USER_AGENT = "ocasionly/0.1"
SESSION_ID = str(uuid.uuid4())  # estável enquanto o servidor estiver a correr


def llm_headers() -> dict:
    """Cabeçalhos para o fornecedor de texto/visão. O opencode exige User-Agent próprio e x-opencode-session."""
    headers = {"Authorization": f"Bearer {get('LLM_API_KEY')}", "User-Agent": USER_AGENT}
    if "opencode.ai" in get("LLM_BASE_URL"):
        headers["x-opencode-session"] = SESSION_ID
    return headers


def tryon_key() -> str:
    """Chave do provador; se estiver vazia e o provador apontar para o opencode, usa a chave do opencode."""
    key = get("GEMINI_API_KEY")
    if not key and "opencode.ai" in get("TRYON_BASE_URL"):
        key = get("LLM_API_KEY")
    return key


def tryon_headers() -> dict:
    key = tryon_key()
    base = get("TRYON_BASE_URL")
    headers = {"x-goog-api-key": key, "User-Agent": USER_AGENT}
    # A Google trata "Authorization: Bearer" como token OAuth e rejeita chaves de API (401), por isso só vai para outros fornecedores.
    if "googleapis.com" not in base:
        headers["Authorization"] = f"Bearer {key}"
    if "opencode.ai" in base:
        headers["x-opencode-session"] = SESSION_ID
    return headers


def __getattr__(name: str) -> str:  # config.LLM_MODEL, config.GEMINI_API_KEY, ... sempre atuais
    if name in DEFAULTS:
        return get(name)
    raise AttributeError(name)


def status() -> dict:
    llm = bool(get("LLM_BASE_URL") and get("LLM_API_KEY"))
    return {
        "advice": llm and bool(get("LLM_MODEL")),
        "vision": llm and bool(get("LLM_VISION_MODEL")),
        "tryon": bool(tryon_key()),
    }
