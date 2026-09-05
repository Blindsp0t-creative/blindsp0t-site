# Activer le CMS web (`/admin/`)

Le CMS Decap édite le contenu directement sur GitHub. Comme GitHub Pages n'a pas de
serveur, il faut un petit **relais d'authentification GitHub** (gratuit). À faire une
seule fois. En attendant, l'**outil local** (`tools/manage.py`) permet déjà de tout gérer.

## Étape 1 — Créer une OAuth App GitHub

`GitHub → Settings → Developer settings → OAuth Apps → New OAuth App`

- **Application name** : BlindSp0t CMS
- **Homepage URL** : `https://blindsp0t.com`
- **Authorization callback URL** : `https://blindsp0t-cms.VOTRE-COMPTE.workers.dev/callback`
  (l'URL exacte du worker de l'étape 2)

Notez le **Client ID** et générez un **Client Secret**.

## Étape 2 — Déployer le relais OAuth (Cloudflare Workers, gratuit)

On utilise le worker open-source `sveltia-cms-auth` (compatible Decap) :

1. Créer un compte gratuit sur [Cloudflare](https://dash.cloudflare.com).
2. `Workers & Pages → Create → Worker`, déployer le code de
   <https://github.com/sveltia/sveltia-cms-auth> (bouton *Deploy* du dépôt, ou copier
   son `src/index.js`).
3. Dans les **Settings → Variables** du worker, ajouter :
   - `GITHUB_CLIENT_ID` = le Client ID de l'étape 1
   - `GITHUB_CLIENT_SECRET` = le Client Secret
   - `ALLOWED_DOMAINS` = `blindsp0t.com` (optionnel, restreint l'usage)
4. Noter l'URL du worker, ex. `https://blindsp0t-cms.VOTRE-COMPTE.workers.dev`.

## Étape 3 — Brancher le CMS

Dans [`admin/config.yml`](../admin/config.yml), remplacer la ligne `base_url` :

```yaml
backend:
  name: github
  repo: Blindsp0t-creative/blindsp0t-site
  branch: main
  base_url: https://blindsp0t-cms.VOTRE-COMPTE.workers.dev
```

Committer/pusher. C'est prêt : `https://blindsp0t.com/admin/` → *Login with GitHub*.

> Alternative sans Cloudflare : héberger le même relais sur un site Netlify gratuit,
> ou utiliser [Sveltia CMS](https://github.com/sveltia/sveltia-cms) (remplaçant direct
> de Decap, même `config.yml`).
