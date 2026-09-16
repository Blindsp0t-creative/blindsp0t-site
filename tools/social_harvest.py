#!/usr/bin/env python3
"""social_harvest.py — moissonneur de contenu pour Instagram (phase 1 : images).

Génère des BROUILLONS de posts à partir des projets du site (content/projects/*.md +
images de assets/images/<slug>/), et peut aller chercher des images SUPPLÉMENTAIRES
dans les dossiers de travail locaux (mapping validé dans sources.yml).

Chaque brouillon = un dossier dans content/social/instagram/drafts/<date>-<slug>/ :
  - post.yml       : type/caption (titre + description + hashtags) — à relire
  - 01.jpg…        : images du SITE reformatées pour Instagram (le carrousel proposé)
  - candidates/    : images en plus, tirées du dossier de travail local (À TRIER —
                     NON publiées : ig_publish.py ne lit que la racine du dossier)

⚠️ L'outil PROPOSE, tu VALIDES. Rien n'est publié ici. Pour publier un brouillon :
   1) relis/ajuste la légende, 2) remonte les images voulues de candidates/ à la racine
   (renommées 0N.jpg) et supprime le reste, 3) DÉPLACE le dossier dans ../queue/
   (c'est queue/ que lit tools/ig_publish.py).

Usage :
  python tools/social_harvest.py list                    projets + nb images + état
  python tools/social_harvest.py map [--force]           (re)génère sources.yml (À VALIDER)
  python tools/social_harvest.py draft <slug|--next|--all> [--scan] [--max-images N] [--force]
  python tools/social_harvest.py scan <slug|--all> [--force]   remplit candidates/ (dossier local)

Deps : stdlib + Pillow + PyYAML (déjà dans tools/requirements.txt). Outil LOCAL only
(non exécuté en CI) : lit motsCles.txt et /Users/.../BLINDSP0T/projets hors du dépôt.
"""
import argparse
import datetime as dt
import glob
import os
import re
import statistics
import sys
import unicodedata

import yaml
from PIL import Image


class _Literal(str):
    """Chaîne rendue en bloc littéral YAML (caption: |) pour la lisibilité."""


def _literal_representer(dumper, data):
    return dumper.represent_scalar("tag:yaml.org,2002:str", data, style="|")


yaml.add_representer(_Literal, _literal_representer, Dumper=yaml.SafeDumper)

# --------------------------------------------------------------- chemins
HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)                      # blindsp0t-site/
PROJECTS_DIR = os.path.join(ROOT, "content", "projects")
IMAGES_DIR = os.path.join(ROOT, "assets", "images")
SOCIAL = os.path.join(ROOT, "content", "social", "instagram")
DRAFTS = os.path.join(SOCIAL, "drafts")
QUEUE = os.path.join(SOCIAL, "queue")
PUBLISHED = os.path.join(SOCIAL, "published")
SOURCES_YML = os.path.join(SOCIAL, "sources.yml")   # mapping slug -> dossier local (validé)

# ressources locales HORS dépôt (l'outil ne tourne qu'en local)
MOTSCLES = os.environ.get(
    "SOCIAL_MOTSCLES",
    os.path.normpath(os.path.join(ROOT, "..", "referencement", "motsCles.txt")))
WORK_ROOT = os.environ.get("SOCIAL_WORK_ROOT", "/Users/blindsp0t/BLINDSP0T/projets")

# --------------------------------------------------------------- specs Instagram
MAX_WIDTH = 1440              # largeur max conseillée pour un feed IG
AR_MIN, AR_MAX = 0.80, 1.91  # ratios acceptés (4:5 portrait -> 1.91:1 paysage)
MAX_IMAGE_MB = 8
MAX_CAROUSEL = 10
JPEG_Q_START = 88
BG = (0, 0, 0)               # fond noir (letterbox) = cohérent avec le site

