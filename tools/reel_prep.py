#!/usr/bin/env python3
"""
reel_prep.py — prépare une vidéo pour publication en Reel Instagram (À LANCER EN LOCAL).

- Entrée : un fichier vidéo LOCAL (.mp4/.mov/…) OU une URL Vimeo (téléchargée via yt-dlp).
- Ré-encode aux specs Reel : H.264 + AAC, 1080x1920 (9:16), ≤ ~90 s, +faststart.
- Génère 5 vignettes candidates (covers/cover-1..5.jpg) — tu choisiras la préférée.
- Crée un brouillon de post dans content/social/instagram/drafts/<date>-<slug>/
  (l'outil propose, tu valides : édite la légende + choisis la vignette, puis déplace
  le dossier dans ../queue/ et pousse).

Hébergement de la vidéo (Instagram la télécharge depuis une URL publique) :
  --host release  (défaut) : upload en asset d'une GitHub Release → `video_url:` dans
                  post.yml. La vidéo ne gonfle PAS le dépôt (hors arbre git).
  --host queue    : copie la vidéo ré-encodée dans le dossier (01.mp4), committée avec
                  le post. Simple, adapté aux clips légers.

Dépendances : ffmpeg (obligatoire), yt-dlp (pour Vimeo), gh authentifié (pour --host release).

Exemples :
  tools/.venv/bin/python tools/reel_prep.py ~/videos/installation.mov --slug installation-led
  tools/.venv/bin/python tools/reel_prep.py https://vimeo.com/123456789 --host queue
"""
import argparse
import datetime as dt
import re
import shutil
import subprocess
import sys
import tempfile
import unicodedata
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
DRAFTS = ROOT / "content" / "social" / "instagram" / "drafts"

FFMPEG = shutil.which("ffmpeg") or "ffmpeg"
YTDLP = shutil.which("yt-dlp")
GH = shutil.which("gh")

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


# ------------------------------------------------------------------ ffmpeg

def ffmpeg_info(path):
    """Renvoie (duration_seconds, has_audio) en lisant la sortie de `ffmpeg -i`."""
    r = run([FFMPEG, "-hide_banner", "-i", str(path)],
            stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True)
    out = r.stdout
    dur = 0.0
    m = re.search(r"Duration:\s*(\d+):(\d+):(\d+\.?\d*)", out)
    if m:
        h, mn, sec = m.groups()
        dur = int(h) * 3600 + int(mn) * 60 + float(sec)
    has_audio = bool(re.search(r"Stream #\d+:\d+.*Audio:", out))
    return dur, has_audio


def reencode(src, dst, fit, max_seconds, has_audio):
    if fit == "cover":                # remplit puis recadre (pas de bandes)
        vf = (f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=increase,"
              f"crop={REEL_W}:{REEL_H},setsar=1,fps={FPS}")
    else:                             # pad : letterbox noir (aucun recadrage)
        vf = (f"scale={REEL_W}:{REEL_H}:force_original_aspect_ratio=decrease,"
              f"pad={REEL_W}:{REEL_H}:(ow-iw)/2:(oh-ih)/2:color=black,setsar=1,fps={FPS}")
    cmd = [FFMPEG, "-y", "-hide_banner", "-i", str(src)]
    if not has_audio:                 # pas de piste audio -> ajoute un silence
        cmd += ["-f", "lavfi", "-i", "anullsrc=channel_layout=stereo:sample_rate=44100",
                "-shortest"]
    cmd += ["-t", str(max_seconds),
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

def fetch_vimeo(url, workdir):
    if not YTDLP:
        die("yt-dlp requis pour une URL Vimeo (brew install yt-dlp).")
    out_tmpl = str(workdir / "source.%(ext)s")
    r = run([YTDLP, "-f", "bestvideo[ext=mp4]+bestaudio/best[ext=mp4]/best",
             "--merge-output-format", "mp4", "-o", out_tmpl, url])
    if r.returncode != 0:
        die("échec du téléchargement Vimeo (yt-dlp).")
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


def upload_release(video, tag, asset_name):
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
    if run([GH, "release", "upload", tag, str(staged), "--clobber"]).returncode != 0:
        die("échec de l'upload sur la Release.")
    return f"https://github.com/{slug}/releases/download/{tag}/{asset_name}"


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
    ap.add_argument("--max-seconds", type=int, default=MAX_SECONDS)
    ap.add_argument("--tag", default=RELEASE_TAG, help="tag de la GitHub Release")
    args = ap.parse_args()

    if not shutil.which("ffmpeg"):
        die("ffmpeg introuvable (brew install ffmpeg).")

    with tempfile.TemporaryDirectory() as td:
        work = Path(td)
        # 1) résoudre l'entrée -> fichier local
        if is_url(args.input):
            src = fetch_vimeo(args.input, work)
            src_note = args.input
            default_slug = slugify(src.stem)
        else:
            src = Path(args.input).expanduser()
            if not src.is_file():
                die(f"fichier introuvable : {src}")
            src_note = src.name
            default_slug = slugify(src.stem)
        slug = slugify(args.slug) if args.slug else default_slug

        out_dir = DRAFTS / f"{args.date}-{slug}"
        if out_dir.exists():
            die(f"brouillon déjà présent : {out_dir.relative_to(ROOT)} (choisis un autre --slug)")
        out_dir.mkdir(parents=True)

        # 2) infos + ré-encodage
        dur, has_audio = ffmpeg_info(src)
        if dur > args.max_seconds:
            print(f"⚠ vidéo {dur:.0f}s > {args.max_seconds}s : tronquée à {args.max_seconds}s.")
        print(f"→ ré-encodage Reel ({args.fit}, {REEL_W}x{REEL_H}, ≤{args.max_seconds}s)…")
        reencoded = work / "reel.mp4"
        reencode(src, reencoded, args.fit, args.max_seconds, has_audio)
        enc_dur = min(dur, args.max_seconds) if dur else args.max_seconds
        size_mb = reencoded.stat().st_size / 1e6
        print(f"  ✓ ré-encodé : {size_mb:.1f} Mo")

        # 3) vignettes
        covers = make_thumbnails(reencoded, out_dir / "covers", enc_dur, n=5)
        print(f"  ✓ {len(covers)} vignettes → covers/cover-1..{len(covers)}.jpg")
        default_cover = f"covers/{covers[0].name}" if covers else "covers/cover-1.jpg"

        # 4) hébergement de la vidéo
        video_url = None
        if args.host == "queue":
            shutil.copy2(reencoded, out_dir / "01.mp4")
            print(f"  ✓ vidéo copiée dans le brouillon (01.mp4, {size_mb:.1f} Mo) — sera committée")
        else:
            asset = f"{args.date}-{slug}.mp4"
            print(f"→ upload de la vidéo sur la Release « {args.tag} »…")
            video_url = upload_release(reencoded, args.tag, asset)
            print(f"  ✓ vidéo hébergée : {video_url}")

        # 5) post.yml
        write_post_yml(out_dir, args.host, video_url, default_cover, slug,
                       args.date, src_note, enc_dur)

    print(f"\n✅ Brouillon prêt : {out_dir.relative_to(ROOT)}")
    print("   1) choisis la vignette (covers/) et mets-la dans reel_cover")
    print("   2) ajuste la légende dans post.yml")
    print("   3) déplace le dossier dans ../queue/ puis pousse")
    print("   Vérifier :  tools/.venv/bin/python tools/ig_publish.py --dry-run")


if __name__ == "__main__":
    main()
