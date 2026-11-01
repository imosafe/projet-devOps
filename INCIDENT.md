# Rapport d'incident — compromission potentielle de `requests`

## Résumé

- **Nature :** incident potentiel de chaîne d'approvisionnement logicielle.
- **Déclencheur :** annonce officielle indiquant qu'une version de `requests` est compromise (ex: version: 2.59.0).
- **Périmètre concerné :** l'application MiniShop, qui déclare `requests` dans `app/requirements.in` et l'utilise dans l'endpoint `/fetch` de `app/app.py`.

## 1. Détecter

Vérification de la version `request ` installée dans les dépendances via `pip-audit`, `pip show requests` :

```bash
#version en local
pip-audit -r app/requirements.txt --desc      
pip show requests | grep Version    
#version de l'image docker
docker run --rm minishop pip show requests    
```

## 2. Évaluation de l'exposition

Afin d'évaluer l'exposition on répond à quatre questions grâce aux outils d'inspections suivants:

- **1. Qui utilise la lib ?**
```bash
 pipdeptree -r -p requests
```
- **2. Quelle version, et où ?** 
- `pip freeze | grep requests` : la version installée dans votre environnement.
- `grep requests app/requirements.txt` : la version écrite dans le fichier verrouillé.
- `docker run --rm minishop pip show requests` : la version dans l’image déployée.

- **3. Depuis quand ?**
```bash 
git log -S'requests==2.99.0' -- app/requirements.txt
```
- **4. Quel code est atteignable ?** 
Oui ! `/fetch` appelle `requests` : l'application est bien exposée.

## 3. Confinement

Il faut geler les déploiements dans la CI et bloquer la version fautive. On arrete l'image docker, on coupe le réseau tout en gardant la trace des logs. On ne désactive pas `security.yml`, il sert à valider le correctif: 

```bash
docker stop minishop                          # arrêter le service
docker network disconnect bridge minishop     # couper l'egress (exfiltration)
docker logs minishop > evidence.log           # garder une trace avant tout nettoyage
```

## 4. Corriger

On met à jour la dépendance : On modifie le fichier de dépendances pour forcer une version sûre de requests.

Commandes appliquées :

```Bash
pip-compile --upgrade-package requests --generate-hashes requirements.in
pip-audit -r requirements.txt --strict        # doit être propre

```
Finalement, on valide la correction : On lance les scripts de vérification et des tests pour s'assurer qu'aucune régression n'a été introduite. Ainsi, on met à jour notre image docker :
```Bash
pytest -q tests                               
docker build --pull --no-cache -t minishop app/
trivy image --severity HIGH,CRITICAL minishop
```

## 5. Rotation des secrets

Si la librairie est malveillante,tout secret accessible au processus est considéré comme compromis: elle s'exécute avec les mêmes droits que l'application.

**L'ordre compte.** On contient d'abord (Partie Confinement), on corrige ensuite , et on fait tourner les secrets seulement après. Sinon les nouveaux secrets seraient volés à leur tour par le même code.

### Étapes de rotation

1. On génère une nouvelle clé `SECRET_KEY`, on la met dans `.env` , puis on redémarre l'application: 
   ```bash
   python -c "import secrets; print(secrets.token_urlsafe(48))"
   ```

2. On supprime l'ancienne clé chez le fournisseur cloud ou API, puis on en crée une nouvelle avec des droits minimaux.

3. On change le mot de passe de la base de donnée, puis on met à jour la configuration de l'application.

4.On révoque les anciens jetons et secrets de la CI, en recréer de nouveaux, puis on les remet dans les secrets du dépôt.

5. On impose une réinitialisation des mots de passe des utilisateurs si la base a pu être lue. Les hashes argon2 ralentissent l'attaque mais ne l'empêchent pas.


On vérifie ensuite si l'ancienne clé ne fonctionne plus, en vérifiant que les anciennes sessions sont refusées. On inspecte ainsi q'aucun secret n'est présent dans le dépôt (`gitleaks detect --source . --no-banner`), et que les logs réseau ne montrent plus de connexion sortante inhabituelle.

## 6. Retour d'expérience

### Ce qui nous protège déjà

* **`pip-audit` quotidien et Dependabot :** Permettent une détection rapide des dépendances vulnérables ou compromises.
* **SBOM (Software Bill of Materials) :** Permet de répondre à la question « sommes-nous concernés ? » en une seule commande.
* **Principe de moindre privilège dans le conteneur :** Utilisation d'un utilisateur non-root et d'une image de base `python:3.12-slim` épinglée pour limiter la surface d'attaque et les dégâts potentiels.
* **Sécurisation de la CI/CD :** Actions GitHub épinglées par SHA et restriction des privilèges (`permissions: contents: read`) pour éviter que la CI ne serve de vecteur d'attaque.


### Limite technique identifiée

L'utilisation de `--require-hashes` dans `pip` n'aurait pas empêché cet incident. Le contrôle par hash garantit l'intégrité d'un fichier contre les altérations, mais ne protège pas contre une nouvelle version intentionnellement corrompue.

### Ce qui aurait aidé à prévenir ou atténuer l'incident

* Définir des versions exactes pour toutes les dépendances directes et transitives.
* Différer de quelques jours l'installation des nouvelles versions afin de laisser le temps à la communauté de détecter d'éventuelles publications malveillantes.
* Épingler l'intégralité des outils et actions de CI par leur commit SHA.
* Privilégier des jetons de publication à durée de vie courte plutôt que des jetons d'accès permanents.

### Plan d'actions d'amélioration

| Action | Raison / Objectif |
|---|---|
| **Filtrer le réseau sortant du conteneur** | Bloquer l'exfiltration de données même si une bibliothèque tierce est piégée. |
| **Instaurer un délai d'adoption des dépendances** | Attendre la validation par la communauté avant d'ingérer une mise à jour mineure/patch. |
| **Définir un SLA (Service Level Agreement) de correction CI** | Structurer une réponse rapide et prévisible face aux vulnérabilités critiques. |

