#!/usr/bin/env python3
"""
Générateur de site statique BlindSp0t.
Lit  content/ (site.yml, projects/*.md, pages/*.md) + assets/
Écrit _site/  (prêt pour GitHub Pages).

Les liens et les ressources utilisent des chemins RELATIFS, calculés selon la
profondeur de chaque page : le site fonctionne donc partout — domaine racine
(blindsp0t.com), URL de projet GitHub Pages (…github.io/blindsp0t-site/) et
prévisualisation locale.

Usage : tools/.venv/bin/python tools/build.py
"""
import glob, hashlib, html, json, re, shutil
from pathlib import Path
import yaml

ASSET_VER = ""   # cache-buster (hash de style.css + app.js), défini au build

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
ASSETS = ROOT / "assets"
OUT = ROOT / "_site"


# --------------------------------------------------------------- utils

def load_md(path):
    raw = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    if not m:
        return {}, raw
    return (yaml.safe_load(m.group(1)) or {}), m.group(2)


def prefix_for(depth):
    """Préfixe relatif vers la racine du site selon la profondeur de la page."""
    return "../" * depth if depth else ""


def asset(p, prefix=""):
    """Normalise un chemin d'image vers une URL relative à la page courante.
    Accepte 'images/slug/x', 'assets/images/...', '/assets/...' ou une URL http."""
    p = (p or "").strip()
    if not p:
        return ""
    if p.startswith("http://") or p.startswith("https://"):
        return p
    if p.startswith("/assets/"):
        rel = p[1:]                      # 'assets/...'
    elif p.startswith("assets/"):
        rel = p
    elif p.startswith("/"):
        rel = p[1:]
    else:
        rel = "assets/" + p              # 'images/slug/x' -> 'assets/images/slug/x'
    return prefix + rel


def esc(s):
    return html.escape(s or "", quote=True)


# ------------------------------------------------------ SEO : URLs & données structurées

def abs_url(site, path):
    """URL absolue (domaine final) pour canonical / og:url / og:image / sitemap.
    Renvoie '' si le domaine n'est pas encore renseigné dans site.yml."""
    base = (site.get("domain") or "").rstrip("/")
    if not path.startswith("/"):
        path = "/" + path
    return (base + path) if base else ""


def og_image(site, cover):
    """URL absolue de l'image de partage : couverture du projet, sinon logo par défaut."""
    rel = asset(cover, "") if cover else "assets/brand/logo_white.png"
    return abs_url(site, "/" + rel)


def _ld(obj):
    """Sérialise un objet JSON-LD (échappe '<' pour rester sûr dans une balise <script>)."""
    obj = {k: v for k, v in obj.items() if v}
    return json.dumps(obj, ensure_ascii=False).replace("<", "\\u003c")


def person_ld(site):
    """JSON-LD Person (Antoine Vanel) — accueil + About."""
    sames = [v for _, v in _iter_socials(site) if str(v).startswith("http")]
    return _ld({
        "@context": "https://schema.org",
        "@type": "Person",
        "name": site.get("author", "Antoine Vanel"),
        "alternateName": site.get("title", "BlindSp0t"),
        "url": abs_url(site, "/"),
        "jobTitle": "Artiste numérique · Creative technologist",
        "address": {"@type": "PostalAddress", "addressLocality": "Lyon", "addressCountry": "FR"},
        "sameAs": sames,
    })


def project_ld(site, p, image, desc, path):
    """JSON-LD VisualArtwork pour une page projet."""
    return _ld({
        "@context": "https://schema.org",
        "@type": "VisualArtwork",
        "name": p.get("title"),
        "url": abs_url(site, path),
        "image": image,
        "description": desc,
        "keywords": ", ".join(p.get("tags") or []),
        "creator": {"@type": "Person", "name": site.get("author", "Antoine Vanel"),
                    "url": abs_url(site, "/")},
    })


def mini_markdown(text):
    """Markdown minimal : paragraphes, listes à puces, titres ##, séparateur ---EN---."""
    out, buf, in_ul = [], [], False

    def flush_p():
        if buf:
            out.append("<p>" + "<br>".join(esc(x) for x in buf) + "</p>")
            buf.clear()

    def close_ul():
        nonlocal in_ul
        if in_ul:
            out.append("</ul>"); in_ul = False

    for line in text.splitlines():
        s = line.strip()
        if s == "---EN---":
            flush_p(); close_ul(); out.append('<div class="lang-sep"></div>'); continue
        if not s:
            flush_p(); close_ul(); continue
        if s.startswith("## "):
            flush_p(); close_ul(); out.append("<h2>" + esc(s[3:]) + "</h2>"); continue
        if s.startswith("* "):
            flush_p()
            if not in_ul:
                out.append("<ul>"); in_ul = True
            out.append("<li>" + esc(s[2:]) + "</li>"); continue
        buf.append(s)
    flush_p(); close_ul()
    return "\n".join(out)