SRC_EXT = {".jpg", ".jpeg", ".png", ".gif", ".avif", ".webp", ".tif", ".tiff", ".heic"}

# hashtags de base ajoutés à chaque post (complétés par la banque de motsCles.txt)
BASE_HASHTAGS = [
    "blindsp0t", "artnumerique", "newmediaart",
    "creativecoding", "installationart", "lyon",
]
MAX_HASHTAGS = 20

# --------------------------------------------------------------- scan local (prudent)
SCAN_MIN_LONG = 1200         # côté le plus long minimal (px) : écarte vignettes/icônes
SCAN_MIN_KB = 80             # écarte les tout petits fichiers
SCAN_MAX_CANDIDATES = 40     # plafond de candidats par projet
# dossiers techniques à ne PAS descendre (composant de chemin en minuscules)
EXCL_EXACT = {"obj", "bin", "library", "temp", "tmp", "cache", "caches",
              "logs", "log", ".git", "node_modules", "__pycache__", ".venv",
              "admin", "devis", "markers", "builds", "build"}
EXCL_SUB = ("unity", "backup", "deriveddata", "il2cpp", "cache",
            "example", "release", "addons", "sdk", "of_v", "node_modules",
            "site-packages", "download", "texture", "lidar", "scan")
# fichiers écartés par leur nom (captures d'écran, screenshots — pas des photos)
SKIP_NAME_SUB = ("screenshot", "screen shot", "capture d")


# --------------------------------------------------------------- utils projets
def load_project(path):
    """Lit le front-matter YAML d'un fichier projet (corps vide chez ce site)."""
    with open(path, encoding="utf-8") as f:
        raw = f.read()
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    data = yaml.safe_load(m.group(1) if m else raw) or {}
    return data


def project_files():
    return sorted(glob.glob(os.path.join(PROJECTS_DIR, "*.md")))


def all_projects():
    """[(slug, proj_dict)] triés par ordre de fichier."""
    out = []
    for path in project_files():
        proj = load_project(path)
        slug = proj.get("slug") or os.path.basename(path)[3:-3]
        out.append((slug, proj))
    return out


def find_project(slug):
    for s, proj in all_projects():
        if s == slug:
            return proj
    return None


# --------------------------------------------------------------- hashtags
def slugify_tag(tag):
    """'Real-time volumetric capture' -> 'realtimevolumetriccapture' (hashtag)."""
    s = unicodedata.normalize("NFKD", tag).encode("ascii", "ignore").decode()
    return re.sub(r"[^a-z0-9]", "", s.lower())


def motscles_hashtags(exclude_generic=True):
    """Extrait la banque de hashtags de motsCles.txt (section 5).
    Ignore le bloc marqué « trop génériques / à n'utiliser… » si exclude_generic."""
    if not os.path.isfile(MOTSCLES):
        return []
    out, avoid = [], False
    for line in open(MOTSCLES, encoding="utf-8"):
        low = line.lower()
        if "trop génériques" in low or "trop generiques" in low or "n'utiliser" in low:
            avoid = True
        toks = re.findall(r"#([a-z0-9]{3,})", line, re.I)
        if len(toks) < 2:              # vraies lignes de hashtags = plusieurs tokens
            continue
        if avoid and exclude_generic:
            continue
        for t in toks:
            t = t.lower()
            if t not in out:
                out.append(t)
    return out


def build_hashtags(tags):
    """tags projet (spécifiques) + base marque + banque motsCles, dédupliqués, plafonnés."""
    out = []
    for t in (tags or []):
        h = slugify_tag(t)
        if h and h not in out:
            out.append(h)
    for h in BASE_HASHTAGS + motscles_hashtags(exclude_generic=True):
        if h not in out:
            out.append(h)
    return ["#" + h for h in out[:MAX_HASHTAGS]]


