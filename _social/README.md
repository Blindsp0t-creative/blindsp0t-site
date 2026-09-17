# _social — publication Instagram (@blindsp0t_studio)

Tout ce qui concerne **Instagram** vit ici, séparé du site (le site est à la racine du
dépôt). L'objectif : publier **un post par semaine** (photo, carrousel ou Reel), sans
navigateur, via GitHub Actions. Voie API : « Instagram API with Instagram Login ».

Doc détaillée : `../../claudeDOC/instaBot/` (`INSTAGRAM-AUTOPOST.md`, `SOCIAL-HARVEST.md`).

## Contenu
```
_social/
├── ig_publish.py        publie le prochain post de instagram/queue/ (utilisé par le workflow)
├── social_harvest.py    génère des brouillons de posts À PARTIR des projets du site
├── reel_prep.py         (local) prépare une vidéo en Reel : ré-encode + vignettes + brouillon
└── instagram/
    ├── queue/           posts à publier (le cron prend le plus ancien) — voir son README
    ├── published/       archive après publication
    ├── drafts/          brouillons générés (à valider puis déplacer dans queue/)
    ├── _modele/         gabarit de post
    ├── sources.yml      mapping projet → dossier de travail local (pour social_harvest)
    └── log.json         journal des publications (media_id + permalink)
```

## Comment ça publie
- Le workflow **`.github/workflows/instagram.yml`** (à la racine du dépôt — contrainte
  GitHub) tourne **chaque lundi 08:00 UTC** (+ bouton « Run workflow ») et lance
  `_social/ig_publish.py`.
- Les médias sont servis par **URL brute GitHub** (`raw.githubusercontent.com/.../_social/…`) ;
  Instagram les télécharge de là. Les vidéos lourdes vont plutôt sur une **GitHub Release**
  (via `reel_prep.py --host release`) pour ne pas alourdir le dépôt.
- Secrets (dans Settings → Secrets → Actions du dépôt) : `IG_ACCESS_TOKEN` (token longue
  durée ~60 j, à rafraîchir avant ~mi-novembre 2026), `IG_USER_ID` (posé mais inutilisé —
  le script publie sur le nœud `me`).

## Usage (le venv est partagé avec le site : `tools/.venv`)
```bash
# publication (ce que fait le workflow) — valider avant :
tools/.venv/bin/python _social/ig_publish.py --list
tools/.venv/bin/python _social/ig_publish.py --dry-run --check-urls

# générer des brouillons depuis le site :
tools/.venv/bin/python _social/social_harvest.py list
tools/.venv/bin/python _social/social_harvest.py draft --next

# préparer une vidéo en Reel (local ; fichier ou URL Vimeo) :
tools/.venv/bin/python _social/reel_prep.py <video|url> --slug mon-reel
```

## Publier concrètement
Valider un brouillon de `instagram/drafts/` (légende + vignette), le **déplacer dans
`instagram/queue/`**, committer/pousser → publication au prochain cron (ou « Run workflow »).
Détail du format d'un post : **`instagram/README.md`**.

> ⚠️ Publier = action **publique et irréversible**. Le cron publie automatiquement tout
> post présent dans `queue/`.
