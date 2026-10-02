"""Lê os metadados (título, imagem, loja, preço) de um link de produto."""
import ipaddress
import socket
from html.parser import HTMLParser
from urllib.parse import urljoin, urlparse

import httpx

UA = "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/605.1.15 (KHTML, like Gecko) Version/17.0 Safari/605.1.15"
MAX_HTML = 1_500_000
MAX_IMAGE = 6_000_000
MAX_REDIRECTS = 4


class LinkError(Exception):
    pass


def check_url(url: str) -> str:
    """Só http(s) e só hosts públicos: o servidor não pode ser usado para aceder à rede local."""
    p = urlparse(url)
    if p.scheme not in ("http", "https") or not p.hostname:
        raise LinkError("Link inválido. Tem de começar por http:// ou https://.")
    try:
        infos = socket.getaddrinfo(p.hostname, p.port or (443 if p.scheme == "https" else 80))
    except socket.gaierror as e:
        raise LinkError("Não consegui encontrar esse site.") from e
    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if not ip.is_global:
            raise LinkError("Esse endereço não é público.")
    return url


def store_from_host(host: str) -> str:
    parts = host.lower().removeprefix("www.").split(".")
    if len(parts) >= 3 and parts[-2] in ("co", "com", "org", "net"):
        name = parts[-3]
    elif len(parts) >= 2:
        name = parts[-2]
    else:
        name = parts[0]
    return name.capitalize()


class _Meta(HTMLParser):
    def __init__(self):
        super().__init__()
        self.meta: dict[str, str] = {}
        self.title = ""
        self._in_title = False

    def handle_starttag(self, tag, attrs):
        a = dict(attrs)
        if tag == "meta":
            key = (a.get("property") or a.get("name") or "").lower()
            if key and a.get("content") and key not in self.meta:
                self.meta[key] = a["content"].strip()
        elif tag == "title":
            self._in_title = True

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data


def parse_html(html: str, base_url: str) -> dict:
    p = _Meta()
    try:
        p.feed(html)
    except Exception:
        pass
    m = p.meta
    price = m.get("product:price:amount") or m.get("og:price:amount") or ""
    currency = m.get("product:price:currency") or m.get("og:price:currency") or ""
    image = m.get("og:image") or m.get("twitter:image") or ""
    return {
        "title": (m.get("og:title") or m.get("twitter:title") or p.title).strip()[:200],
        "store": m.get("og:site_name", "").strip()[:60],
        "price": f"{price} {currency}".strip(),
        "image_url": urljoin(base_url, image) if image else "",
    }


def _get(client: httpx.Client, url: str, limit: int) -> tuple[bytes, str]:
    """GET com redireções manuais, validando cada destino, e com limite de tamanho."""
    for _ in range(MAX_REDIRECTS + 1):
        check_url(url)
        with client.stream("GET", url) as r:
            if r.is_redirect and r.headers.get("location"):
                url = urljoin(url, r.headers["location"])
                continue
            r.raise_for_status()
            data = b""
            for chunk in r.iter_bytes():
                data += chunk
                if len(data) > limit:
                    break
            return data[:limit], url
    raise LinkError("Demasiados redirecionamentos.")


def fetch_meta(url: str) -> tuple[dict, bytes | None]:
    """Devolve (metadados, bytes da imagem). Falhas de rede/bloqueios devolvem metadados vazios."""
    check_url(url)
    meta = {"title": "", "store": "", "price": "", "image_url": ""}
    img = None
    try:
        with httpx.Client(headers={"User-Agent": UA, "Accept-Language": "pt-PT,pt;q=0.9,en;q=0.8"}, timeout=10.0) as c:
            raw, final = _get(c, url, MAX_HTML)
            meta = parse_html(raw.decode("utf-8", errors="ignore"), final)
            if meta["image_url"]:
                try:
                    img, _ = _get(c, meta["image_url"], MAX_IMAGE)
                except (httpx.HTTPError, LinkError):
                    img = None
    except (httpx.HTTPError, LinkError):
        pass
    if not meta["store"]:
        meta["store"] = store_from_host(urlparse(url).hostname or "")
    return meta, img
