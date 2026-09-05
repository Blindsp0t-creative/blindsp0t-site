# BlindSp0t — site web

Copie statique du portfolio [blindsp0t.com](https://blindsp0t.com) (anciennement Cargo),
hébergée sur **GitHub Pages**. Même look & feel, même contenu, plus de back-end payant.

Le contenu vit dans des fichiers simples (`content/`) — **ajouter un projet ne demande
jamais de toucher au code**. Deux façons d'éditer :

- 🌐 **CMS web** (`/admin/`) — interface en ligne, éditable depuis n'importe où (voir plus bas).
- 💻 **Outil local** (`tools/manage.py`) — pour les imports/traitements d'images en masse.

---

## 1. Structure

```
content/
  site.yml                 réglages globaux (titre, contact, réseaux sociaux…)
  projects/NN-slug.md      1 fichier par projet (ordre, tags, blocs de contenu)
  pages/about.md, privacy.md
assets/
  images/<slug>/…          images des projets (pleine résolution optimisée)
  brand/                   logo + favicon
  css/style.css            reproduction fidèle du thème d'origine
  js/app.js                splash d'intro + diaporamas
admin/                     CMS web (Decap)
tools/
  scrape.py                import initial depuis Cargo (déjà exécuté)
  build.py                 générateur de site → _site/
  manage.py                outil local (créer projet, images, publier)
.github/workflows/deploy.yml   build + mise en ligne automatiques
```

Un projet ressemble à ceci :

```yaml
---
title: Mon Projet
slug: Mon-Projet
order: 1
tags: [installation, interactive]
cover: images/Mon-Projet/photo1.jpg
blocks:
  - type: text
    html: "Description du projet…"
  - type: gallery
    layout: slideshow      # slideshow | freeform | columns
    autoplay: true
    speed: 2.5
    images:
      - { file: images/Mon-Projet/photo1.jpg }
  - type: video
    src: https://player.vimeo.com/video/123456
---
```

---

## 2. Prérequis (une seule fois)

```bash
python3 -m venv tools/.venv
tools/.venv/bin/pip install -r tools/requirements.txt
```

---

## 3. Ajouter / modifier du contenu

### Option A — outil local

```bash
# créer un projet (assistant interactif)
tools/.venv/bin/python tools/manage.py new

# ajouter des images à un projet existant (galerie)
tools/.venv/bin/python tools/manage.py add-images Mon-Projet ~/photos/*.jpg

# prévisualiser en local → http://localhost:8765
tools/.venv/bin/python tools/manage.py serve

# publier (build + commit + push → mise en ligne auto)
tools/.venv/bin/python tools/manage.py publish "Ajout du projet X"
```

Autres commandes : `list`, `reorder`, `set-cover <slug> <image>`, `optimize`, `build`.

### Option B — CMS web (`/admin/`)

Une fois en ligne, aller sur `https://blindsp0t.com/admin/`, se connecter avec GitHub,
et éditer projets / pages / réglages via des formulaires. Chaque enregistrement crée un
commit et déclenche la reconstruction du site.

> ⚙️ **Activation (une seule fois).** Le CMS a besoin d'un relais d'authentification GitHub
> (GitHub Pages n'a pas de serveur). Étapes dans [`docs/CMS-SETUP.md`](docs/CMS-SETUP.md).
> Tant que ce n'est pas fait, l'outil local (Option A) suffit à tout gérer.

---

## 4. Mise en ligne

Le workflow **GitHub Actions** (`.github/workflows/deploy.yml`) reconstruit et publie
automatiquement à chaque `push` sur `main`.

Activation initiale : `Settings → Pages → Build and deployment → Source = GitHub Actions`.

### Bascule du domaine depuis Cargo

1. Vérifier le site sur l'URL GitHub Pages (`Settings → Pages`) ou en local (`manage.py serve`).
2. Dans `Settings → Pages → Custom domain`, saisir `blindsp0t.com` (le fichier `CNAME` est déjà généré).
3. Chez le registrar du domaine, faire pointer les DNS vers GitHub Pages :
   - `A` → `185.199.108.153`, `185.199.109.153`, `185.199.110.153`, `185.199.111.153`
   - `CNAME` `www` → `blindsp0t-creative.github.io`
4. Cocher **Enforce HTTPS** une fois le certificat émis.

> Astuce : pour tester sans couper Cargo, faire d'abord pointer un sous-domaine
> (ex. `new.blindsp0t.com`) vers Pages, valider, puis basculer l'apex.

---

## 5. Formulaire de contact

GitHub Pages étant statique, le formulaire passe par **Formspree** (gratuit) :

1. Créer un formulaire sur [formspree.io](https://formspree.io) (destinataire = votre email).
2. Copier l'identifiant du endpoint dans `content/site.yml` → `formspree_id`.

Tant qu'il est vide, la page Contact affiche un lien email de repli.

---

## 6. Ré-importer depuis Cargo

Le contenu a été importé automatiquement depuis l'ancien site :

```bash
tools/.venv/bin/python tools/scrape.py            # tout
tools/.venv/bin/python tools/scrape.py Mon-Projet # un seul projet
```
