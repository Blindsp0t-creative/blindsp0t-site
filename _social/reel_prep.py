#!/usr/bin/env python3
"""
reel_prep.py — prépare une vidéo pour publication en Reel Instagram (À LANCER EN LOCAL).

- Entrée : un fichier vidéo LOCAL (.mp4/.mov/…) OU une URL Vimeo (téléchargée via yt-dlp).
  Vidéo Vimeo privée/non répertoriée (URL avec un hash, ex. /1221116062/0f72…) : ajouter
  --cookies-from-browser safari (ou chrome/firefox/brave), connecté au compte Vimeo.
- Portion : --start/--end pour ne garder qu'un extrait (SS, MM:SS ou HH:MM:SS).
- Cadre : --crop W:H:X:Y (pixels source) pour recadrer avant le passage en 9:16.
- Repérage : --probe n'encode rien, sort une image à grille 10 % + les dimensions,
  pour choisir le cadre et les bornes, puis relancer sans --probe.
- Ré-encode aux specs Reel : H.264 + AAC, 1080x1920 (9:16), ≤ ~90 s, +faststart.
- Génère 5 vignettes candidates (covers/cover-1..5.jpg) — tu choisiras la préférée.
- Crée un brouillon de post dans _social/instagram/drafts/<date>-<slug>/
  (l'outil propose, tu valides : édite la légende + choisis la vignette, puis déplace
  le dossier dans ../queue/ et pousse).

Hébergement de la vidéo (Instagram la télécharge depuis une URL publique) :
  --host release  (défaut) : upload en asset d'une GitHub Release → `video_url:` dans
                  post.yml. La vidéo ne gonfle PAS le dépôt (hors arbre git).
  --host queue    : copie la vidéo ré-encodée dans le dossier (01.mp4), committée avec
                  le post. Simple, adapté aux clips légers.

Dépendances : ffmpeg (obligatoire), yt-dlp (pour Vimeo), gh authentifié (pour --host release).
yt-dlp : binaire imposé (_YTDLP_DEFAULT), surchargeable via la variable d'env YTDLP_BIN,
sinon repli sur celui du PATH.

Exemples :
  tools/.venv/bin/python _social/reel_prep.py ~/videos/installation.mov --slug installation-led
  tools/.venv/bin/python _social/reel_prep.py https://vimeo.com/123456789 --host queue
  # Vimeo privé / non répertorié (auth par cookies du navigateur) :
  tools/.venv/bin/python _social/reel_prep.py https://vimeo.com/1221116062/0f72abcd \
      --cookies-from-browser safari --slug depth-experiments
  # 1) repérer cadre + bornes :
  tools/.venv/bin/python _social/reel_prep.py ~/videos/inst.mov --probe --start 0:12
  # 2) extraire 0:12→0:38 et recadrer un cadre 1080x1920 à x=420 :
  tools/.venv/bin/python _social/reel_prep.py ~/videos/inst.mov --start 0:12 --end 0:38 \
      --crop 1080:1920:420:0
"""
import argparse
import datetime as dt
import re
import shutil
import os
import subprocess
import sys
import tempfile
import time
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "_social" / "instagram" / "drafts"

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
GH = shutil.which("gh")

# yt-dlp : binaire imposé (surchargeable via $YTDLP_BIN), sinon repli sur le PATH.
_YTDLP_DEFAULT = "/Users/blindsp0t/BLINDSP0T/projets/2026_BLAST/_MEDIAS/zapping/yt-dlp_macos_last"


def _resolve_ytdlp():
    cand = os.environ.get("YTDLP_BIN") or _YTDLP_DEFAULT
    if cand and os.path.isfile(cand) and os.access(cand, os.X_OK):
        return cand
    return shutil.which("yt-dlp")


YTDLP = _resolve_ytdlp()

REEL_W, REEL_H = 1080, 1920          # 9:16
MAX_SECONDS = 90                     # durée max (Reels : viser 5–90 s)
FPS = 30
CRF = 23                            # qualité (plus bas = mieux/plus lourd)
MAXRATE, BUFSIZE = "8M", "12M"
RELEASE_TAG = "reels"               # tag de la GitHub Release qui héberge les vidéos

HASHTAGS = ("#blindsp0t #artnumerique #newmediaart #creativecoding #installationart "
            "#lyon #digitalart #mediaart #generativeart #immersiveart")


def die(msg, code=1):
    print(f"! {msg}")
    sys.exit(code)