# ------------------------------------------------------------ templates

def nav(prefix, active=""):
    def cls(n):
        return ' class="active"' if n == active else ""
    home = prefix or "./"
    return (
        '<nav class="topnav">'
        f'<a class="nav-logo" href="{home}" aria-label="BlindSp0t — accueil">'
        f'<img src="{prefix}assets/brand/logo_white.png" alt="BlindSp0t"></a>'
        '<div class="nav-links">'
        f'<a href="{prefix}#projects"{cls("projects")}>Projects</a>'
        f'<a href="{prefix}about/"{cls("about")}>About</a>'
        f'<a href="{prefix}contact/"{cls("contact")}>Contact</a>'
        '</div>'
        '</nav>'
    )


def _iter_socials(site):
    s = site.get("socials") or []
    if isinstance(s, dict):
        return [(k, v) for k, v in s.items()]
    return [(x.get("label", ""), x.get("url", "")) for x in s]


def _social_href(v, prefix):
    return prefix + "contact/" if v == "contact-form" else v


def footer(site, prefix):
    socials = "".join(
        f'<a href="{esc(_social_href(v, prefix))}"{"" if v=="contact-form" else " target=_blank rel=noopener"}>{esc(k)}</a>'
        for k, v in _iter_socials(site)
    )
    return (
        '<footer class="footer">'
        f'<div>{esc(site.get("author",""))} — {esc(site.get("location",""))}</div>'
        f'<div class="socials">{socials}</div>'
        '</footer>'
    )


def page_shell(site, title, body, prefix="", active="", desc="", noindex=False,
               path="/", image="", jsonld="", og_type="website"):
    dtitle = f"{title} — {site['title']}" if title and title != site["title"] else site["title"]
    description = desc or site.get("description", "")
    robots = '<meta name="robots" content="noindex,nofollow">\n' if noindex else ""
    # Canonical / og:url : URL absolue du domaine final (pas sur les pages noindex).
    canonical = "" if noindex else abs_url(site, path)
    canon_tags = ""
    if canonical:
        canon_tags = (f'<link rel="canonical" href="{esc(canonical)}">\n'
                      f'<meta property="og:url" content="{esc(canonical)}">\n')
    img_tags = ""
    if image:
        img_tags = (f'<meta property="og:image" content="{esc(image)}">\n'
                    f'<meta property="og:image:alt" content="{esc(dtitle)}">\n'
                    f'<meta name="twitter:image" content="{esc(image)}">\n')
    jsonld_tag = f'<script type="application/ld+json">{jsonld}</script>\n' if jsonld else ""
    return f"""<!doctype html>
<html lang="fr">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
{robots}<title>{esc(dtitle)}</title>
<meta name="description" content="{esc(description)}">
<meta name="keywords" content="{esc(site.get('keywords',''))}">
{canon_tags}<meta property="og:title" content="{esc(dtitle)}">
<meta property="og:description" content="{esc(description)}">
<meta property="og:type" content="{og_type}">
<meta property="og:site_name" content="{esc(site['title'])}">
{img_tags}<meta name="twitter:card" content="summary_large_image">
<meta name="twitter:title" content="{esc(dtitle)}">
<meta name="twitter:description" content="{esc(description)}">
{jsonld_tag}<link rel="shortcut icon" href="{prefix}assets/brand/favicon.ico">
<link rel="preconnect" href="https://fonts.googleapis.com">
<link rel="preconnect" href="https://fonts.gstatic.com" crossorigin>
<link href="https://fonts.googleapis.com/css2?family=IBM+Plex+Mono:ital,wght@0,300;0,400;0,600;0,700;1,400&family=Space+Mono:ital,wght@0,400;0,700;1,400&family=Rubik:wght@400;700&display=swap" rel="stylesheet">
<link rel="stylesheet" href="{prefix}assets/css/style.css?v={ASSET_VER}">
</head>
<body>
{body}
{footer(site, prefix)}
<script src="{prefix}assets/js/app.js?v={ASSET_VER}" defer></script>
</body>
</html>
"""