def build_caption(proj):
    title = (proj.get("title") or "").strip()
    desc = (proj.get("description") or "").strip()
    tags = build_hashtags(proj.get("tags"))
    parts = [p for p in (title, desc) if p]
    body = "\n\n".join(parts)
    return f"{body}\n\n{' '.join(tags)}\n" if body else f"{' '.join(tags)}\n"


# --------------------------------------------------------------- images
def cover_first(proj, files):
    """Met l'image 'cover' en tête si elle est dans la liste."""
    cover = proj.get("cover")
    if not cover:
        return files
    base = os.path.basename(cover)
    ordered = [f for f in files if os.path.basename(f) == base]
    ordered += [f for f in files if os.path.basename(f) != base]
    return ordered


def source_images(slug):
    d = os.path.join(IMAGES_DIR, slug)
    if not os.path.isdir(d):
        return []
    return [os.path.join(d, n) for n in sorted(os.listdir(d))
            if os.path.splitext(n)[1].lower() in SRC_EXT]


def _open_rgb(src):
    """Ouvre une image (1re frame), aplatit l'alpha sur fond noir, renvoie du RGB."""
    im = Image.open(src)
    try:
        im.seek(0)   # 1re frame pour gif/animé
    except Exception:
        pass
    if im.mode in ("RGBA", "LA", "P"):
        im = im.convert("RGBA")
        bg = Image.new("RGBA", im.size, BG + (255,))
        return Image.alpha_composite(bg, im).convert("RGB")
    return im.convert("RGB")


def image_ratio(src):
    """Ratio largeur/hauteur de l'image source (pour choisir un ratio commun)."""
    with Image.open(src) as im:
        w, h = im.size
    return w / h


