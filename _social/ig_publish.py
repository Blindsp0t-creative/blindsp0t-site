#!/usr/bin/env python3
"""
Publication automatique Instagram — chemin « Instagram API with Instagram Login ».

Publie UN post (le plus ancien éligible) depuis _social/instagram/queue/.
Gère image simple, carrousel (2–10 médias) et Reel. Sans navigateur.
Les médias sont servis en URL brute GitHub (dépôt public), l'API Instagram les
télécharge depuis cette URL — donc les fichiers doivent être poussés sur `main`
avant la publication (c'est le cas au moment du cron : la file est déjà versionnée).

Variables d'environnement (secrets GitHub Actions) :
  IG_ACCESS_TOKEN   token longue durée (~60 j) du compte pro (obligatoire pour publier)
  IG_USER_ID        identifiant du compte pro Instagram (obligatoire pour publier)
  IG_RAW_BASE       (option) base des URLs brutes ; défaut = dépôt public sur main
  IG_API_VERSION    (option) version d'API Graph ; défaut = v23.0

Commandes :
  python _social/ig_publish.py --dry-run [--check-urls]   valide sans publier
  python _social/ig_publish.py --list                     liste la file d'attente
  python _social/ig_publish.py                            publie le plus ancien éligible
  python _social/ig_publish.py --post <slug>              publie ce post précis
  python _social/ig_publish.py --no-commit                ne pas committer/pousser après

Structure d'un post (un dossier par post dans queue/) :
  queue/2026-09-15-nom-court/
      post.yml          type/caption/publish_after (voir _modele/post.yml)
      01.jpg 02.jpg …   images (JPEG), ordre = nom de fichier
      ou 01.mp4         une vidéo -> Reel
"""
import argparse
import hashlib
import json
import os
import shutil
import subprocess
import sys
import time
from datetime import date, datetime
from pathlib import Path

import yaml

try:
    import requests
except ImportError:
    print("! module 'requests' requis : pip install requests")
    sys.exit(1)

ROOT = Path(__file__).resolve().parent.parent
SOCIAL = ROOT / "_social" / "instagram"
QUEUE = SOCIAL / "queue"
PUBLISHED = SOCIAL / "published"
LOG = SOCIAL / "log.json"

GRAPH = "https://graph.instagram.com"
API_VERSION = os.environ.get("IG_API_VERSION", "v23.0")
RAW_BASE = os.environ.get(
    "IG_RAW_BASE",
    "https://raw.githubusercontent.com/Blindsp0t-creative/blindsp0t-site/main",
).rstrip("/")

IMAGE_EXT = {".jpg", ".jpeg"}          # Instagram n'accepte pas le PNG
VIDEO_EXT = {".mp4", ".mov"}
MAX_IMAGE_MB = 8
MAX_VIDEO_MB = 100
MAX_CAPTION = 2200
POLL_MAX = 60                          # ~5 min max (60 x 5 s) pour l'encodage Reel
POLL_EVERY = 5


# --------------------------------------------------------------- lecture file

def post_dirs():
    """Dossiers de posts dans la file, triés par nom (donc par date en préfixe)."""
    if not QUEUE.exists():
        return []
    return sorted(d for d in QUEUE.iterdir() if d.is_dir() and (d / "post.yml").exists())


def load_post(d):
    data = yaml.safe_load((d / "post.yml").read_text(encoding="utf-8")) or {}
    return data


def media_files(d, post):
    """Médias du dossier (hors éventuelle vignette de Reel), triés par nom."""
    cover = post.get("reel_cover")
    files = []
    for p in sorted(d.iterdir()):
        if p.name == cover:
            continue
        if p.suffix.lower() in IMAGE_EXT | VIDEO_EXT:
            files.append(p)
    return files


def detect_type(post, medias):
    t = (post.get("type") or "auto").lower()
    if t != "auto":
        return t
    if post.get("video_url"):            # vidéo hébergée hors dépôt (Release/CDN)
        return "reel"
    has_video = any(p.suffix.lower() in VIDEO_EXT for p in medias)
    if has_video:
        return "reel"
    return "carousel" if len(medias) >= 2 else "image"


def is_eligible(post):
    pa = post.get("publish_after")
    if not pa:
        return True
    if isinstance(pa, datetime):
        pa = pa.date()
    if isinstance(pa, str):
        pa = date.fromisoformat(pa.strip())
    return pa <= date.today()


def raw_url(path):
    """URL brute GitHub d'un fichier du dépôt (chemin relatif à la racine du repo)."""
    rel = path.resolve().relative_to(ROOT).as_posix()
    return f"{RAW_BASE}/{rel}"


# ------------------------------------------------------------------ appels API