# --------------------------------------------------------------- blocks

def render_text(b, prefix, alt=""):
    return f'<div class="block text">{b.get("html","")}</div>'


def render_image(b, prefix, alt=""):
    src = esc(asset(b["file"], prefix))
    return f'<div class="block image"><img loading="lazy" src="{src}" alt="{esc(alt)}"></div>'


def render_video(b, prefix, alt=""):
    src = esc(b.get("src", ""))
    title = f' title="{esc(alt)}"' if alt else ""
    return f'<div class="block video"><div class="frame"><iframe src="{src}"{title} allow="autoplay; fullscreen; picture-in-picture" allowfullscreen loading="lazy"></iframe></div></div>'


def render_gallery(b, prefix, alt=""):
    imgs = b.get("images", [])
    if not imgs:
        return ""
    # une seule image -> affichage simple
    if len(imgs) == 1:
        im = imgs[0]
        return f'<div class="block image"><img loading="lazy" src="{esc(asset(im["file"], prefix))}" alt="{esc(alt)}"></div>'
    # plusieurs images -> diaporama autoplay (rendu uniforme pour toutes les galeries)
    speed = b.get("speed") or 2.5
    # hauteur constante = ratio de la 1re image (évite les sauts de mise en page)
    try:
        w = float(imgs[0].get("w") or 0)
        h = float(imgs[0].get("h") or 0)
        ar = f"{w:g} / {h:g}" if w > 0 and h > 0 else "16 / 9"
    except (TypeError, ValueError):
        ar = "16 / 9"
    slides = "".join(
        f'<div class="slide{" active" if k==0 else ""}"><img loading="lazy" src="{esc(asset(im["file"], prefix))}" alt="{esc(f"{alt} — {k+1}" if alt else "")}"></div>'
        for k, im in enumerate(imgs)
    )
    dots = "".join(f'<span class="dot{" active" if k==0 else ""}"></span>' for k in range(len(imgs)))
    arrows = ('<button type="button" class="arrow left" aria-label="Précédent">‹</button>'
              '<button type="button" class="arrow right" aria-label="Suivant">›</button>') if b.get("arrows", True) else ""
    return (
        f'<div class="block gallery" data-slideshow data-autoplay="1" data-speed="{speed}">'
        f'<div class="slides" style="aspect-ratio:{ar}">{slides}{arrows}</div>'
        f'<div class="dots">{dots}</div>'
        '</div>'
    )


def render_columns(b, prefix, alt=""):
    # Nouveau format : deux champs nommés fr / en (côte à côte).
    # Ancien format (compat) : liste `columns: [FR, EN]`.
    if "fr" in b or "en" in b:
        cols = [b.get("fr", ""), b.get("en", "")]
    else:
        cols = b.get("columns", [])
    cols = [c for c in cols if (c or "").strip()]
    if not cols:
        return ""
    cells = "".join(f'<div class="col">{c}</div>' for c in cols)
    return f'<div class="block columns">{cells}</div>'


BLOCK_RENDER = {"text": render_text, "image": render_image, "video": render_video,
                "gallery": render_gallery, "columns": render_columns}


def merge_media_runs(blocks):
    """Regroupe les suites d'images/galeries adjacentes en un seul diaporama
    (évite qu'une image isolée pende sous une galerie). Une image réellement
    seule reste affichée en image simple (via render_gallery)."""
    out = []
    for b in blocks:
        if b["type"] in ("image", "gallery"):
            if b["type"] == "gallery":
                imgs = list(b.get("images", []))
                speed = b.get("speed") or 2.5
            else:
                imgs = [{"file": b.get("file"), "w": b.get("w", ""), "h": b.get("h", "")}]
                speed = 2.5
            if out and out[-1]["type"] == "gallery":
                out[-1]["images"].extend(imgs)
            else:
                out.append({"type": "gallery", "layout": "slideshow", "autoplay": True,
                            "speed": speed, "arrows": True, "images": imgs})
        else:
            out.append(dict(b))
    return out


# ---------------------------------------------------------------- build

