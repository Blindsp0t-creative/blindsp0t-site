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
   - **Reel** : une vidéo `.mp4`/`.mov` (H.264 + AAC, 9:16 conseillé, ≤ 100 Mo).
3. Éditer `post.yml` (légende + hashtags ; `type: auto` suffit dans la plupart des cas).
4. Committer / pousser (`git add … && git push`, ou l'outil habituel). C'est tout :
   le lundi, le cron publie le **plus ancien** post éligible et le déplace dans
   `published/`.

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
