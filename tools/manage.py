#!/usr/bin/env python3
"""
Outil local BlindSp0t — ajouter / gérer du contenu sans toucher au code.

Commandes :
  new                         Créer un projet (interactif)
  add-images <slug> [images]  Ajouter des images à un projet (galerie)
  set-cover <slug> <image>    Définir l'image de couverture
  optimize                    Optimiser toutes les images (redimension + compression)
  list                        Lister les projets et leur ordre
  reorder                     Réordonner les projets (interactif)
  build                       Générer le site dans _site/
  serve [port]                Prévisualiser en local (défaut : 8765)
  publish "message"           Générer + commit + push (déclenche la mise en ligne)

Exemples :
  tools/.venv/bin/python tools/manage.py new
  tools/.venv/bin/python tools/manage.py add-images Mon-Projet ~/photos/*.jpg
  tools/.venv/bin/python tools/manage.py publish "Ajout du projet X"
"""
import glob, os, re, shutil, subprocess, sys, unicodedata
from pathlib import Path
import yaml

ROOT = Path(__file__).resolve().parent.parent
CONTENT = ROOT / "content"
PROJ = CONTENT / "projects"
IMG = ROOT / "assets" / "images"
PY = sys.executable

MAX_W = 2000          # largeur max des images (px)
JPEG_Q = 82           # qualité JPEG


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or "projet"


def load(path):
    raw = Path(path).read_text(encoding="utf-8")
    m = re.match(r"^---\n(.*?)\n---\n?(.*)$", raw, re.S)
    return (yaml.safe_load(m.group(1)) or {}), (m.group(2) if m else "")


def write_project(fm):
    order = fm.get("order", 99)
    slug = fm["slug"]
    # supprime un éventuel ancien fichier de ce slug
    for old in PROJ.glob(f"*-{slug}.md"):
        old.unlink()
    out = PROJ / f"{int(order):02d}-{slug}.md"
    with open(out, "w", encoding="utf-8") as f:
        f.write("---\n")
        yaml.safe_dump(fm, f, allow_unicode=True, sort_keys=False, width=10000)
        f.write("---\n")
    return out


def all_projects():
    res = []
    for f in sorted(PROJ.glob("*.md")):
        fm, _ = load(f)
        res.append((f, fm))
    res.sort(key=lambda x: x[1].get("order", 999))
    return res


def find_project(slug):
    for f, fm in all_projects():
        if fm.get("slug") == slug or f.stem.endswith(slug):
            return f, fm
    print(f"! projet introuvable : {slug}")
    sys.exit(1)


# --------------------------------------------------------------- Pillow

def _pil():
    try:
        from PIL import Image
        return Image
    except ImportError:
        print("! Pillow requis : tools/.venv/bin/pip install Pillow")
        sys.exit(1)


def optimize_file(path):
    Image = _pil()
    p = Path(path)
    if p.suffix.lower() not in (".jpg", ".jpeg", ".png"):
        return
    try:
        im = Image.open(p)
    except Exception:
        return
    changed = False
    if im.width > MAX_W:
        h = round(im.height * MAX_W / im.width)
        im = im.resize((MAX_W, h), Image.LANCZOS)
        changed = True
    if p.suffix.lower() in (".jpg", ".jpeg"):
        im = im.convert("RGB")
        im.save(p, "JPEG", quality=JPEG_Q, optimize=True, progressive=True)
        changed = True
    elif p.suffix.lower() == ".png":
        im.save(p, "PNG", optimize=True)
        changed = True
    if changed:
        print(f"  ✓ {p.name} ({im.width}px, {p.stat().st_size//1024} Ko)")


def copy_image(src, slug):
    dest_dir = IMG / slug
    dest_dir.mkdir(parents=True, exist_ok=True)
    name = slugify(Path(src).stem) + Path(src).suffix.lower()
    dest = dest_dir / name
    n = 1
    while dest.exists():
        dest = dest_dir / f"{slugify(Path(src).stem)}-{n}{Path(src).suffix.lower()}"
        n += 1
    shutil.copy2(src, dest)
    optimize_file(dest)
    return f"images/{slug}/{dest.name}"


# ------------------------------------------------------------- commands

