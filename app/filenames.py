"""Interpreta nomes de ficheiro como `Calças_Ganga_Levis_511_W33_L34.jpg`.

As partes vêm separadas por `_` e sem ordem fixa, por isso cada parte é classificada pelo que é:
tamanho (M, 44, W33, L34), cor, corte, material, tipo de peça ou marca/modelo (o que sobra).
O resultado é só uma proposta: tudo fica editável na app.
"""
import re
import unicodedata

SIZES = {"xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl", "3xl", "4xl"}
COLORS = {
    "branco", "branca", "preto", "preta", "azul", "vermelho", "vermelha", "verde", "amarelo", "amarela", "cinza", "cinzento",
    "cinzenta", "castanho", "castanha", "bege", "beige", "rosa", "laranja", "roxo", "roxa", "violeta", "bordeaux", "caqui",
    "navy", "creme", "dourado", "dourada", "prateado", "prateada", "turquesa", "salmao", "mostarda", "oliva", "multicolor",
    "white", "black", "blue", "red", "green", "yellow", "grey", "gray", "brown", "pink", "orange", "purple", "khaki", "cream",
}
COLOR_MODIFIERS = {"claro", "clara", "escuro", "escura", "marinho", "marinha", "forte", "pastel"}
FITS = {"wide", "slim", "regular", "oversize", "oversized", "baggy", "skinny", "straight", "relaxed", "loose", "tapered", "boxy", "cropped", "fit", "comfort"}
MATERIALS = {"ganga", "denim", "algodao", "linho", "couro", "pele", "la", "fleece", "sarja", "veludo", "camurca", "seda", "poliester", "malha", "nylon"}
# palavra do tipo de peça -> (categoria, rótulo para o nome); a categoria vem da pasta, isto só dá o rótulo
TYPES = {
    "tshirt": "T-shirt", "tee": "T-shirt", "camisa": "Camisa", "polo": "Polo", "camisola": "Camisola", "sweat": "Sweat",
    "hoodie": "Hoodie", "casaco": "Casaco", "blazer": "Blazer", "parka": "Parka", "blusao": "Blusão", "calcas": "Calças",
    "calcoes": "Calções", "bermudas": "Bermudas", "meias": "Meias", "sapatos": "Sapatos", "tenis": "Ténis", "botas": "Botas",
    "sandalias": "Sandálias", "chapeu": "Chapéu", "bone": "Boné", "gorro": "Gorro", "cinto": "Cinto", "relogio": "Relógio",
    "oculos": "Óculos", "cachecol": "Cachecol", "luvas": "Luvas", "gravata": "Gravata", "mala": "Mala", "carteira": "Carteira",
}
# pasta (normalizada) -> id da categoria na app
FOLDERS = {
    "tshirt": "t-shirt", "tshirts": "t-shirt",
    "camisa": "camisa", "camisas": "camisa",
    "camisola": "camisola", "camisolas": "camisola", "hoodie": "camisola", "hoodies": "camisola", "sweat": "camisola", "sweats": "camisola",
    "hoodiecamisola": "camisola", "hoodiecamisolas": "camisola", "hoodiescamisolas": "camisola", "hoodieecamisolas": "camisola",
    "hoodiesecamisolas": "camisola", "camisolashoodies": "camisola", "camisolasehoodies": "camisola", "camisolahoodie": "camisola",
    "calcoes": "calções", "calcao": "calções",
    "calcas": "calças", "calca": "calças", "meias": "meias", "meia": "meias",
    "casaco": "casaco", "casacos": "casaco", "sapatos": "sapatos", "sapato": "sapatos",
    "acessorios": "acessórios", "acessorio": "acessórios",
}
KNOWN_BRANDS = {
    "nike", "adidas", "puma", "reebok", "newbalance", "asics", "converse", "vans", "levis", "wrangler", "lee", "diesel", "zara",
    "lefties", "bershka", "pullbear", "stradivarius", "massimodutti", "mango", "hm", "uniqlo", "primark", "cortefiel", "springfield",
    "tommyhilfiger", "calvinklein", "ralphlauren", "lacoste", "fredperry", "boss", "hugoboss", "gant", "jackjones", "selected",
    "carhartt", "northface", "thenorthface", "patagonia", "columbia", "champion", "fila", "kappa", "umbro", "newera", "ray-ban",
    "rayban", "casio", "seiko", "gstock", "timberland", "drmartens", "clarks", "geox", "sacoor", "salsa", "decathlon", "kiabi",
}