def build():
    global ASSET_VER
    css = (ASSETS / "css" / "style.css").read_bytes()
    js = (ASSETS / "js" / "app.js").read_bytes()
    ASSET_VER = hashlib.md5(css + js).hexdigest()[:8]

    site = yaml.safe_load((CONTENT / "site.yml").read_text(encoding="utf-8"))

    projects = []
    for f in sorted(glob.glob(str(CONTENT / "projects" / "*.md"))):
        fm, _ = load_md(f)
        projects.append(fm)
    projects.sort(key=lambda p: p.get("order", 999))

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    shutil.copytree(ASSETS, OUT / "assets")
    admin_src = ROOT / "admin"
    if admin_src.exists():
        shutil.copytree(admin_src, OUT / "admin")

    domain = (site.get("domain") or "").replace("https://", "").replace("http://", "").strip("/")
    if domain:
        (OUT / "CNAME").write_text(domain + "\n")
    (OUT / ".nojekyll").write_text("")
    robots_txt = "User-agent: *\nAllow: /\n"
    sm_url = abs_url(site, "/sitemap.xml")
    if sm_url:
        robots_txt += f"Sitemap: {sm_url}\n"
    (OUT / "robots.txt").write_text(robots_txt)

    # --- grille de vignettes (accueil : prefix "" ; page projects : prefix "../") ---
    def grid(prefix):
        def thumb(p):
            tags = "".join(f"<span>{esc(t)}</span>" for t in (p.get("tags") or []))
            cover = esc(asset(p.get("cover"), prefix)) if p.get("cover") else ""
            img = (f'<img class="cover-img" loading="lazy" src="{cover}" alt="{esc(p.get("title",""))}">'
                   if cover else '<div class="cover-img"></div>')
            link = f'{prefix}project/{esc(p["slug"])}/'
            return (
                '<div class="thumb">'
                f'<a class="cover" href="{link}">{img}</a>'
                f'<div class="title"><a href="{link}">{esc(p["title"])}</a></div>'
                f'<div class="tags">{tags}</div>'
                '</div>'
            )
        return ('<div class="thumbs-wrap"><div class="thumbs" id="projects">'
                + "".join(thumb(p) for p in projects) + "</div></div>")

    # --- accueil (logo animé p5.js en hero, cf. assets/logo-anim/) ---
    home_body = (
        '<header class="hero">'
        '<iframe class="logo-anim" src="assets/logo-anim/index.html" title="BlindSp0t" '
        'scrolling="no" loading="eager"></iframe>'
        '<img class="logo-fallback" src="assets/brand/logo_white.png" alt="BlindSp0t">'
        '</header>'
        '<a class="scroll-hint" href="#projects" aria-label="Découvrir les projets">'
        '<svg viewBox="0 0 24 24" fill="none" xmlns="http://www.w3.org/2000/svg">'
        '<path d="M12 4 V20 M5 13 L12 20 L19 13" stroke="currentColor" stroke-width="1.6" '
        'stroke-linecap="round" stroke-linejoin="round"/></svg></a>'
        f'{nav("", "projects")}'
        f'{grid("")}'
    )
    (OUT / "index.html").write_text(
        page_shell(site, site["title"], home_body, prefix="", active="projects",
                   path="/", image=og_image(site, None), jsonld=person_ld(site)), encoding="utf-8")

    # --- /projects/ ---
    (OUT / "projects").mkdir()
    (OUT / "projects" / "index.html").write_text(
        page_shell(site, "Projects", nav("../", "projects") + grid("../"), prefix="../", active="projects",
                   path="/projects/", image=og_image(site, None)), encoding="utf-8")

    # --- pages projet (profondeur 2) ---
    for p in projects:
        pfx = "../../"
        alt = p.get("title", "")
        blocks = merge_media_runs(p.get("blocks", []))
        body_blocks = "".join(
            BLOCK_RENDER.get(b["type"], lambda b, pr, a="": "")(b, pfx, alt) for b in blocks)
        # Description : champ `description` du front-matter en priorité (éditable au CMS),
        # sinon 1er bloc texte, sinon repli titre + tags (projets média-only).
        desc = (p.get("description") or "").strip()
        if not desc:
            desc = re.sub(r"<[^>]+>", " ", next((b["html"] for b in p.get("blocks", []) if b["type"] == "text"), ""))
            desc = re.sub(r"\s+", " ", desc).strip()[:180]
        if not desc:
            tags = ", ".join(p.get("tags") or [])
            desc = f'{p.get("title","")} — {site.get("author","")}' + (f" · {tags}" if tags else "")
        path = f'/project/{p["slug"]}/'
        image = og_image(site, p.get("cover"))
        body = (
            f'{nav(pfx, "")}'
            '<main class="page">'
            f'<h1 class="project-title">{esc(p["title"])}</h1>'
            f'{body_blocks}'
            '<hr>'
            f'<p><a href="{pfx}#projects" style="border-bottom:1px solid rgba(255,255,255,.4)">← Projects</a></p>'
            '</main>'
        )
        d = OUT / "project" / p["slug"]
        d.mkdir(parents=True)
        (d / "index.html").write_text(
            page_shell(site, p["title"], body, prefix=pfx, desc=desc, path=path, image=image,
                       jsonld=project_ld(site, p, image, desc, path), og_type="article"),
            encoding="utf-8")

    # --- About (profondeur 1) : titre + filet + 2 colonnes FR/EN ---
    fm, md = load_md(CONTENT / "pages" / "about.md")
    parts = md.split("---EN---")
    fr = mini_markdown(parts[0])
    en = mini_markdown(parts[1]) if len(parts) > 1 else ""
    if en:
        prose = f'<div class="about-cols"><div class="col">{fr}</div><div class="col">{en}</div></div>'
    else:
        prose = f'<div class="prose">{fr}</div>'
    body = (f'{nav("../","about")}<main class="page"><hr>'
            f'<h1 class="project-title">{esc(fm.get("title","About"))}</h1>{prose}</main>')
    # Description dédiée : à partir de la présentation d'Antoine (pas de la citation d'intro).
    about_txt = re.sub(r"\s+", " ", re.sub(r"<[^>]+>", " ", fr)).strip()
    i = about_txt.find("Antoine Vanel")
    about_desc = (about_txt[i:] if i != -1 else about_txt)[:180]
    (OUT / "about").mkdir()
    (OUT / "about" / "index.html").write_text(
        page_shell(site, "About", body, prefix="../", active="about",
                   path="/about/", desc=about_desc, image=og_image(site, None),
                   jsonld=person_ld(site)), encoding="utf-8")

    # --- Confidentialité (profondeur 1) ---
    fm, md = load_md(CONTENT / "pages" / "privacy.md")
    body = f'{nav("../","")}<main class="page"><div class="prose">{mini_markdown(md)}</div></main>'
    d = OUT / "engagement-confidentialite"; d.mkdir()
    (d / "index.html").write_text(page_shell(site, fm.get("title", "Confidentialité"), body, prefix="../", noindex=True), encoding="utf-8")

    # --- Contact (profondeur 1) ---
    (OUT / "contact").mkdir()
    (OUT / "contact" / "index.html").write_text(
        page_shell(site, "Contact", nav("../", "contact") + contact_body(site, "../"),
                   prefix="../", active="contact", path="/contact/", image=og_image(site, None)), encoding="utf-8")

    # --- sitemap ---
    urls = ["/", "/about/", "/contact/", "/projects/"] + [f"/project/{p['slug']}/" for p in projects]
    base = site.get("domain", "").rstrip("/")
    sm = '<?xml version="1.0" encoding="UTF-8"?>\n<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">\n'
    sm += "".join(f"<url><loc>{base}{u}</loc></url>\n" for u in urls) + "</urlset>\n"
    (OUT / "sitemap.xml").write_text(sm, encoding="utf-8")

    print(f"✓ Build OK : {len(projects)} projets → {OUT}")


def contact_body(site, prefix):
    fid = (site.get("formspree_id") or "").strip()
    email = site.get("contact_email", "")
    if fid:
        form = (
            f'<form class="contact-form" action="https://formspree.io/f/{esc(fid)}" method="POST">'
            '<div><label>Nom</label><input type="text" name="name" required></div>'
            '<div><label>Email</label><input type="email" name="email" required></div>'
            '<div><label>Message</label><textarea name="message" required></textarea></div>'
            '<button type="submit">Envoyer</button>'
            '</form>'
        )
    else:
        form = (
            '<p style="color:rgba(255,255,255,.6);max-width:46rem">'
            'Le formulaire sera activé dès que l’identifiant Formspree sera renseigné dans '
            '<code>content/site.yml</code>. En attendant :</p>'
            f'<p><a href="mailto:{esc(email)}" style="border-bottom:1px solid rgba(255,255,255,.4)">{esc(email)}</a></p>'
        )
    return f'<main class="page"><h1 class="project-title">Contact</h1>{form}</main>'


if __name__ == "__main__":
    build()
