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

## Publier un Reel (vidéo) — ⚠️ non encore testé de bout en bout
Le code gère les Reels, mais aucun Reel n'a encore été publié en conditions réelles
(seuls images/carrousels sont validés). Marche à suivre :

1. Créer un dossier dans `queue/`, ex. `queue/2026-09-20-installation-led/`.
2. Y déposer **une seule vidéo** nommée `01.mp4` (ou `.mov`). Une seule vidéo par post :
   la détection `type: auto` en fait un **reel** (pas de carrousel vidéo ici).
   - Specs Instagram : **MP4, H.264 + AAC**, ratio **9:16** conseillé (jusqu'à 1080×1920),
     durée **3 s–90 s**, et **≤ ~50 Mo** (voir la limite d'hébergement ci-dessous).
3. `post.yml` : `type: auto` (ou `type: reel`) + `caption`. Vignette optionnelle :
   `reel_cover: cover.jpg` (déposer aussi cette image dans le dossier).
4. Committer / pousser, puis publier comme un post normal (cron du lundi ou
   `workflow_dispatch`). La publication attend la **fin de l'encodage** côté Instagram
   (jusqu'à ~5 min) — c'est normal.

**⚠️ Limite d'hébergement vidéo.** Les médias sont servis par **URL brute GitHub**. Or
GitHub **bloque les fichiers > 100 Mo** (alerte dès 50 Mo) et une vidéo committée
**alourdit définitivement le dépôt public**. Pour des Reels réguliers ou lourds, préférer
un **autre hébergement** (ex. lien Vimeo/CDN via `IG_RAW_BASE`) plutôt que git-raw.
Si la vidéo ne respecte pas les specs, le run échoue proprement (conteneur en `ERROR`),
sans rien publier.

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