def cmd_new():
    title = input("Titre du projet : ").strip()
    slug = input(f"Slug [{slugify(title)}] : ").strip() or slugify(title)
    tags = [t.strip() for t in input("Tags (séparés par des virgules) : ").split(",") if t.strip()]
    orders = [fm.get("order", 0) for _, fm in all_projects()]
    default_order = 1
    order = input(f"Ordre d'affichage [1 = en premier] : ").strip()
    order = int(order) if order else default_order
    # décale les autres si besoin
    if order in orders:
        for f, fm in all_projects():
            if fm.get("order", 0) >= order:
                fm["order"] = fm["order"] + 1
                write_project(fm)
    blocks = []
    print("\nAjout de contenu (laisser vide pour terminer) :")
    print("  Astuce : le texte, les images et vidéos peuvent aussi s'éditer ensuite via le CMS web.")
    desc = input("Texte/description (optionnel) : ").strip()
    if desc:
        blocks.append({"type": "text", "html": desc.replace("\n", "<br>")})
    imgs = input("Dossier ou images de galerie (glob, optionnel) : ").strip()
    gallery_imgs = []
    if imgs:
        for g in glob.glob(os.path.expanduser(imgs)):
            gallery_imgs.append({"file": copy_image(g, slug)})
    if gallery_imgs:
        blocks.append({"type": "gallery", "layout": "slideshow", "autoplay": True,
                       "speed": 2.5, "arrows": True, "images": gallery_imgs})
    vid = input("URL vidéo embed (Vimeo/YouTube, optionnel) : ").strip()
    if vid:
        blocks.append({"type": "video", "src": vid})
    cover = gallery_imgs[0]["file"] if gallery_imgs else None
    fm = {"title": title, "slug": slug, "order": order, "tags": tags,
          "cover": cover, "blocks": blocks}
    out = write_project(fm)
    print(f"\n✓ Projet créé : {out.relative_to(ROOT)}")
    print("  Prévisualiser : tools/.venv/bin/python tools/manage.py serve")
    print("  Publier       : tools/.venv/bin/python tools/manage.py publish \"nouveau projet\"")


def cmd_add_images(args):
    slug = args[0]
    f, fm = find_project(slug)
    files = []
    for a in args[1:]:
        files += glob.glob(os.path.expanduser(a))
    if not files:
        print("! aucune image trouvée"); return
    added = [{"file": copy_image(x, fm["slug"])} for x in sorted(files)]
    # ajoute à la 1re galerie sinon en crée une
    gal = next((b for b in fm.get("blocks", []) if b["type"] == "gallery"), None)
    if gal:
        gal["images"].extend(added)
    else:
        fm.setdefault("blocks", []).append(
            {"type": "gallery", "layout": "slideshow", "autoplay": True,
             "speed": 2.5, "arrows": True, "images": added})
    if not fm.get("cover"):
        fm["cover"] = added[0]["file"]
    write_project(fm)
    print(f"✓ {len(added)} image(s) ajoutée(s) à {fm['slug']}")


def cmd_set_cover(args):
    slug, src = args[0], args[1]
    f, fm = find_project(slug)
    fm["cover"] = copy_image(os.path.expanduser(src), fm["slug"])
    write_project(fm)
    print(f"✓ couverture définie pour {fm['slug']}")


def cmd_optimize():
    files = [p for p in IMG.rglob("*") if p.is_file()]
    print(f"Optimisation de {len(files)} image(s)…")
    for p in files:
        optimize_file(p)
    print("✓ terminé")


def cmd_list():
    for f, fm in all_projects():
        n = len(fm.get("blocks", []))
        print(f"{fm.get('order',0):3d}  {fm.get('title','')[:50]:50s}  ({n} blocs)  {fm.get('slug')}")


def cmd_reorder():
    projs = all_projects()
    print("Ordre actuel :")
    for i, (f, fm) in enumerate(projs, 1):
        print(f"  {i}. {fm.get('title')}")
    print("Entrez le nouvel ordre des numéros (ex: 3 1 2 4 …), le reste garde sa place :")
    seq = input("> ").split()
    order = 1
    done = set()
    for tok in seq:
        idx = int(tok) - 1
        if 0 <= idx < len(projs):
            f, fm = projs[idx]; fm["order"] = order; write_project(fm); done.add(idx); order += 1
    for idx, (f, fm) in enumerate(projs):
        if idx not in done:
            fm["order"] = order; write_project(fm); order += 1
    print("✓ réordonné")


def cmd_build():
    subprocess.run([PY, str(ROOT / "tools" / "build.py")], check=True)


def cmd_serve(args):
    cmd_build()
    port = args[0] if args else "8765"
    os.chdir(ROOT / "_site")
    print(f"→ http://localhost:{port}  (Ctrl+C pour arrêter)")
    subprocess.run([PY, "-m", "http.server", port])


def cmd_publish(args):
    msg = args[0] if args else "Mise à jour du contenu"
    cmd_build()
    # Stage TOUT le dépôt suivi (content, assets, tools, admin, .github, docs…) ;
    # _site/ est gitignored donc exclu. Évite d'oublier silencieusement les
    # changements de code/config (build.py, admin/config.yml…) au moment de publier.
    subprocess.run(["git", "-C", str(ROOT), "add", "-A"], check=True)
    r = subprocess.run(["git", "-C", str(ROOT), "commit", "-m", msg])
    if r.returncode != 0:
        print("(rien à committer)")
    subprocess.run(["git", "-C", str(ROOT), "push"], check=True)
    print("✓ publié — GitHub Actions reconstruit et met en ligne le site.")


def main():
    if len(sys.argv) < 2:
        print(__doc__); return
    cmd, args = sys.argv[1], sys.argv[2:]
    {
        "new": lambda: cmd_new(),
        "add-images": lambda: cmd_add_images(args),
        "set-cover": lambda: cmd_set_cover(args),
        "optimize": lambda: cmd_optimize(),
        "list": lambda: cmd_list(),
        "reorder": lambda: cmd_reorder(),
        "build": lambda: cmd_build(),
        "serve": lambda: cmd_serve(args),
        "publish": lambda: cmd_publish(args),
    }.get(cmd, lambda: print(__doc__))()


if __name__ == "__main__":
    main()