def norm(s: str) -> str:
    s = unicodedata.normalize("NFKD", s)
    return "".join(c for c in s if not unicodedata.combining(c)).lower().strip()


def _pretty(token: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token)  # NewEra -> New Era


def folder_category(folder: str) -> str | None:
    # "Hoodie/Camisolas" não pode ser nome de pasta no Mac: aceita Hoodie-Camisolas, Hoodie_Camisolas, "Hoodies e Camisolas"…
    return FOLDERS.get(re.sub(r"[^a-z0-9]", "", norm(folder)))


CAMERA_NAME = re.compile(r"^(img|dsc|dscn|dscf|pxl|image|photo|foto|screenshot|captura|whatsapp)[\s_\-.]*\d", re.I)


def parse(filename: str, category: str, fallback_label: str = "") -> dict:
    """Devolve name/size/brand/model/color/fit/material para um ficheiro de uma dada categoria."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    tokens = [t for t in re.split(r"[_\s]+", stem) if t]
    out = {"color": "", "size": "", "brand": "", "model": "", "fit": "", "material": "", "name": ""}
    if CAMERA_NAME.match(stem):  # nome automático da câmara: não tem informação
        return out
    type_label = ""
    waist = length = ""
    leftovers: list[str] = []
    last_was_color = False

    for tok in tokens:
        n = norm(tok)
        was_color = False
        if (m := re.fullmatch(r"w(\d{2})", n)):
            waist = m.group(1)
        elif (m := re.fullmatch(r"l(\d{2})", n)) and category in ("calças", "calções"):
            length = m.group(1)
        elif n in SIZES and not out["size"]:
            out["size"] = tok.upper()
        elif re.fullmatch(r"\d{2}(-\d{2})?", n) and _numeric_is_size(int(n[:2]), category, out["size"], waist):
            out["size"] = tok
        elif n in TYPES and not type_label:
            type_label = TYPES[n]
        elif n in COLORS:
            out["color"] = (out["color"] + " " + n).strip()
            was_color = True
        elif n in COLOR_MODIFIERS and last_was_color:
            out["color"] += " " + n
            was_color = True
        elif n in FITS and not out["fit"]:
            out["fit"] = tok.capitalize()
        elif n in MATERIALS and not out["material"]:
            out["material"] = tok.capitalize()
        elif n.replace("-", "") in KNOWN_BRANDS and not out["brand"]:
            out["brand"] = _pretty(tok)
        else:
            leftovers.append(tok)
        last_was_color = was_color

    if waist:
        out["size"] = f"W{waist}" + (f" L{length}" if length else "")
    # o que sobra: a primeira palavra é a marca (se ainda não há) e o resto é o modelo
    if leftovers and not out["brand"] and not leftovers[0].isdigit():
        out["brand"] = _pretty(leftovers.pop(0))
    out["model"] = " ".join(_pretty(t) for t in leftovers)

    name_parts = [type_label or fallback_label, out["material"], out["color"], out["brand"], out["model"]]
    out["name"] = " ".join(p for p in name_parts if p) or _pretty(stem.replace("_", " "))
    return out


def _numeric_is_size(n: int, category: str, current_size: str, waist: str) -> bool:
    """Um número de 2 dígitos só é tamanho em categorias onde isso faz sentido e se ainda não há tamanho."""
    if current_size or waist:
        return False
    if category == "sapatos":
        return 34 <= n <= 49
    if category in ("calças", "calções"):
        return 28 <= n <= 54
    if category in ("t-shirt", "camisa", "camisola", "casaco"):
        return 34 <= n <= 54
    if category == "meias":
        return 34 <= n <= 49
    return False