def _node():
    # Chemin « Instagram Login » (base graph.instagram.com) : le token identifie déjà le
    # compte, donc `me` résout toujours vers le bon nœud de publication. On n'utilise PAS
    # IG_USER_ID ici : le `user_id` (17841…) appartient à l'ancien chemin graph.facebook.com
    # et provoque une erreur « Object with ID does not exist » (code 100/subcode 33).
    # Échappatoire : IG_NODE_OVERRIDE permet de forcer un id explicite si besoin.
    return os.environ.get("IG_NODE_OVERRIDE", "").strip() or "me"


def _token():
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    if not tok:
        print("! IG_ACCESS_TOKEN manquant (secret GitHub Actions).")
        sys.exit(2)
    return tok


def _redact(msg):
    """Masque le token dans un message d'erreur (les exceptions requests recrachent
    l'URL complète avec ?access_token=…, sinon le secret fuiterait dans les traces)."""
    tok = os.environ.get("IG_ACCESS_TOKEN", "").strip()
    s = str(msg)
    if tok:
        s = s.replace(tok, "***")
    return s


def api_post(node, params):
    url = f"{GRAPH}/{API_VERSION}/{node}"
    params = {**params, "access_token": _token()}
    try:
        r = requests.post(url, data=params, timeout=120)
    except requests.RequestException as e:
        print(f"! erreur réseau sur POST {node} : {_redact(e)}")
        sys.exit(4)
    if not r.ok:
        print(f"! API {r.status_code} sur POST {node} : {_redact(r.text)[:500]}")
        sys.exit(3)
    return r.json()


def api_get(node, params):
    url = f"{GRAPH}/{API_VERSION}/{node}"
    params = {**params, "access_token": _token()}
    try:
        r = requests.get(url, params=params, timeout=60)
    except requests.RequestException as e:
        print(f"! erreur réseau sur GET {node} : {_redact(e)}")
        sys.exit(4)
    if not r.ok:
        print(f"! API {r.status_code} sur GET {node} : {_redact(r.text)[:500]}")
        sys.exit(3)
    return r.json()


def wait_ready(container_id):
    """Attend qu'un conteneur (vidéo/Reel) soit FINISHED avant publication."""
    for _ in range(POLL_MAX):
        st = api_get(container_id, {"fields": "status_code,status"}).get("status_code")
        if st in ("FINISHED", None):   # None = champ non renvoyé → publish() gère via retry
            return
        if st == "ERROR":
            print(f"! encodage du média en erreur (container {container_id})")
            sys.exit(3)
        time.sleep(POLL_EVERY)
    print("! délai d'encodage dépassé (le média n'est pas prêt).")
    sys.exit(3)


def create_image_container(url, caption=None, carousel_item=False):
    params = {"image_url": url}
    if caption is not None:
        params["caption"] = caption
    if carousel_item:
        params["is_carousel_item"] = "true"
    return api_post(f"{_node()}/media", params)["id"]


def create_video_container(url, caption=None, carousel_item=False,
                           as_reel=False, cover_url=None):
    params = {"video_url": url, "media_type": "REELS" if as_reel else "VIDEO"}
    if caption is not None:
        params["caption"] = caption
    if carousel_item:
        params["is_carousel_item"] = "true"
    if cover_url:
        params["cover_url"] = cover_url
    cid = api_post(f"{_node()}/media", params)["id"]
    wait_ready(cid)                       # vidéo = encodage asynchrone
    return cid


def create_carousel(children_ids, caption):
    params = {"media_type": "CAROUSEL", "children": ",".join(children_ids)}
    if caption is not None:
        params["caption"] = caption
    cid = api_post(f"{_node()}/media", params)["id"]
    wait_ready(cid)          # le conteneur carrousel doit être FINISHED avant publication
    return cid


def publish(creation_id):
    # edge de publication : /{node}/media_publish. Le conteneur peut ne pas être encore
    # prêt (code 9007 « media not ready ») : on réessaie quelques fois avant d'abandonner.
    url = f"{GRAPH}/{API_VERSION}/{_node()}/media_publish"
    for _ in range(POLL_MAX):
        r = requests.post(url, data={"creation_id": creation_id,
                                     "access_token": _token()}, timeout=120)
        if r.ok:
            return r.json()
        err = r.json().get("error", {})
        if err.get("code") == 9007 or err.get("error_subcode") == 2207027:
            time.sleep(POLL_EVERY)   # pas encore prêt → attendre et réessayer
            continue
        print(f"! API {r.status_code} sur media_publish : {r.text[:500]}")
        sys.exit(3)
    print("! média toujours pas prêt après plusieurs tentatives.")
    sys.exit(3)


def permalink(media_id):
    try:
        return api_get(media_id, {"fields": "permalink"}).get("permalink")
    except SystemExit:
        return None


# ---------------------------------------------------------------- validation

