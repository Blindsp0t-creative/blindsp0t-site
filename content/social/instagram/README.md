# Publication automatique Instagram

Publie **un post par semaine** sur `@blindsp0t_studio` depuis ce dossier, via
GitHub Actions, sans navigateur. Chemin API : « Instagram API with Instagram Login »
(aucune Page Facebook requise). Plan complet : `claudeDOC/INSTAGRAM-AUTOPOST.md`.

## Ajouter un post (aucun code)
1. Copier le dossier `_modele/` dans `queue/` et le renommer, ex.
   `queue/2026-09-15-installation-led/` (le préfixe date sert à l'ordre de passage).
2. Y déposer les médias :
   - **Image / carrousel** : fichiers **JPEG** `01.jpg`, `02.jpg`, … (2 à 10 pour un
     carrousel, ≤ 8 Mo chacun). L'ordre des noms = l'ordre d'affichage.
   - **Reel** : une vidéo `.mp4`/`.mov` — voir la section dédiée « Publier un Reel » plus bas.
3. Éditer `post.yml` (légende + hashtags ; `type: auto` suffit dans la plupart des cas).
4. Committer / pousser (`git add … && git push`, ou l'outil habituel). C'est tout :
   le lundi, le cron publie le **plus ancien** post éligible et le déplace dans
   `published/`.

## Publier un Reel (vidéo) — ⚠️ chemin non encore testé de bout en bout
Le code gère les Reels, mais aucun Reel n'a encore été publié en conditions réelles.

### Le plus simple : `reel_prep.py` (À LANCER EN LOCAL)
Cet outil **ré-encode** la vidéo aux specs Reel, génère **5 vignettes candidates**, crée
le **brouillon** de post, et **héberge la vidéo sur une GitHub Release** (hors dépôt →
n'alourdit pas le dépôt). Entrée : un **fichier local** ou une **URL Vimeo**.

```bash
# fichier local (héberge la vidéo sur une Release GitHub — défaut)
tools/.venv/bin/python tools/reel_prep.py ~/videos/installation.mov --slug installation-led
# depuis Vimeo
tools/.venv/bin/python tools/reel_prep.py https://vimeo.com/123456789 --slug ma-piece
# variantes : --host queue (committe la vidéo au lieu de la Release) ; --fit cover
#             (remplir+recadrer au lieu du letterbox 9:16) ; --max-seconds 60
```
Puis, dans le brouillon `drafts/<date>-<slug>/` créé :
1. **choisis ta vignette** parmi `covers/cover-1..5.jpg` et mets son nom dans `reel_cover`
   (ex. `reel_cover: covers/cover-3.jpg`), supprime les autres si tu veux ;
2. **ajuste la légende** dans `post.yml` ;
3. **déplace** le dossier dans `../queue/` et pousse (`git add -A && git push`).

Dépendances (local) : **ffmpeg** (obligatoire), **yt-dlp** (pour Vimeo), **gh** authentifié
(pour `--host release`).

### À la main (sans l'outil)
Créer `queue/<date>-slug/` avec **une seule vidéo** `01.mp4` (`type: auto` → reel), une
`caption`, et une vignette `reel_cover:`. Specs : **MP4 H.264 + AAC, 9:16, 3–90 s**.

### Points communs / limites
- La publication attend la **fin de l'encodage** côté Instagram (jusqu'à ~5 min) — normal.
- Si la vidéo ne respecte pas les specs, le run échoue proprement (conteneur `ERROR`),
  sans rien publier.
- **Hébergement** : `--host release` garde la vidéo **hors du dépôt** (recommandé). En
  `--host queue` (ou dépôt manuel), la vidéo est servie par **URL brute GitHub** → GitHub
  **bloque > 100 Mo** et alourdit le dépôt public.
- ⚠️ Reste à **valider au 1er vrai Reel** que le fetch de l'URL (Release ou raw) par
  Instagram fonctionne.

## Vérifier avant de publier
```bash
tools/.venv/bin/python tools/ig_publish.py --list                 # voir la file
tools/.venv/bin/python tools/ig_publish.py --dry-run --check-urls # valider médias + URLs
```

## Comment ça marche
- Les médias sont servis par **URL brute GitHub** (dépôt public) ; Instagram les
  télécharge depuis cette URL. Ils doivent donc être **poussés sur `main`** avant le
  passage du cron (c'est le cas dès que la file est versionnée).
- Après publication, le post passe de `queue/` à `published/` (⇒ pas de doublon) et
  une ligne est ajoutée à `log.json` (media_id + permalink).

## Dossiers
- `queue/` — posts en attente (traités du plus ancien au plus récent).
- `published/` — archive des posts déjà publiés.
- `_modele/` — gabarit à copier (ignoré par le script : il ne scanne que `queue/`).
- `log.json` — journal des publications.
