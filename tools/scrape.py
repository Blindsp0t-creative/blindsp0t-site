#!/usr/bin/env python3
"""
Import (one-shot) du contenu depuis l'ancien site Cargo (blindsp0t.com) vers
des fichiers de contenu locaux + rapatriement des images en pleine résolution.

Sortie :
  content/projects/NN-<slug>.md   (front-matter YAML : titre, tags, ordre, blocs)
  content/pages/about.md, privacy.md
  assets/images/<slug>/*.jpg|png  (images originales)

Usage :
  tools/.venv/bin/python tools/scrape.py            # tout
  tools/.venv/bin/python tools/scrape.py La-Fin-Du-Present   # un seul projet
"""
import json, os, re, sys, time, urllib.parse, hashlib
from pathlib import Path
import requests
from bs4 import BeautifulSoup, NavigableString, Tag
import yaml

ROOT = Path(__file__).resolve().parent.parent
BASE = "https://blindsp0t.com"
UA = {"User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120 Safari/537.36"}
IMG_DIR = ROOT / "assets" / "images"
PROJ_DIR = ROOT / "content" / "projects"
PAGE_DIR = ROOT / "content" / "pages"

session = requests.Session()
session.headers.update(UA)


def fetch(url):
    for attempt in range(3):
        try:
            r = session.get(url, timeout=45)
            if r.status_code == 200:
                return r
        except requests.RequestException as e:
            print(f"    ! {e}")
        time.sleep(2)
    raise RuntimeError(f"fetch failed: {url}")


def slug_dir(slug):
    d = IMG_DIR / slug
    d.mkdir(parents=True, exist_ok=True)
    return d


def img_filename(url):
    """Nom de fichier lisible et unique à partir de l'URL freight."""
    name = urllib.parse.unquote(url.split("/")[-1].split("?")[0])
    name = re.sub(r"[^A-Za-z0-9._-]", "_", name)
    # préfixe court du hash cargo pour éviter les collisions de noms identiques
    m = re.search(r"/i/([0-9a-f]{8})", url)
    prefix = (m.group(1) + "_") if m else ""
    return prefix + name


def download_image(url, slug, cache):
    if url in cache:
        return cache[url]
    fn = img_filename(url)
    dest = slug_dir(slug) / fn
    rel = f"images/{slug}/{fn}"
    if not dest.exists() or dest.stat().st_size == 0:
        try:
            r = fetch(url)
            dest.write_bytes(r.content)
            print(f"    ↓ {fn} ({len(r.content)//1024} Ko)")
        except Exception as e:
            print(f"    ! image KO {url}: {e}")
            return None
    cache[url] = rel
    return rel


def img_src(im):
    return im.get("data-src") or im.get("src") or ""


def is_logo(url):
    return "logo" in url.lower() or "bsp0t_logo" in url.lower()


def find_content_bodycopy(soup):
    """La zone de contenu = le <bodycopy> avec le plus d'images de contenu (hors logo)."""
    best, bn = None, -1
    for bc in soup.find_all("bodycopy"):
        imgs = [i for i in bc.find_all("img")
                if "freight" in img_src(i) and not is_logo(img_src(i))]
        if len(imgs) > bn:
            bn, best = len(imgs), bc
    return best


TAG_INLINE_KEEP = {"br", "strong", "b", "em", "i", "u", "a", "span", "small", "sub", "sup"}


def clean_text_html(node):
    """Rend le HTML texte nettoyé (on garde br/gras/italique/liens, on jette le reste)."""
    def render(n):
        if isinstance(n, NavigableString):
            return str(n)
        if not isinstance(n, Tag):
            return ""
        if n.name == "br":
            return "<br>"
        inner = "".join(render(c) for c in n.children)
        if n.name == "a":
            href = n.get("href", "")
            return f'<a href="{href}">{inner}</a>' if inner.strip() else ""
        if n.name in ("strong", "b"):
            return f"<strong>{inner}</strong>"
        if n.name in ("em", "i"):
            return f"<em>{inner}</em>"
        # small / span / div / p / h... -> on garde juste le contenu
        return inner
    html = "".join(render(c) for c in node.children) if isinstance(node, Tag) else render(node)
    html = re.sub(r"(?:\s*<br>\s*){3,}", "<br><br>", html)   # max 2 sauts consécutifs
    html = re.sub(r"[ \t]+", " ", html)
    return html.strip()


def parse_gallery(div, slug, cache):
    raw = div.get("data-gallery", "")
    settings = {}
    try:
        settings = json.loads(urllib.parse.unquote(raw)) if raw else {}
    except Exception:
        settings = {}
    data = settings.get("data", {})
    layout = settings.get("path", "gallery")  # slideshow / grid / justify / ...
    images = []
    for im in div.find_all("img"):
        u = img_src(im)
        if not u or is_logo(u):
            continue
        rel = download_image(u, slug, cache)
        if rel:
            images.append({"file": rel,
                           "w": im.get("width_o") or im.get("width") or "",
                           "h": im.get("height_o") or im.get("height") or ""})
    return {
        "type": "gallery",
        "layout": layout,
        "autoplay": bool(data.get("autoplay", False)),
        "speed": data.get("autoplaySpeed", 0),
        "arrows": bool(data.get("arrows", True)),
        "captions": bool(data.get("captions", False)),
        "transition": data.get("transition-type", "slide"),
        "images": images,
    }


