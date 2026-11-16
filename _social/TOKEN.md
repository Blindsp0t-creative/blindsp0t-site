# Régénérer le token Instagram

Le secret **`IG_ACCESS_TOKEN`** (utilisé par le workflow pour publier) est un token
**longue durée ~60 jours**. Quand il expire, la publication échoue : il faut en générer
un neuf et mettre à jour le secret. Compte : `@blindsp0t_studio` · app Meta :
**« BlindSp0t Autopost »** · chemin « Instagram API with Instagram Login » (nœud `me`).

> ⚠️ Un token expiré ne peut **pas** être rafraîchi (`refresh_access_token` ne marche que
> sur un token encore valide). S'il est expiré, il faut en **générer un neuf** (étape 1).

## 1. Générer un token neuf (dashboard Meta, navigateur)
1. [developers.facebook.com/apps](https://developers.facebook.com/apps) → app **« BlindSp0t Autopost »**.
2. Menu de gauche **Instagram → « API setup with Instagram login »**.
3. Section **« Générez des tokens d'accès »** : (re)générer le token de `@blindsp0t_studio`
   (ou **« Ajouter un compte »** → connexion → autoriser ; le compte est déjà testeur de l'app).
4. Copier le token. ⚠️ Ne pas le coller ailleurs que dans le secret (étape 3).

## 2. Vérifier qu'il est bien longue durée (~60 j)
```bash
TOKEN='colle_le_nouveau_token'
curl -sS -w '\nHTTP %{http_code}\n' \
  "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=$TOKEN"
```
- `expires_in` ≈ **5 184 000** (~60 j) → bon (le token du dashboard est en général déjà
  longue durée ; celui renvoyé ici est rafraîchi à neuf, l'un ou l'autre convient).
- Si « not a long-lived token » → l'échanger avec la **clé secrète Instagram** (dashboard,
  champ « Clé secrète Instagram ») :
  ```bash
  SECRET='colle_la_cle_secrete_instagram'
  curl -sS -w '\nHTTP %{http_code}\n' \
    "https://graph.instagram.com/access_token?grant_type=ig_exchange_token&client_secret=$SECRET&access_token=$TOKEN"
  ```

## 3. Mettre à jour le secret GitHub
```bash
printf %s "$TOKEN" | gh secret set IG_ACCESS_TOKEN -R Blindsp0t-creative/blindsp0t-site
```
(ou UI : Settings → Secrets and variables → Actions → `IG_ACCESS_TOKEN` → Update)

Noter la nouvelle échéance (~60 j) pour le prochain renouvellement.

---

## ⚠️ Piège DNS rencontré : `graph.instagram.com` ne résout pas
Symptôme en local : `curl: (6) Could not resolve host: graph.instagram.com` (et `HTTP 000`).

Cause : un **résolveur DNS local filtrant** (VPN / Pi-hole / NextDNS / AdGuard…) renvoie
**NXDOMAIN** pour `graph.instagram.com` (souvent classé « tracker Meta » dans les
blocklists), alors que `instagram.com` et `graph.facebook.com` passent. Diagnostic :
```bash
nslookup graph.instagram.com 1.1.1.1   # résout (57.144.x.x)
nslookup graph.instagram.com           # NXDOMAIN via le résolveur local -> c'est lui
```
> N'affecte **que la machine locale**. Le runner GitHub Actions utilise son propre DNS :
> la publication automatique n'est pas touchée (seules les commandes `curl` ci-dessus le sont).

**Contournements** (un seul suffit) :
- Désactiver le VPN / filtre DNS, puis relancer.
- Basculer le DNS système sur `1.1.1.1` / `8.8.8.8` le temps de l'opération.
- Épingler l'IP juste pour curl (sans rien changer au système) :
  ```bash
  IGIP=$(nslookup graph.instagram.com 1.1.1.1 2>/dev/null | awk '/^Address: /{ip=$2} END{print ip}')
  curl -sS --resolve graph.instagram.com:443:"$IGIP" -w '\nHTTP %{http_code}\n' \
    "https://graph.instagram.com/refresh_access_token?grant_type=ig_refresh_token&access_token=$TOKEN"
  ```
  (TLS reste valide : curl garde le nom d'hôte, il ne change que l'IP.)
