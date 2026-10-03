"""Parse file names such as `Trousers_Denim_Levis_511_W33_L34.jpg` (Portuguese names such as `Calças_Ganga_...` work too).

Parts are separated by `_` and have no fixed order, so each part is classified by what it is:
size (M, 44, W33, L34), colour, fit, material, garment type, or brand/model (whatever is left).
The result is only a proposal: every field stays editable in the app.
"""
import re

from .vocab import COLOR_MODIFIERS, COLOR_WORDS, MATERIALS, norm

SIZES = {"xxs", "xs", "s", "m", "l", "xl", "xxl", "xxxl", "3xl", "4xl"}
FITS = {"wide", "slim", "regular", "oversize", "oversized", "baggy", "skinny", "straight", "relaxed", "loose", "tapered", "boxy", "cropped", "fit", "comfort"}
# garment-type word (normalised, English or Portuguese) -> label used in the generated name
TYPES = {
    "tshirt": "T-shirt", "tee": "T-shirt", "camisa": "Shirt", "shirt": "Shirt", "polo": "Polo",
    "camisola": "Sweater", "sweater": "Sweater", "jumper": "Sweater", "sweat": "Sweatshirt", "sweatshirt": "Sweatshirt", "hoodie": "Hoodie",
    "casaco": "Coat", "coat": "Coat", "jacket": "Jacket", "blazer": "Blazer", "parka": "Parka", "blusao": "Jacket",
    "calcas": "Trousers", "trousers": "Trousers", "pants": "Pants", "jeans": "Jeans",
    "calcoes": "Shorts", "shorts": "Shorts", "bermudas": "Bermuda shorts",
    "meias": "Socks", "socks": "Socks", "sapatos": "Shoes", "shoes": "Shoes",
    "tenis": "Sneakers", "sneakers": "Sneakers", "trainers": "Sneakers", "botas": "Boots", "boots": "Boots",
    "sandalias": "Sandals", "sandals": "Sandals",
    "chapeu": "Hat", "hat": "Hat", "bone": "Cap", "cap": "Cap", "gorro": "Beanie", "beanie": "Beanie",
    "cinto": "Belt", "belt": "Belt", "relogio": "Watch", "watch": "Watch", "oculos": "Glasses", "glasses": "Glasses", "sunglasses": "Sunglasses",
    "cachecol": "Scarf", "scarf": "Scarf", "luvas": "Gloves", "gloves": "Gloves", "gravata": "Tie", "tie": "Tie",
    "mala": "Bag", "bag": "Bag", "carteira": "Wallet", "wallet": "Wallet",
}
# folder name (normalised, punctuation removed) -> category id used by the app
_FOLDER_NAMES = {
    "tshirt": "tshirt", "tshirts": "tshirt",
    "shirt": "shirt", "shirts": "shirt", "camisa": "shirt", "camisas": "shirt",
    "sweater": "sweater", "sweaters": "sweater", "hoodie": "sweater", "hoodies": "sweater", "sweat": "sweater", "sweats": "sweater",
    "sweatshirt": "sweater", "sweatshirts": "sweater", "jumper": "sweater", "jumpers": "sweater",
    "camisola": "sweater", "camisolas": "sweater",
    # "Hoodie/Sweater" cannot be a folder name on macOS: Hoodie-Sweaters, Hoodie_Sweaters, "Hoodies and Sweaters"... all work
    "hoodiesweater": "sweater", "hoodiesweaters": "sweater", "hoodiesandsweaters": "sweater", "hoodiesweatshirts": "sweater",
    "sweatershoodies": "sweater", "sweatersandhoodies": "sweater",
    "hoodiecamisola": "sweater", "hoodiecamisolas": "sweater", "hoodiescamisolas": "sweater", "hoodieecamisolas": "sweater",
    "hoodiesecamisolas": "sweater", "camisolashoodies": "sweater", "camisolasehoodies": "sweater", "camisolahoodie": "sweater",
    "shorts": "shorts", "calcoes": "shorts", "calcao": "shorts",
    "trousers": "trousers", "pants": "trousers", "jeans": "trousers", "calcas": "trousers", "calca": "trousers",
    "socks": "socks", "meias": "socks", "meia": "socks",
    "coat": "coat", "coats": "coat", "jacket": "coat", "jackets": "coat", "casaco": "coat", "casacos": "coat",
    "shoes": "shoes", "footwear": "shoes", "sapatos": "shoes", "sapato": "shoes",
    "accessories": "accessories", "accessory": "accessories", "acessorios": "accessories", "acessorio": "accessories",
}
KNOWN_BRANDS = {
    "nike", "adidas", "puma", "reebok", "newbalance", "asics", "converse", "vans", "levis", "wrangler", "lee", "diesel", "zara",
    "lefties", "bershka", "pullbear", "stradivarius", "massimodutti", "mango", "hm", "uniqlo", "primark", "cortefiel", "springfield",
    "tommyhilfiger", "calvinklein", "ralphlauren", "lacoste", "fredperry", "boss", "hugoboss", "gant", "jackjones", "selected",
    "carhartt", "northface", "thenorthface", "patagonia", "columbia", "champion", "fila", "kappa", "umbro", "newera", "ray-ban",
    "rayban", "casio", "seiko", "gstock", "timberland", "drmartens", "clarks", "geox", "sacoor", "salsa", "decathlon", "kiabi",
}
CAMERA_NAME = re.compile(r"^(img|dsc|dscn|dscf|pxl|image|photo|foto|screenshot|captura|whatsapp)[\s_\-.]*\d", re.I)