def validate(d, post, medias, kind):
    errs, warns = [], []
    caption = post.get("caption") or ""
    video_url = post.get("video_url")
    if not medias and not video_url:
        errs.append("aucun média (jpg/jpeg/mp4/mov) dans le dossier")
    if len(caption) > MAX_CAPTION:
        errs.append(f"légende trop longue ({len(caption)} > {MAX_CAPTION})")
    for p in medias:
        ext = p.suffix.lower()
        mb = p.stat().st_size / 1e6
        if ext in IMAGE_EXT and mb > MAX_IMAGE_MB:
            errs.append(f"{p.name} : image {mb:.1f} Mo > {MAX_IMAGE_MB} Mo")
        if ext in VIDEO_EXT and mb > MAX_VIDEO_MB:
            errs.append(f"{p.name} : vidéo {mb:.1f} Mo > {MAX_VIDEO_MB} Mo")
    # incohérences PNG (souvent une erreur d'export)
    for p in sorted(d.iterdir()):
        if p.suffix.lower() == ".png":
            warns.append(f"{p.name} : PNG ignoré (convertir en JPEG)")
    if kind == "carousel" and not (2 <= len(medias) <= 10):
        errs.append(f"carrousel : {len(medias)} médias (attendu 2 à 10)")
    if kind == "reel":
        vids = [p for p in medias if p.suffix.lower() in VIDEO_EXT]
        if video_url:
            if vids:
                warns.append("reel : video_url ET vidéo locale — la video_url est utilisée")
        elif len(vids) != 1:
            errs.append(f"reel : {len(vids)} vidéo(s) locale(s) (attendu 1, ou un video_url)")
        rc = post.get("reel_cover")
        if rc and not str(rc).startswith("http") and not (d / rc).is_file():
            errs.append(f"reel_cover introuvable : {rc}")
    if kind == "image" and len(medias) != 1:
        errs.append(f"image : {len(medias)} médias (attendu 1)")
    return errs, warns


def check_urls(medias):
    warns = []
    for p in medias:
        u = raw_url(p)
        try:
            r = requests.head(u, timeout=20, allow_redirects=True)
            if not r.ok:
                warns.append(f"{p.name} : URL brute {r.status_code} ({u}) — pas encore poussé sur main ?")
        except requests.RequestException as e:
            warns.append(f"{p.name} : URL injoignable ({e})")
    return warns


# ------------------------------------------------------------------ commandes

def cmd_whoami():
    """Sonde d'identité : empreinte du token (sans fuite) + qui l'API reconnaît."""
    tok = _token()
    fp = hashlib.sha256(tok.encode()).hexdigest()[:12]
    print(f"token: len={len(tok)} sha256[:12]={fp} node={_node()}")
    data = api_get(_node(), {"fields": "id,username,account_type"})
    print("me:", json.dumps(data, ensure_ascii=False))


def cmd_selftest():
    """Diagnostic non destructif : crée des conteneurs (jamais publiés) et affiche
    chaque réponse, pour isoler ce qui échoue en CI vs local."""
    cmd_whoami()
    dirs = post_dirs()
    if not dirs:
        print("selftest: file vide"); return
    p = media_files(dirs[0], load_post(dirs[0]))[0]
    url = raw_url(p)
    print("image_url:", url)
    endpoint = f"{GRAPH}/{API_VERSION}/{_node()}/media"

    def _try(label, data, headers=None):
        try:
            r = requests.post(endpoint, data={**data, "access_token": _token()},
                              headers=headers, timeout=60)
            print(f"{label}: {r.status_code} {r.text[:300]}")
        except Exception as e:  # noqa: BLE001
            print(f"{label}: EXC {e}")

    _try("A) image simple", {"image_url": url})
    _try("B) carousel_item", {"image_url": url, "is_carousel_item": "true"})
    _try("C) image simple + UA navigateur", {"image_url": url},
         headers={"User-Agent": "Mozilla/5.0 (curl-like)"})


def cmd_list():
    dirs = post_dirs()
    if not dirs:
        print("File d'attente vide."); return
    for d in dirs:
        post = load_post(d)
        medias = media_files(d, post)
        kind = detect_type(post, medias)
        flag = "" if is_eligible(post) else f"  (après {post.get('publish_after')})"
        print(f"  {d.name:40s} {kind:9s} {len(medias)} média(s){flag}")


def do_dry_run(dirs, want_urls):
    ok = True
    for d in dirs:
        post = load_post(d)
        medias = media_files(d, post)
        kind = detect_type(post, medias)
        errs, warns = validate(d, post, medias, kind)
        if want_urls and not errs:
            warns += check_urls(medias)
        print(f"\n• {d.name}  [{kind}, {len(medias)} média(s)]")
        for w in warns:
            print(f"    ⚠ {w}")
        for e in errs:
            print(f"    ✗ {e}"); ok = False
        if not errs:
            print("    ✓ prêt à publier")
    print("\n✓ validation OK" if ok else "\n✗ des erreurs bloquent la publication")
    return ok


