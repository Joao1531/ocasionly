"""Controlled vocabulary shared by the importer and the one-time migration of data saved in Portuguese.

Everything stored by the app is in English. Portuguese words are still *understood* (file names, old data)
and translated to the English vocabulary.
"""
import re
import unicodedata


def norm(s: str) -> str:
    """Lower-case, accent-free form used for comparisons."""
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


# --- values stored in the database by earlier (Portuguese) versions -> current English values ---
LEGACY_CATEGORIES = {
    "t-shirt": "tshirt", "camisa": "shirt", "camisola": "sweater", "calções": "shorts", "calças": "trousers",
    "meias": "socks", "casaco": "coat", "sapatos": "shoes", "acessórios": "accessories",
}
LEGACY_SEASONS = {"primavera/verão": "spring/summer", "outono/inverno": "autumn/winter", "todo o ano": "all year"}
LEGACY_FORMALITY = {"desportivo": "sporty", "casual": "casual", "smart casual": "smart casual", "formal": "formal"}
LEGACY_KINDS = {"preferência": "preference", "regra": "rule", "facto": "fact"}

# --- colours (Portuguese or English word -> English colour) ---
COLOR_WORDS = {
    "branco": "white", "branca": "white", "brancos": "white", "brancas": "white", "white": "white",
    "preto": "black", "preta": "black", "pretos": "black", "pretas": "black", "black": "black",
    "azul": "blue", "azuis": "blue", "blue": "blue",
    "vermelho": "red", "vermelha": "red", "vermelhos": "red", "vermelhas": "red", "red": "red",
    "verde": "green", "verdes": "green", "green": "green",
    "amarelo": "yellow", "amarela": "yellow", "yellow": "yellow",
    "cinza": "grey", "cinzento": "grey", "cinzenta": "grey", "grey": "grey", "gray": "grey",
    "castanho": "brown", "castanha": "brown", "brown": "brown",
    "bege": "beige", "beige": "beige",
    "rosa": "pink", "pink": "pink", "laranja": "orange", "orange": "orange",
    "roxo": "purple", "roxa": "purple", "violeta": "purple", "purple": "purple",
    "bordo": "burgundy", "bordeaux": "burgundy", "burgundy": "burgundy", "vinho": "burgundy",
    "caqui": "khaki", "khaki": "khaki", "navy": "navy",
    "creme": "cream", "cream": "cream",
    "dourado": "gold", "dourada": "gold", "gold": "gold",
    "prateado": "silver", "prateada": "silver", "silver": "silver",
    "turquesa": "turquoise", "turquoise": "turquoise",
    "salmao": "salmon", "salmon": "salmon", "mostarda": "mustard", "mustard": "mustard",
    "oliva": "olive", "olive": "olive", "multicolor": "multicolor", "lilas": "lilac", "areia": "sand",
}
# modifiers go BEFORE the colour in English: "azul claro" -> "light blue", "azul marinho" -> "navy blue"
COLOR_MODIFIERS = {
    "claro": "light", "clara": "light", "light": "light", "escuro": "dark", "escura": "dark", "dark": "dark",
    "marinho": "navy", "marinha": "navy", "forte": "bright", "pastel": "pastel",
}
# "cinzento azulado" -> "bluish grey": the adjective goes before the colour it qualifies
SHADE_ADJECTIVES = {"azulado": "bluish", "acinzentado": "greyish", "esverdeado": "greenish", "avermelhado": "reddish", "amarelado": "yellowish"}
OTHER_WORDS = {"e": "and", "com": "with", "riscas": "stripes", "listras": "stripes", "xadrez": "plaid", "padrao": "pattern"}

MATERIALS = {
    "ganga": "Denim", "denim": "Denim", "algodao": "Cotton", "cotton": "Cotton", "linho": "Linen", "linen": "Linen",
    "couro": "Leather", "pele": "Leather", "leather": "Leather", "la": "Wool", "wool": "Wool", "fleece": "Fleece",
    "sarja": "Twill", "twill": "Twill", "veludo": "Velvet", "velvet": "Velvet", "camurca": "Suede", "suede": "Suede",
    "seda": "Silk", "silk": "Silk", "poliester": "Polyester", "polyester": "Polyester", "malha": "Knit", "knit": "Knit",
    "nylon": "Nylon",
}


def translate_color(text: str) -> str:
    """'azul-marinho e branco' -> 'navy blue and white'. Unknown words are kept as they are."""
    s = re.sub(r"riscas\s+(\w+)", r"\1 stripes", norm(text))  # 'riscas azuis' -> 'azuis stripes'
    out: list[str] = []
    for tok in re.split(r"[\s\-/,]+", s):
        if not tok:
            continue
        if tok in SHADE_ADJECTIVES and out and out[-1] in COLOR_WORDS.values():
            out[-1] = f"{SHADE_ADJECTIVES[tok]} {out[-1]}"
        elif tok in COLOR_MODIFIERS and out and out[-1] in COLOR_WORDS.values():
            out[-1] = f"{COLOR_MODIFIERS[tok]} {out[-1]}"
        elif tok in COLOR_WORDS:
            color = COLOR_WORDS[tok]
            if color == "olive" and out and out[-1] == "green":  # 'verde-oliva' -> 'olive green'
                out[-1] = "olive green"
            else:
                out.append(color)
        elif tok in COLOR_MODIFIERS:
            out.append(COLOR_MODIFIERS[tok])
        else:
            out.append(OTHER_WORDS.get(tok, tok))
    return " ".join(out)


def translate_material(text: str) -> str:
    return " ".join(MATERIALS.get(norm(t), t) for t in text.split())


def untranslated(text: str) -> list[str]:
    """Words of an already translated colour that are not English vocabulary (to report leftovers)."""
    known = set(COLOR_WORDS.values()) | set(COLOR_MODIFIERS.values()) | set(OTHER_WORDS.values()) | set(SHADE_ADJECTIVES.values()) | {"navy", "stripes", "light", "dark"}
    return [w for w in text.split() if w not in known]