def _pretty(token: str) -> str:
    return re.sub(r"(?<=[a-z])(?=[A-Z])", " ", token)  # NewEra -> New Era


def folder_category(folder: str) -> str | None:
    return _FOLDER_NAMES.get(re.sub(r"[^a-z0-9]", "", norm(folder)))


def parse(filename: str, category: str, fallback_label: str = "") -> dict:
    """Return name/size/brand/model/color/fit/material proposed for a file of the given category."""
    stem = re.sub(r"\.[A-Za-z0-9]+$", "", filename)
    tokens = [t for t in re.split(r"[_\s]+", stem) if t]
    out = {"color": "", "size": "", "brand": "", "model": "", "fit": "", "material": "", "name": ""}
    if CAMERA_NAME.match(stem):  # automatic camera name: carries no information
        return out
    type_label = ""
    waist = length = ""
    colors: list[str] = []
    leftovers: list[str] = []

    for tok in tokens:
        n = norm(tok)
        if (m := re.fullmatch(r"w(\d{2})", n)):
            waist = m.group(1)
        elif (m := re.fullmatch(r"l(\d{2})", n)) and category in ("trousers", "shorts"):
            length = m.group(1)
        elif n in SIZES and not out["size"]:
            out["size"] = tok.upper()
        elif re.fullmatch(r"\d{2}(-\d{2})?", n) and _numeric_is_size(int(n[:2]), category, out["size"], waist):
            out["size"] = tok
        elif n in TYPES and not type_label:
            type_label = TYPES[n]
        elif n in COLOR_WORDS:
            colors.append(COLOR_WORDS[n])
        elif n in COLOR_MODIFIERS and colors:  # "Blue_Light" -> "light blue": the modifier goes before the colour
            colors[-1] = f"{COLOR_MODIFIERS[n]} {colors[-1]}"
        elif n in FITS and not out["fit"]:
            out["fit"] = tok.capitalize()
        elif n in MATERIALS and not out["material"]:
            out["material"] = MATERIALS[n]
        elif n.replace("-", "") in KNOWN_BRANDS and not out["brand"]:
            out["brand"] = _pretty(tok)
        else:
            leftovers.append(tok)

    out["color"] = " ".join(colors)
    if waist:
        out["size"] = f"W{waist}" + (f" L{length}" if length else "")
    # what is left: the first word is the brand (if there is none yet) and the rest is the model
    if leftovers and not out["brand"] and not leftovers[0].isdigit():
        out["brand"] = _pretty(leftovers.pop(0))
    out["model"] = " ".join(_pretty(t) for t in leftovers)

    name_parts = [out["material"], out["color"], out["brand"], out["model"], type_label or fallback_label]
    name = " ".join(p for p in name_parts if p) or _pretty(stem.replace("_", " "))
    out["name"] = name[0].upper() + name[1:]
    return out


def _numeric_is_size(n: int, category: str, current_size: str, waist: str) -> bool:
    """A two-digit number is only a size in categories where that makes sense and if there is no size yet."""
    if current_size or waist:
        return False
    if category == "shoes":
        return 34 <= n <= 49
    if category in ("trousers", "shorts"):
        return 28 <= n <= 54
    if category in ("tshirt", "shirt", "sweater", "coat"):
        return 34 <= n <= 54
    if category == "socks":
        return 34 <= n <= 49
    return False