def norm_media_src(src):
    src = (src or "").strip()
    if src.startswith("//"):
        src = "https:" + src
    return src


def node_has_media(node):
    """True si le sous-arbre contient une galerie, un iframe ou une image de contenu."""
    if not isinstance(node, Tag):
        return False
    if node.get("data-gallery") or node.name == "iframe":
        return True
    if node.name == "img" and "freight" in img_src(node) and not is_logo(img_src(node)):
        return True
    return bool(node.find(lambda t: isinstance(t, Tag) and (
        t.get("data-gallery") is not None
        or t.name == "iframe"
        or (t.name == "img" and "freight" in img_src(t) and not is_logo(img_src(t)))
    )))


def parse_project(slug, title, tags, order):
    print(f"[{order:02d}] {slug}")
    r = fetch(f"{BASE}/{slug}")
    soup = BeautifulSoup(r.text, "html.parser")
    # couverture curatée = og:image de la page
    og = soup.find("meta", property="og:image")
    og_url = og.get("content") if og else None

    bc = find_content_bodycopy(soup)
    if not bc:
        print("    ! pas de contenu trouvé")
        return None
    pc = bc.find("projectcontent") or bc.find("div", class_="page_content") or bc
    cache = {}
    blocks = []
    text_buf = []

    def flush_text():
        if text_buf:
            html = "".join(text_buf).strip()
            html = re.sub(r"^(?:<br>\s*)+", "", html)
            html = re.sub(r"(?:<br>\s*)+$", "", html).strip()
            html = re.sub(r"^\.+$", "", html).strip()   # jette les "." isolés
            if html and re.sub(r"<[^>]+>", "", html).strip():
                blocks.append({"type": "text", "html": html})
            text_buf.clear()

    seen_gallery_imgs = set()

    def walk(node, header_state):
        """Parcours récursif en-ordre : galeries, vidéos, images, texte."""
        for child in node.children:
            if isinstance(child, NavigableString):
                t = str(child).strip()
                if t:
                    text_buf.append(t + " ")
                continue
            if not isinstance(child, Tag):
                continue

            # --- header nav (1er grid-row contenant le logo) : on saute ---
            if not header_state["done"] and child.get("grid-row") is not None and \
               any(is_logo(img_src(i)) for i in child.find_all("img")):
                header_state["done"] = True
                continue
            # titres structurels (rendus par le gabarit)
            if child.name in ("h1", "h2"):
                continue

            # --- galerie ---
            if child.get("data-gallery") is not None:
                flush_text()
                g = parse_gallery(child, slug, cache)
                for im in g["images"]:
                    seen_gallery_imgs.add(im["file"])
                if g["images"]:
                    blocks.append(g)
                continue

            # --- iframe (vidéo) ---
            if child.name == "iframe":
                flush_text()
                src = norm_media_src(child.get("src") or child.get("data-src"))
                if src:
                    blocks.append({"type": "video", "src": src,
                                   "w": child.get("width", "960"), "h": child.get("height", "540")})
                continue

            # --- image isolée ---
            if child.name == "img":
                if "freight" in img_src(child) and not is_logo(img_src(child)):
                    flush_text()
                    rel = download_image(img_src(child), slug, cache)
                    if rel and rel not in seen_gallery_imgs:
                        blocks.append({"type": "image", "file": rel,
                                       "w": child.get("width_o") or child.get("width") or "",
                                       "h": child.get("height_o") or child.get("height") or ""})
                continue

            # --- conteneur : recurse s'il contient du media, sinon texte ---
            if node_has_media(child):
                walk(child, header_state)
            else:
                html = clean_text_html(child)
                if html:
                    text_buf.append(html + "<br>")

    walk(pc, {"done": False})
    flush_text()

    # couverture : image issue du contenu sinon og:image curatée
    cover = None
    for b in blocks:
        if b["type"] == "gallery" and b["images"]:
            cover = b["images"][0]["file"]; break
        if b["type"] == "image":
            cover = b["file"]; break
    if not cover and og_url:
        cover = download_image(og_url, slug, cache)

    fm = {
        "title": title,
        "slug": slug,
        "order": order,
        "tags": tags,
        "cover": cover,
        "blocks": blocks,
    }
    out = PROJ_DIR / f"{order:02d}-{slug}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.safe_dump(fm, f, allow_unicode=True, sort_keys=False, width=10000)
        f.write("---\n")
    nb_img = sum(len(b.get("images", [])) if b["type"] == "gallery" else (1 if b["type"] == "image" else 0) for b in blocks)
    nb_vid = sum(1 for b in blocks if b["type"] == "video")
    nb_txt = sum(1 for b in blocks if b["type"] == "text")
    print(f"    ✓ {len(blocks)} blocs (img={nb_img} vidéo={nb_vid} texte={nb_txt}) -> {out.name}")
    return fm


def main():
    manifest = json.loads((ROOT / "content" / "site-manifest.json").read_text())
    projects = manifest["projects"]
    only = sys.argv[1] if len(sys.argv) > 1 else None
    for i, p in enumerate(projects, 1):
        if only and p["slug"] != only:
            continue
        try:
            parse_project(p["slug"], p["title"], p.get("tags", []), i)
        except Exception as e:
            print(f"    !! ERREUR {p['slug']}: {e}")
        time.sleep(0.5)


if __name__ == "__main__":
    main()