def run(cmd, **kw):
    return subprocess.run(cmd, **kw)


def slugify(s):
    s = unicodedata.normalize("NFKD", s).encode("ascii", "ignore").decode()
    s = re.sub(r"[^A-Za-z0-9]+", "-", s).strip("-")
    return s or "reel"


def parse_time(s):
    """Convertit 'SS', 'MM:SS' ou 'HH:MM:SS' (décimales OK) en secondes. None si vide."""
    if s is None:
        return None
    s = str(s).strip()
    if not s:
        return None
    try:
        parts = [float(p) for p in s.split(":")]
    except ValueError:
        die(f"temps invalide : {s!r} (attendu SS, MM:SS ou HH:MM:SS)")
    sec = 0.0
    for p in parts:
        sec = sec * 60 + p
    return sec


def parse_crop(s, src_w, src_h):
    """Parse 'W:H:X:Y' (pixels source, origine haut-gauche) et valide les bornes."""
    m = re.match(r"^(\d+):(\d+):(\d+):(\d+)$", s.strip())
    if not m:
        die("--crop attend W:H:X:Y en pixels (ex. 1080:1920:420:0). "
            "Lance --probe pour repérer les coordonnées.")
    cw, ch, cx, cy = (int(x) for x in m.groups())
    if cw <= 0 or ch <= 0:
        die("--crop : largeur et hauteur doivent être > 0.")
    if src_w and src_h and (cx + cw > src_w or cy + ch > src_h):
        die(f"--crop {cw}:{ch}:{cx}:{cy} déborde de la source {src_w}x{src_h} "
            f"(X+W ≤ {src_w}, Y+H ≤ {src_h}).")
    return cw, ch, cx, cy


FONT_CANDIDATES = ("/System/Library/Fonts/Supplemental/Arial.ttf",
                   "/Library/Fonts/Arial.ttf")


def _grid_font():
    for f in FONT_CANDIDATES:
        if os.path.isfile(f):
            return f
    return None