def _pad_to_ratio(im, ratio):
    """Letterboxe l'image sur fond noir pour atteindre EXACTEMENT `ratio` (jamais de crop)."""
    w, h = im.size
    cur = w / h
    if abs(cur - ratio) < 1e-3:
        return im
    if cur < ratio:                           # trop étroit -> barres gauche/droite
        tw = int(round(h * ratio))
        canvas = Image.new("RGB", (tw, h), BG)
        canvas.paste(im, ((tw - w) // 2, 0))
    else:                                     # trop large -> barres haut/bas
        th = int(round(w / ratio))
        canvas = Image.new("RGB", (w, th), BG)
        canvas.paste(im, (0, (th - h) // 2))
    return canvas


def convert_for_ig(src, dst, target_ratio=None):
    """Aplatit l'alpha sur noir, redimensionne (<=1440 large), sauve en JPEG <=8 Mo.
    - target_ratio fourni (carrousel) : letterboxe TOUTES les images à CE ratio commun
      (sinon Instagram recadre le carrousel sur le ratio de la 1re image).
    - sinon : letterbox seulement si le ratio sort de [0.8, 1.91]. Retourne (w, h)."""
    im = _open_rgb(src)
    if target_ratio is not None:
        im = _pad_to_ratio(im, target_ratio)
    else:
        ratio = im.size[0] / im.size[1]
        if ratio < AR_MIN:
            im = _pad_to_ratio(im, AR_MIN)
        elif ratio > AR_MAX:
            im = _pad_to_ratio(im, AR_MAX)

    w, h = im.size
    if w > MAX_WIDTH:
        im = im.resize((MAX_WIDTH, int(round(h * MAX_WIDTH / w))), Image.LANCZOS)

    q = JPEG_Q_START
    while True:
        im.save(dst, "JPEG", quality=q, optimize=True, progressive=True)
        if os.path.getsize(dst) <= MAX_IMAGE_MB * 1024 * 1024 or q <= 60:
            break
        q -= 6
    return im.size


def common_ratio(srcs):
    """Ratio commun pour un carrousel = médiane des ratios, bornée à [AR_MIN, AR_MAX]."""
    rs = []
    for s in srcs:
        try:
            rs.append(image_ratio(s))
        except Exception:
            pass
    if not rs:
        return None
    return min(AR_MAX, max(AR_MIN, statistics.median(rs)))


def contact_sheet(images, dst, cell=300, cols=5, bg=(17, 17, 17)):
    """Planche-contact JPEG à partir de chemins d'images (aperçu)."""
    if not images:
        return
    pad = 6
    rows = (len(images) + cols - 1) // cols
    W = cols * cell + (cols + 1) * pad
    H = rows * cell + (rows + 1) * pad
    sheet = Image.new("RGB", (W, H), bg)
    for i, f in enumerate(images):
        try:
            im = Image.open(f).convert("RGB")
        except Exception:
            continue
        im.thumbnail((cell, cell), Image.LANCZOS)
        r, c = divmod(i, cols)
        x = pad + c * (cell + pad) + (cell - im.width) // 2
        y = pad + r * (cell + pad) + (cell - im.height) // 2
        sheet.paste(im, (x, y))
    sheet.save(dst, "JPEG", quality=85)


# --------------------------------------------------------------- état / mapping
def existing_targets(slug):
    """Un post (brouillon/queue/publié) existe-t-il déjà pour ce slug ?"""
    hits = []
    for base, label in ((DRAFTS, "brouillon"), (QUEUE, "queue"), (PUBLISHED, "publié")):
        if not os.path.isdir(base):
            continue
        for n in os.listdir(base):
            if n.endswith("-" + slug) and os.path.isdir(os.path.join(base, n)):
                hits.append(label)
    return hits


def find_draft_dir(slug):
    if not os.path.isdir(DRAFTS):
        return None
    hits = sorted(n for n in os.listdir(DRAFTS)
                  if n.endswith("-" + slug) and os.path.isdir(os.path.join(DRAFTS, n)))
    return os.path.join(DRAFTS, hits[-1]) if hits else None


def load_sources():
    if not os.path.isfile(SOURCES_YML):
        return {}
    return yaml.safe_load(open(SOURCES_YML, encoding="utf-8")) or {}


def _norm(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode().lower()
    return re.sub(r"[^a-z0-9]+", " ", s).split()


def _folder_tokens(name):
    """'2023_LFDP' -> ['lfdp'] ; sépare le camelCase ('ToBeAMachine' -> to be a machine)."""
    name = re.sub(r"^\d{4}[_-]?", "", name)                    # retire l'année en tête
    name = re.sub(r"(?<=[a-z0-9])(?=[A-Z])", " ", name)        # aA -> a A
    name = re.sub(r"(?<=[A-Z])(?=[A-Z][a-z])", " ", name)      # AMachine -> A Machine
    return [t for t in _norm(name) if len(t) >= 2]             # ignore tokens d'1 lettre


def match_folder(slug, proj, folders):
    """Meilleure(s) correspondance(s) dossier local pour un projet (score simple)."""
    ptoks = {t for t in _norm(proj.get("title", "")) + _norm(slug) if len(t) >= 2}
    initials = "".join(w[0] for w in _norm(proj.get("title", "")) if w)
    scored = []
    for f in folders:
        ftoks = set(_folder_tokens(f))
        score = len(ptoks & ftoks)                        # mots communs
        for a in ptoks:
            for b in ftoks:
                if len(a) >= 4 and (a in b or b in a):    # sous-chaîne
                    score += 0.5
        if initials and initials in {"".join(ftoks), "".join(sorted(ftoks))}:
            score += 2                                    # sigle (LFDP, GFE…)
        for b in ftoks:                                   # sigle vs token unique
            if initials and b == initials:
                score += 2
        if score > 0:
            scored.append((score, f))
    scored.sort(reverse=True)
    return scored


# --------------------------------------------------------------- scan local
def _excluded(dirname):
    d = dirname.lower()
    return d.startswith(".") or d in EXCL_EXACT or any(s in d for s in EXCL_SUB)


def local_candidates(work_dir):
    """Images candidates d'un dossier de travail (filtrées, plafonnées).
    Stratégie : liste rapide (ext + taille mini + dossiers techniques élagués),
    tri par poids décroissant, puis lecture d'en-tête jusqu'à SCAN_MAX_CANDIDATES
    (côté long >= SCAN_MIN_LONG). Évite d'ouvrir des milliers d'images."""
    if not work_dir or not os.path.isdir(work_dir):
        return []
    pool = []
    for root, dirs, files in os.walk(work_dir):
        dirs[:] = [d for d in dirs if not _excluded(d)]   # ne pas descendre
        for n in files:
            if os.path.splitext(n)[1].lower() not in SRC_EXT:
                continue
            low = n.lower()
            if any(s in low for s in SKIP_NAME_SUB):    # captures d'écran, screenshots
                continue
            p = os.path.join(root, n)
            try:
                sz = os.path.getsize(p)
            except OSError:
                continue
            if sz >= SCAN_MIN_KB * 1024:
                pool.append((sz, p))
    pool.sort(reverse=True)                               # gros fichiers d'abord
    picked = []
    for sz, p in pool:
        try:
            with Image.open(p) as im:
                w, h = im.size
        except Exception:
            continue
        if max(w, h) >= SCAN_MIN_LONG:
            picked.append((p, w, h, sz))
            if len(picked) >= SCAN_MAX_CANDIDATES:
                break
    return picked


def write_candidates(out_dir, work_dir, verbose=True):
    """Remplit <draft>/candidates/ avec les images du dossier local (converties IG) +
    _sources.txt (origine) + _planche.jpg (aperçu). Retourne le nombre d'images."""
    cands = local_candidates(work_dir)
    cdir = os.path.join(out_dir, "candidates")
    if os.path.isdir(cdir):
        for n in os.listdir(cdir):
            os.remove(os.path.join(cdir, n))
    if not cands:
        if verbose:
            print(f"     (aucune image ≥{SCAN_MIN_LONG}px trouvée dans {work_dir})")
        return 0
    os.makedirs(cdir, exist_ok=True)
    made, srcmap = [], []
    for i, (p, w, h, sz) in enumerate(cands, 1):
        dst = os.path.join(cdir, f"cand-{i:02d}.jpg")
        try:
            convert_for_ig(p, dst)
            made.append(dst)
            srcmap.append(f"cand-{i:02d}.jpg  <-  {p}  ({w}x{h})")
        except Exception as e:
            if os.path.exists(dst):
                os.remove(dst)
            srcmap.append(f"(illisible) {p} : {e}")
    with open(os.path.join(cdir, "_sources.txt"), "w", encoding="utf-8") as f:
        f.write(f"# Candidats scannés depuis : {work_dir}\n")
        f.write("# Pour publier : remonte le fichier voulu dans le dossier parent,\n"
                "# renommé 0N.jpg, puis supprime candidates/.\n\n")
        f.write("\n".join(srcmap) + "\n")
    contact_sheet(made, os.path.join(cdir, "_planche.jpg"))
    if verbose:
        print(f"     + candidates/ : {len(made)} image(s) locales à trier (voir _planche.jpg)")
    return len(made)


# --------------------------------------------------------------- commandes
def cmd_list(_args):
    srcs = load_sources()
    print(f"{'IMG':>4}  {'ÉTAT':<24}  {'DOSSIER LOCAL':<26}  PROJET")
    print("-" * 92)
    for slug, proj in all_projects():
        n = len(source_images(slug))
        state = ", ".join(existing_targets(slug)) or "—"
        local = srcs.get(slug) or "—"
        print(f"{n:>4}  {state:<24}  {str(local):<26}  {proj.get('title', slug)}")


def cmd_map(args):
    if os.path.isfile(SOURCES_YML) and not args.force:
        sys.exit(f"{os.path.relpath(SOURCES_YML, ROOT)} existe déjà — --force pour réécrire.")
    if not os.path.isdir(WORK_ROOT):
        sys.exit(f"dossier de travail introuvable : {WORK_ROOT}")
    folders = sorted(n for n in os.listdir(WORK_ROOT)
                     if os.path.isdir(os.path.join(WORK_ROOT, n)) and not n.startswith("."))
    os.makedirs(SOCIAL, exist_ok=True)
    lines = [
        "# Mapping projet du site -> dossier de travail local. À VALIDER / CORRIGER.",
        f"# Racine des dossiers : {WORK_ROOT}",
        "# Valeur = nom du dossier (ou null si aucun). Le commentaire liste d'autres",
        "# candidats plausibles. Utilisé par : social_harvest.py scan / draft --scan.",
        "",
    ]
    for slug, proj in all_projects():
        scored = match_folder(slug, proj, folders)
        best = scored[0][1] if scored else None
        alts = ", ".join(f for _, f in scored[1:4])
        val = best if best else "null"
        line = f"{slug}: {val}"
        if alts:
            line += f"    # autres : {alts}"
        lines.append(line)
    with open(SOURCES_YML, "w", encoding="utf-8") as f:
        f.write("\n".join(lines) + "\n")
    print(f"✅ Mapping proposé écrit dans {os.path.relpath(SOURCES_YML, ROOT)}")
    print("→ RELIS-le et corrige les rattachements avant `scan` / `draft --scan`.")


def make_draft(proj, slug, max_images, force, scan_local=False):
    imgs = source_images(slug)
    if not imgs:
        print(f"  ⚠️  {slug} : aucune image dans assets/images/{slug}/ — ignoré")
        return None
    imgs = cover_first(proj, imgs)[:max_images]

    date = dt.date.today().isoformat()
    out = os.path.join(DRAFTS, f"{date}-{slug}")
    if os.path.isdir(out):
        if not force:
            print(f"  ⏭  {slug} : brouillon déjà présent — --force pour réécrire")
            return None
        for r, _, fs in os.walk(out, topdown=False):
            for n in fs:
                os.remove(os.path.join(r, n))
            if r != out:
                os.rmdir(r)
    os.makedirs(out, exist_ok=True)

    # Carrousel : ratio commun à toutes les images (sinon IG recadre sur la 1re).
    target_ratio = common_ratio(imgs) if len(imgs) >= 2 else None

    ok = []
    for i, src in enumerate(imgs, 1):
        dst = os.path.join(out, f"{i:02d}.jpg")
        try:
            convert_for_ig(src, dst, target_ratio=target_ratio)
            ok.append(os.path.basename(src))
        except Exception as e:
            print(f"     ! image illisible ignorée : {os.path.basename(src)} ({e})")
            if os.path.exists(dst):
                os.remove(dst)
    if not ok:
        print(f"  ⚠️  {slug} : aucune image exploitable — brouillon supprimé")
        os.rmdir(out)
        return None

    caption = build_caption(proj)
    header = (
        f"# BROUILLON généré le {date} par social_harvest.py — À VALIDER.\n"
        f"# Projet : {proj.get('title', slug)} (slug: {slug})\n"
        f"# 1) relis/ajuste la légende et l'ordre des images (01.jpg, 02.jpg…)\n"
        f"# 2) candidates/ = images locales EN PLUS (non publiées) : remonte les\n"
        f"#    voulues à la racine renommées 0N.jpg, supprime le reste + candidates/\n"
        f"# 3) DÉPLACE ce dossier dans ../queue/ pour publication par ig_publish.py\n"
        f"# Sources site : {', '.join(ok)}\n"
    )
    with open(os.path.join(out, "post.yml"), "w", encoding="utf-8") as f:
        f.write(header + "\n")
        yaml.safe_dump({"type": "auto", "caption": _Literal(caption)}, f,
                       allow_unicode=True, sort_keys=False, width=1000)

    kind = "image" if len(ok) == 1 else f"carrousel ({len(ok)})"
    print(f"  ✅ {slug} : {kind} → {os.path.relpath(out, ROOT)}")

    if scan_local:
        work = load_sources().get(slug)
        wdir = os.path.join(WORK_ROOT, work) if work else None
        if wdir:
            write_candidates(out, wdir)
        else:
            print(f"     (pas de dossier local mappé pour {slug} — voir sources.yml)")
    return out


def cmd_draft(args):
    os.makedirs(DRAFTS, exist_ok=True)
    if args.slug:
        proj = find_project(args.slug)
        if not proj:
            sys.exit(f"projet introuvable : {args.slug}")
        make_draft(proj, proj.get("slug"), args.max_images, args.force, args.scan)
        return
    made = 0
    for slug, proj in all_projects():
        if existing_targets(slug) and not args.force:
            continue
        if make_draft(proj, slug, args.max_images, args.force, args.scan):
            made += 1
            if args.next:
                break
    print(f"\n{made} brouillon(s) créé(s) dans {os.path.relpath(DRAFTS, ROOT)}/")
    if made:
        print("→ Relis, trie candidates/, puis déplace les dossiers validés dans ../queue/.")


def cmd_scan(args):
    srcs = load_sources()
    if not srcs:
        sys.exit("Aucun sources.yml — lance d'abord : social_harvest.py map (puis valide-le).")
    slugs = [args.slug] if args.slug else [s for s, _ in all_projects()]
    for slug in slugs:
        proj = find_project(slug)
        if not proj:
            print(f"  ⚠️  projet inconnu : {slug}")
            continue
        work = srcs.get(slug)
        if not work:
            if args.slug:
                print(f"  ⚠️  {slug} : aucun dossier local dans sources.yml")
            continue
        out = find_draft_dir(slug)
        if not out:
            out = make_draft(proj, slug, MAX_CAROUSEL, force=False)
            if not out:
                continue
        print(f"  🔍 {slug} ← {work}")
        write_candidates(out, os.path.join(WORK_ROOT, work))


def main():
    ap = argparse.ArgumentParser(description="Moissonneur de contenu Instagram (images).")
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("list", help="lister projets, nb d'images, état, dossier local")

    m = sub.add_parser("map", help="(re)générer sources.yml (mapping local À VALIDER)")
    m.add_argument("--force", action="store_true", help="réécrire sources.yml existant")

    d = sub.add_parser("draft", help="générer des brouillons de posts")
    g = d.add_mutually_exclusive_group()
    g.add_argument("slug", nargs="?", help="slug d'un projet précis")
    g.add_argument("--next", action="store_true", help="1er projet sans post/brouillon")
    g.add_argument("--all", action="store_true", help="tous les projets non traités")
    d.add_argument("--scan", action="store_true", help="ajouter candidates/ (dossier local)")
    d.add_argument("--max-images", type=int, default=MAX_CAROUSEL,
                   help=f"images site max par post (def. {MAX_CAROUSEL})")
    d.add_argument("--force", action="store_true", help="réécrire un brouillon existant")

    s = sub.add_parser("scan", help="remplir candidates/ depuis le dossier local mappé")
    sg = s.add_mutually_exclusive_group()
    sg.add_argument("slug", nargs="?", help="slug d'un projet")
    sg.add_argument("--all", action="store_true", help="tous les projets mappés")
    s.add_argument("--force", action="store_true")

    args = ap.parse_args()
    if args.cmd == "list":
        cmd_list(args)
    elif args.cmd == "map":
        cmd_map(args)
    elif args.cmd == "draft":
        if not (args.slug or args.next or args.all):
            sys.exit("précise un slug, ou --next, ou --all")
        cmd_draft(args)
    elif args.cmd == "scan":
        if not (args.slug or args.all):
            sys.exit("précise un slug, ou --all")
        cmd_scan(args)


if __name__ == "__main__":
    main()