def append_log(entry):
    data = []
    if LOG.exists():
        try:
            data = json.loads(LOG.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            data = []
    data.append(entry)
    LOG.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")


def move_to_published(d):
    PUBLISHED.mkdir(parents=True, exist_ok=True)
    dest = PUBLISHED / d.name
    if dest.exists():
        dest = PUBLISHED / f"{d.name}-{int(time.time())}"
    shutil.move(str(d), str(dest))
    return dest


def git_commit_push(message):
    subprocess.run(["git", "-C", str(ROOT), "add", "-A"], check=True)
    r = subprocess.run(["git", "-C", str(ROOT), "commit", "-m", message])
    if r.returncode != 0:
        print("(rien à committer)"); return
    subprocess.run(["git", "-C", str(ROOT), "push"], check=True)


def publish_one(d, do_commit=True):
    post = load_post(d)
    medias = media_files(d, post)
    kind = detect_type(post, medias)
    caption = post.get("caption") or ""
    errs, _ = validate(d, post, medias, kind)
    if errs:
        for e in errs:
            print(f"    ✗ {e}")
        print(f"! post invalide, non publié : {d.name}")
        sys.exit(1)

    print(f"→ publication de {d.name}  [{kind}]")
    rc = post.get("reel_cover")
    cover_url = None
    if rc:
        cover_url = rc if str(rc).startswith("http") else raw_url(d / rc)

    if kind == "image":
        cid = create_image_container(raw_url(medias[0]), caption=caption)
    elif kind == "reel":
        # vidéo : URL externe (Release/CDN) si fournie, sinon fichier local du dossier
        if post.get("video_url"):
            video_url = post["video_url"]
        else:
            video_url = raw_url(next(p for p in medias if p.suffix.lower() in VIDEO_EXT))
        cid = create_video_container(video_url, caption=caption,
                                     as_reel=True, cover_url=cover_url)
    elif kind == "carousel":
        children = []
        for p in medias:
            if p.suffix.lower() in VIDEO_EXT:
                children.append(create_video_container(raw_url(p), carousel_item=True))
            else:
                children.append(create_image_container(raw_url(p), carousel_item=True))
        cid = create_carousel(children, caption)
    else:
        print(f"! type inconnu : {kind}"); sys.exit(1)

    media_id = publish(cid).get("id")
    link = permalink(media_id)
    print(f"✓ publié — media_id={media_id}" + (f"  {link}" if link else ""))

    append_log({
        "post": d.name, "type": kind, "media_id": media_id,
        "permalink": link, "published_at": datetime.now().isoformat(timespec="seconds"),
    })
    move_to_published(d)
    if do_commit:
        git_commit_push(f"Instagram: publication {d.name}")
    else:
        print("(--no-commit : file/journal modifiés localement, non poussés)")


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Publication automatique Instagram.")
    ap.add_argument("--dry-run", action="store_true", help="valide sans publier")
    ap.add_argument("--check-urls", action="store_true",
                    help="(avec --dry-run) vérifie que les URLs brutes répondent")
    ap.add_argument("--list", action="store_true", help="liste la file d'attente")
    ap.add_argument("--whoami", action="store_true",
                    help="diagnostic : empreinte du token + identité reconnue par l'API")
    ap.add_argument("--selftest", action="store_true",
                    help="diagnostic : crée des conteneurs (non publiés) pour isoler un échec")
    ap.add_argument("--post", metavar="SLUG", help="publie ce dossier précis")
    ap.add_argument("--no-commit", action="store_true",
                    help="ne pas committer/pousser après publication")
    args = ap.parse_args()

    if args.whoami:
        cmd_whoami(); return

    if args.selftest:
        cmd_selftest(); return

    if args.list:
        cmd_list(); return

    dirs = post_dirs()

    if args.dry_run:
        target = [d for d in dirs if not args.post or d.name == args.post]
        if not target:
            print("Rien à valider."); return
        sys.exit(0 if do_dry_run(target, args.check_urls) else 1)

    # publication réelle
    if args.post:
        d = QUEUE / args.post
        if not (d.is_dir() and (d / "post.yml").exists()):
            print(f"! post introuvable : {args.post}"); sys.exit(1)
        publish_one(d, do_commit=not args.no_commit)
        return

    eligible = [d for d in dirs if is_eligible(load_post(d))]
    if not eligible:
        print("Aucun post éligible cette fois-ci (file vide ou dates futures).")
        return
    publish_one(eligible[0], do_commit=not args.no_commit)


if __name__ == "__main__":
    main()