def make_probe(src, out_path, at_seconds, src_w, src_h):
    """Écrit une image de repérage (grille 10 %, coordonnées px) au temps donné."""
    # grille tous les 10 % ; réduite pour l'affichage (les fractions restent valides)
    filters = [f"drawgrid=w=iw/10:h=ih/10:t=2:c=red@0.8"]
    font = _grid_font()
    if font and src_w and src_h:
        for i in range(1, 10):                      # étiquettes X (px) tous les 10 %
            x = round(src_w * i / 10)
            filters.append(f"drawtext=fontfile='{font}':text='{x}':x=W*{i}/10+3:y=6:"
                           f"fontsize=H/28:fontcolor=yellow:box=1:boxcolor=black@0.6")
        for j in range(1, 10):                      # étiquettes Y (px) tous les 10 %
            y = round(src_h * j / 10)
            filters.append(f"drawtext=fontfile='{font}':text='{y}':x=6:y=H*{j}/10+3:"
                           f"fontsize=H/28:fontcolor=yellow:box=1:boxcolor=black@0.6")
    filters.append("scale='min(960,iw)':-2")        # confort d'affichage
    r = run([FFMPEG, "-y", "-hide_banner", "-ss", f"{at_seconds:.2f}", "-i", str(src),
             "-frames:v", "1", "-vf", ",".join(filters), "-q:v", "3", str(out_path)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    return out_path.exists() and r.returncode == 0


# ------------------------------------------------------------------ ffmpeg

def ffmpeg_info(path):
    """Renvoie (duration_seconds, has_audio, width, height) via `ffmpeg -i`."""
    r = run([FFMPEG, "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = r.stdout
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if m:
        h, mn, sec = m.groups()
        dur = int(h) * 3600 + int(mn) * 60 + float(sec)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*Audio:", out))
    # dimensions : 1re occurrence "<w>x<h>" sur une ligne de flux vidéo
    w = h = 0
    vm = re.search(r"Video:.*?(\d{2,5})x(\d{2,5})", out)
    if vm:
        w, h = int(vm.group(1)), int(vm.group(2))
    return dur, has_audio, w, h


def reencode(src, dst, fit, duration, has_audio, start=0.0, crop=None):
    filters = []
    if crop:                          # 1) cadre choisi dans la source (px)
        cw, ch, cx, cy = crop
        filters.append(f"crop={cw}:{ch}:{cx}:{cy}")
    if fit == "cover":                # 2a) remplit puis recadre (pas de bandes)
        filters += [f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase",
                    f"crop={REEL_W}:{REEL_H}"]
    else:                             # 2b) pad : letterbox noir (aucun recadrage)
        filters += [f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease",
                    f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=black"]
    filters += ["setsar=1", f"fps={FPS}"]
    vf = ",".join(filters)
    cmd = [FFMPEG, "-y", "-hide_banner"]
    if start and start > 0:           # seek d'entrée : rapide ET précis au ré-encodage
        cmd += ["-ss", f"{start:.3f}"]
    cmd += ["-i", str(src)]
    if not has_audio:                 # pas de piste audio -> ajoute un silence
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-shortest"]
    cmd += ["-t", f"{duration:.3f}",
            "-vf", vf,
            "-c:v", "libx264", "-profile:v", "high", "-pix_fmt", "yuv420p",
            "-preset", "medium", "-crf", str(CRF), "-maxrate", MAXRATE, "-bufsize", BUFSIZE,
            "-c:a", "aac", "-b:a", "128k", "-movflags", "+faststart", str(dst)]
    if run(cmd).returncode != 0:
        die("échec du ré-encodage ffmpeg")


def make_thumbnails(video, out_dir, duration, n=5):
    out_dir.mkdir(parents=True, exist_ok=True)
    covers = []
    fracs = [(i + 1) / (n + 1) for i in range(n)]     # 1/6, 2/6, … pour n=5 -> 5 points
    for i, f in enumerate(fracs, 1):
        t = max(0.0, min(duration * f, max(0.0, duration - 0.1)))
        dst = out_dir / f"cover-{i}.jpg"
        run([FFMPEG, "-y", "-hide_banner", "-ss", f"{t:.2f}", "-i", str(video),
             "-frames:v", "1", "-q:v", "3", str(dst)],
            stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        if dst.exists():
            covers.append(dst)
    return covers


# ------------------------------------------------------------------ entrée

def fetch_vimeo(url, workdir, cookies_from_browser=None, cookies_file=None):
    if not YTDLP:
        die("yt-dlp requis pour une URL Vimeo (brew install yt-dlp).")
    out_tmpl = str(workdir / "source.%(ext)s")
    cmd = [YTDLP, "-f", "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
           "--merge-output-format", "mp4", "-o", out_tmpl]
    # vidéos non répertoriées / privées : authentification via cookies du navigateur
    if cookies_from_browser:
        cmd += ["--cookies-from-browser", cookies_from_browser]
    if cookies_file:
        cmd += ["--cookies", cookies_file]
    cmd.append(url)
    if run(cmd).returncode != 0:
        die("échec du téléchargement Vimeo (yt-dlp). Vidéo privée/non répertoriée ? "
            "Ajoute --cookies-from-browser safari (ou chrome/firefox) — connecté à ton compte Vimeo.")
    files = sorted(workdir.glob("source.*"))
    if not files:
        die("vidéo Vimeo introuvable après téléchargement.")
    return files[0]


def is_url(s):
    return s.startswith("http://") or s.startswith("https://")


# --------------------------------------------------------------- release gh

def repo_slug():
    r = run([GH, "repo", "view", "--json", "nameWithOwner", "-q", ".nameWithOwner"],
            stdout=subprocess.PIPE, text=True)
    return r.stdout.strip() if r.returncode == 0 else None


def upload_release(video, tag, asset_name, retries=3):
    """Upload l'asset sur la Release (idempotent, --clobber). Renvoie l'URL, ou None
    après `retries` échecs (le réseau GitHub peut timeouter) — l'appelant gère le repli."""
    if not GH:
        die("gh requis pour --host release (ou utilise --host queue).")
    slug = repo_slug()
    if not slug:
        die("dépôt GitHub introuvable (gh repo view).")
    # crée la release si absente (idempotent)
    if run([GH, "release", "view", tag], stdout=subprocess.DEVNULL,
           stderr=subprocess.DEVNULL).returncode != 0:
        run([GH, "release", "create", tag, "--title", "Reels (médias)",
             "--notes", "Vidéos hébergées pour publication Instagram (Reels)."],
            stdout=subprocess.DEVNULL)
    # upload sous un nom stable = asset_name
    staged = video.parent / asset_name
    if staged != video:
        shutil.copy2(video, staged)
    url = f"https://github.com/{slug}/releases/download/{tag}/{asset_name}"
    for attempt in range(1, retries + 1):
        if run([GH, "release", "upload", tag, str(staged), "--clobber"]).returncode == 0:
            return url
        print(f"  ⚠ upload Release : tentative {attempt}/{retries} échouée.")
        if attempt < retries:
            time.sleep(5 * attempt)
    return None


# ------------------------------------------------------------------ post.yml

def write_post_yml(out_dir, host, video_url, default_cover, slug, date, src_note, dur):
    lines = [
        f"# BROUILLON Reel généré le {date} par reel_prep.py — À VALIDER.",
        f"# Source : {src_note}  (durée ré-encodée ≤ {min(dur, MAX_SECONDS):.0f} s)",
        "# 1) choisis ta vignette parmi covers/cover-1..5.jpg et mets son nom dans reel_cover",
        "#    (supprime les autres covers/ si tu veux) ; 2) ajuste la légende ;",
        "# 3) DÉPLACE ce dossier dans ../queue/ puis pousse (git add -A && git push).",
    ]
    if host == "release":
        lines.append("# Vidéo hébergée sur GitHub Release (hors dépôt) — voir video_url.")
    body = [
        "",
        "type: reel",
        f"reel_cover: {default_cover}",
    ]
    if host == "release":
        body.append(f'video_url: "{video_url}"')
    body += [
        "caption: |",
        f"  {slug.replace('-', ' ').title()}",
        "",
        "  (Décris l'œuvre en une ou deux phrases.)",
        "",
        f"  {HASHTAGS}",
        "",
    ]
    (out_dir / "post.yml").write_text("\n".join(lines + body), encoding="utf-8")


# ---------------------------------------------------------------------- main

def main():
    ap = argparse.ArgumentParser(description="Prépare une vidéo pour un Reel Instagram.")
    ap.add_argument("input", help="fichier vidéo local OU URL Vimeo")
    ap.add_argument("--slug", help="nom du post (défaut : dérivé du fichier/URL)")
    ap.add_argument("--date", default=dt.date.today().isoformat(), help="AAAA-MM-JJ")
    ap.add_argument("--host", choices=["release", "queue"], default="release",
                    help="release = vidéo sur GitHub Release (défaut) ; queue = committée")
    ap.add_argument("--fit", choices=["pad", "cover"], default="pad",
                    help="pad = letterbox 9:16 (défaut) ; cover = remplir + recadrer")
    ap.add_argument("--start", help="début de la portion à garder (SS, MM:SS ou HH:MM:SS)")
    ap.add_argument("--end", help="fin de la portion à garder (SS, MM:SS ou HH:MM:SS)")
    ap.add_argument("--crop", help="cadre de recadrage W:H:X:Y en pixels source "
                                   "(origine haut-gauche ; cf. --probe)")
    ap.add_argument("--probe", action="store_true",
                    help="n'encode rien : affiche dimensions/durée + une image de repérage "
                         "(grille 10 %) au temps --start, pour choisir --crop / --start / --end")
    ap.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    ap.add_argument("--tag", default=RELEASE_TAG, help="tag de la GitHub Release")
    ap.add_argument("--cookies-from-browser",
                    help="pour une URL Vimeo privée/non répertoriée : navigateur où tu es "
                         "connecté à Vimeo (safari, chrome, firefox, brave, edge…)")
    ap.add_argument("--cookies", help="alternative : fichier cookies.txt (format Netscape)")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        die("ffmpeg introuvable (brew install ffmpeg).")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        # 1) résoudre l'entrée -> fichier local
        if is_url(args.input):
            src = fetch_vimeo(args.input, work, args.cookies_from_browser, args.cookies)
            src_note = args.input
            default_slug = slugify(src.stem)
        else:
            src = Path(args.input).expanduser()
            if not src.is_file():
                die(f"fichier introuvable : {src}")
            src_note = src.name
            default_slug = slugify(src.stem)
        slug = slugify(args.slug) if args.slug else default_slug

        # 2) infos source (durée, audio, dimensions)
        dur, has_audio, src_w, src_h = ffmpeg_info(src)

        # 2a) fenêtre à conserver (trim) : --start / --end -> seek + durée
        start = parse_time(args.start) or 0.0
        end = parse_time(args.end)
        if dur and start >= dur:
            die(f"--start {start:.2f}s ≥ durée source {dur:.2f}s.")
        if end is not None and end <= start:
            die(f"--end ({end:.2f}s) doit être > --start ({start:.2f}s).")
        window = (end - start) if end is not None else ((dur - start) if dur else args.max_seconds)
        enc_dur = window
        if enc_dur > args.max_seconds:
            print(f"⚠ portion {window:.0f}s > {args.max_seconds}s : tronquée à {args.max_seconds}s "
                  f"(augmente --max-seconds si besoin).")
            enc_dur = args.max_seconds

        # 2b) cadre de recadrage éventuel
        crop = parse_crop(args.crop, src_w, src_h) if args.crop else None

        # --probe : repérage seulement, aucun encodage / aucun brouillon
        if args.probe:
            dims = f"{src_w}x{src_h}" if src_w else "inconnues"
            print(f"Source : {src_note}")
            print(f"  dimensions : {dims}   durée : {dur:.2f}s")
            print(f"  portion visée : {start:.2f}s → "
                  f"{(end if end is not None else dur):.2f}s  (≈ {enc_dur:.0f}s encodés)")
            probe_img = Path.cwd() / f"probe-{slug}.jpg"
            if make_probe(src, probe_img, start, src_w, src_h):
                print(f"  image de repérage : {probe_img}")
                print("  → grille tous les 10 % ; étiquettes jaunes = pixels source (X en haut, Y à gauche).")
                print(f"  → cadre = --crop W:H:X:Y (X+W ≤ {src_w or '?'}, Y+H ≤ {src_h or '?'}).")
            else:
                print("  (impossible de générer l'image de repérage)")
            return

        out_dir = DRAFTS / f"{args.date}-{slug}"
        if out_dir.exists():
            die(f"brouillon déjà présent : {out_dir.relative_to(ROOT)} (choisis un autre --slug)")
        out_dir.mkdir(parents=True)

        # 3) ré-encodage (trim -> crop -> 9:16)
        span = f", portion {start:.0f}–{start + enc_dur:.0f}s" if (start or end is not None) else ""
        cropn = f", crop {':'.join(map(str, crop))}" if crop else ""
        print(f"→ ré-encodage Reel ({args.fit}, {REEL_W}x{REEL_H}, ≤{enc_dur:.0f}s{span}{cropn})…")
        reencoded = work / "reel.mp4"
        reencode(src, reencoded, args.fit, enc_dur, has_audio, start=start, crop=crop)
        size_mb = reencoded.stat().st_size / 1e6
        print(f"  ✓ ré-encodé : {size_mb:.1f} Mo")

        # 3) vignettes
        covers = make_thumbnails(reencoded, out_dir / "covers", enc_dur, n=5)
        print(f"  ✓ {len(covers)} vignettes → covers/cover-1..{len(covers)}.jpg")
        default_cover = f"covers/{covers[0].name}" if covers else "covers/cover-1.jpg"

        # 4) hébergement de la vidéo
        video_url = None
        if args.host == "release":
            asset = f"{args.date}-{slug}.mp4"
            print(f"→ upload de la vidéo sur la Release « {args.tag} »…")
            video_url = upload_release(reencoded, args.tag, asset)
            if video_url:
                print(f"  ✓ vidéo hébergée : {video_url}")
            else:
                # repli : ne PAS perdre l'encodage — on committe la vidéo dans le brouillon
                args.host = "queue"
                print("  ⚠ upload Release impossible (réseau ?) — repli sur --host queue : "
                      "la vidéo est sauvegardée dans le brouillon (voir ci-dessous). "
                      f"Réessai manuel possible :\n"
                      f"     gh release upload {args.tag} <fichier>.mp4 --clobber")
        if args.host == "queue":
            shutil.copy2(reencoded, out_dir / "01.mp4")
            print(f"  ✓ vidéo copiée dans le brouillon (01.mp4, {size_mb:.1f} Mo) — sera committée")

        # 5) post.yml (note de provenance : source + trim/crop appliqués)
        note = src_note
        if start or end is not None:
            note += f" [portion {start:.0f}–{start + enc_dur:.0f}s]"
        if crop:
            note += f" [crop {':'.join(map(str, crop))}]"
        write_post_yml(out_dir, args.host, video_url, default_cover, slug,
                       args.date, note, enc_dur)

    print(f"\n✅ Brouillon prêt : {out_dir.relative_to(ROOT)}")
    print("   1) choisis la vignette (covers/) et mets-la dans reel_cover")
    print("   2) ajuste la légende dans post.yml")
    print("   3) déplace le dossier dans ../queue/ puis pousse")
    print("   Vérifier :  tools/.venv/bin/python _social/ig_publish.py --dry-run")


if __name__ == "__main__":
    main()
