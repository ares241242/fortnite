# Boutique Fortnite → Instagram (automatique)

Chaque jour à 00h15 UTC (2h15 heure de Paris en été, 1h15 en hiver), GitHub :
1. récupère la boutique du jour (API gratuite fortnite-api.com, en français) ;
2. génère un carrousel de 1 à 10 images 1080×1350 (objets triés du plus cher au moins cher) ;
3. le publie sur ton compte Instagram avec une légende et des hashtags.

Tu n'as rien à faire une fois la configuration terminée. Ton PC peut être éteint.

## Configuration (une seule fois, ~20 min)

### 1. Compte Instagram
Ton compte doit être un **compte professionnel** (Créateur ou Entreprise) :
Instagram → Paramètres → Type de compte et outils → Passer à un compte professionnel.

### 2. App Meta + jeton d'accès
1. Va sur https://developers.facebook.com/apps → **Créer une app** → cas d'usage
   « Gérer les messages et le contenu sur Instagram ».
2. Dans **API Instagram → Configuration de l'API avec connexion Instagram** :
   - section « Générer des jetons d'accès » → **Ajouter un compte** → connecte ton Instagram ;
   - clique sur **Générer le jeton** : copie le jeton (c'est ton `IG_ACCESS_TOKEN`, valable 60 jours) ;
   - note l'**ID** affiché sous ton compte (c'est ton `IG_USER_ID`).
3. Vérifie que la permission `instagram_business_content_publish` est bien activée.

> L'app peut rester en mode « Développement » : elle publie sans problème sur ton propre compte.

### 3. Dépôt GitHub
1. Crée un dépôt **public** sur https://github.com/new (public obligatoire : Instagram doit
   pouvoir télécharger les images depuis `raw.githubusercontent.com`).
2. Envoie-y ces fichiers (`shop.py`, `requirements.txt`, `.gitignore`, `.github/workflows/boutique.yml`).
3. Dans le dépôt : **Settings → Secrets and variables → Actions → New repository secret**, ajoute :

| Nom | Valeur |
|---|---|
| `IG_ACCESS_TOKEN` | le jeton de l'étape 2 |
| `IG_USER_ID` | l'ID de l'étape 2 |
| `GH_PAT` | *(recommandé)* un jeton GitHub pour renouveler le jeton Instagram automatiquement |

Le workflow « Renouveler le jeton Instagram » prolonge le jeton chaque lundi.
`GH_PAT` n'est utile que si Instagram renvoie un jeton différent (le workflow échoue alors
et GitHub t'envoie un e-mail) : https://github.com/settings/personal-access-tokens/new →
accès à ce dépôt uniquement → permission **Secrets : Read and write** → expiration longue.

### 4. Tester
Onglet **Actions** → « Boutique Fortnite -> Instagram » → **Run workflow**.
Le post apparaît sur Instagram en 1 à 2 minutes. Ensuite, ça tourne tout seul chaque jour.

## Personnaliser
- **Heure** : ligne `cron` dans `.github/workflows/boutique.yml` (heure UTC). GitHub peut
  avoir quelques minutes de retard.
- **Légende / hashtags** : variable `caption` dans `shop.py`.
- **Couleurs, titre, grille** : constantes en haut de `shop.py`.
- Les pistes musicales (Festival) sont ignorées pour ne garder que les cosmétiques.

## Tester en local
```
pip install -r requirements.txt
python shop.py generate
```
Les images sont créées dans `out/<date>/`.
