# Déployer OpenTranscribe sur Scaleway avec Terraform

Ce tutoriel est un runbook reproductible pour déployer OpenTranscribe MCP dans le projet
Scaleway **FBO Holding**. Il utilise le module maintenu dans `infra/scaleway` et évite les
opérations manuelles dans la console, sauf pour créer l'identité de déploiement et consulter
les journaux.

**Référence de version :** documentation Scaleway consultée le 8 septembre 2026, Terraform
1.16.1 et provider Scaleway 2.82.x verrouillé par le dépôt. Les contrôles locaux de cette PR
ne créent aucune ressource dans le compte Scaleway.

La [documentation de référence](../deploy-scaleway.md) explique les choix d'architecture,
les limites et le stockage temporaire. Ce runbook se concentre sur les commandes d'une
installation concrète.

## Résultat attendu

| Paramètre | Valeur |
| --- | --- |
| Projet Scaleway | `FBO Holding` |
| Project ID | `ee5aacbd-4915-4c83-9524-47a14c669816` |
| Région | `fr-par` |
| Registry | `open-transcribe-registry` |
| Namespace Serverless | `open-transcribe-serverless` |
| Conteneur | `open-transcribe-mcp` |
| Endpoint MCP | `https://<endpoint-scaleway>/mcp` |
| Stockage des résultats | désactivé au premier déploiement |

Le Project ID identifie la cible mais n'authentifie aucune requête. Les Access Keys, Secret
Keys, jetons MCP et clés fournisseur restent des secrets et ne doivent jamais être commités.

## 1. Ouvrir l'environnement de développement

Le devcontainer fournit déjà Python 3, `uv`, Docker-in-Docker, Terraform 1.16.1 et GitHub CLI.
Depuis VS Code :

1. clone le dépôt et ouvre son dossier ;
2. exécute **Dev Containers: Reopen in Container** ;
3. attends la fin de `.devcontainer/post-create.sh` ;
4. vérifie les outils :

```bash
terraform version
docker version
docker buildx version
uv --version
```

Terraform doit afficher `1.16.1`. Aucune clé Scaleway n'est copiée dans l'image du
devcontainer : elles seront injectées uniquement dans le terminal courant.

Sans VS Code, installe Terraform 1.16.1, Docker avec Buildx, Python 3 et `uv`, puis exécute les
mêmes commandes depuis la racine du dépôt.

## 2. Créer une identité IAM de déploiement

Dans la [console Scaleway](https://console.scaleway.com/), sélectionne **FBO Holding**, puis :

1. ouvre **IAM > Applications** ;
2. crée l'application `open-transcribe-deployer` ;
3. crée une politique attachée à cette application ;
4. ajoute une règle limitée au projet **FBO Holding** avec :
   - `ContainerRegistryFullAccess` ;
   - `ContainersFullAccess` ;
5. si le stockage S3 optionnel sera activé, ajoute `ObjectStorageFullAccess` sur le projet ;
6. pour permettre au module de créer l'identité S3 optionnelle, ajoute au niveau de
   l'Organisation :
   - `IAMApplicationManager` ;
   - `IAMPolicyManager` ;
7. génère une clé API avec une expiration courte et conserve ses deux valeurs dans un
   gestionnaire de secrets.

Les droits IAM d'Organisation ne sont pas nécessaires lorsque `enable_result_store = false`.
Ils sont puissants : ne les accorde pas à l'identité d'exécution du serveur et révoque la clé
de déploiement lorsqu'elle n'est plus utilisée. Consulte les
[permission sets Scaleway](https://www.scaleway.com/en/docs/iam/reference-content/permission-sets/).

Dans le terminal du devcontainer :

```bash
export SCW_ACCESS_KEY="<ACCESS_KEY>"
read -rsp "Scaleway Secret Key: " SCW_SECRET_KEY
export SCW_SECRET_KEY
export SCW_DEFAULT_PROJECT_ID="ee5aacbd-4915-4c83-9524-47a14c669816"
export SCW_DEFAULT_REGION="fr-par"
```

La saisie de la Secret Key est masquée et évite de l'enregistrer dans l'historique du shell.
Le provider accepte ces variables sans exécuter `scw init`.

## 3. Configurer les variables Terraform

Crée une copie locale ignorée par Git :

```bash
cp infra/scaleway/terraform.tfvars.example infra/scaleway/terraform.tfvars
chmod 600 infra/scaleway/terraform.tfvars
openssl rand -hex 32
```

La dernière commande génère le jeton d'accès MCP. Place-le, avec une clé de fournisseur, dans
`infra/scaleway/terraform.tfvars` :

```hcl
project_id = "ee5aacbd-4915-4c83-9524-47a14c669816"
region     = "fr-par"
name_prefix = "open-transcribe"

# Utiliser une version ou un identifiant de commit immuable, jamais latest.
image_tag = "1.1.0"

environment_variables = {
  OT_DEFAULT_PROVIDER    = "microsoft"
  OT_DEFAULT_MODEL       = "MAI-Transcribe-2"
  OT_MICROSOFT__ENDPOINT = "https://<RESOURCE>.cognitiveservices.azure.com"
}

secret_environment_variables = {
  OT_SECURITY__BEARER_TOKEN = "<JETON_MCP_ALEATOIRE>"
  OT_MICROSOFT__API_KEY     = "<CLE_MICROSOFT>"
}

enable_result_store = false

tags = [
  "environment=production",
  "owner=fbo-holding",
]
```

Pour ElevenLabs ou Groq, remplace la configuration Microsoft par les variables exactes de
`.env.example` et consulte [Providers and capabilities](../providers.md). Le module refuse
une configuration sans jeton MCP ou sans clé fournisseur.

!!! warning "Les secrets sont présents dans le state"

    `terraform.tfvars` et le state sont ignorés par Git, mais ce n'est pas du chiffrement. Les
    secrets fournis au conteneur peuvent être présents dans le state Terraform. Garde le state
    sur un disque chiffré pour ce premier déploiement. Pour une exploitation partagée, migre-le
    vers un backend distant chiffré et strictement limité avant de confier le déploiement à une
    CI.

## 4. Initialiser et contrôler le module

Depuis la racine du dépôt :

```bash
terraform -chdir=infra/scaleway init
terraform -chdir=infra/scaleway fmt -check -recursive
terraform -chdir=infra/scaleway validate
```

`terraform init` doit sélectionner la version inscrite dans
`infra/scaleway/.terraform.lock.hcl`. Ne mets pas le provider à jour pendant ce déploiement.

Le module utilise les attributs actuels de l'API v1 : `image`, `memory_limit_bytes`,
`local_storage_limit_bytes` et le déploiement automatique. Les anciens attributs
`registry_image`, `memory_limit`, `local_storage_limit` et `deploy` sont dépréciés dans le
[provider Scaleway](https://registry.terraform.io/providers/scaleway/scaleway/latest/docs/resources/container).

## 5. Créer d'abord le Registry privé

L'image doit exister avant la création du Serverless Container. Applique uniquement la
ressource Registry lors du bootstrap :

```bash
terraform -chdir=infra/scaleway plan \
  -target=scaleway_registry_namespace.this \
  -out=registry.tfplan

terraform -chdir=infra/scaleway apply registry.tfplan
```

L'utilisation ponctuelle de `-target` est intentionnelle ici. Les déploiements suivants
utiliseront toujours un plan complet.

Récupère les références calculées par Terraform :

```bash
REGISTRY_ENDPOINT="$(terraform -chdir=infra/scaleway output -raw registry_endpoint)"
IMAGE_REFERENCE="$(terraform -chdir=infra/scaleway output -raw image_reference)"
```

## 6. Construire et publier l'image

Connecte Docker au Registry avec la Secret Key de l'identité de déploiement :

```bash
printf '%s' "$SCW_SECRET_KEY" | \
  docker login "$REGISTRY_ENDPOINT" --username nologin --password-stdin
```

Construis explicitement une image AMD64, même si la machine de développement utilise une
puce ARM :

```bash
docker buildx build \
  --platform linux/amd64 \
  --tag "$IMAGE_REFERENCE" \
  --push \
  .
```

Contrôle sa publication :

```bash
docker buildx imagetools inspect "$IMAGE_REFERENCE"
```

Scaleway exige actuellement `linux/amd64` et recommande une image de moins de 1 Go pour
réduire les cold starts. Voir les
[limites Serverless Containers](https://www.scaleway.com/en/docs/serverless-containers/reference-content/containers-limitations/).

## 7. Planifier et déployer toute l'infrastructure

Crée un plan complet et lis attentivement la liste des ressources :

```bash
terraform -chdir=infra/scaleway plan -out=open-transcribe.tfplan
terraform -chdir=infra/scaleway show open-transcribe.tfplan
```

Le plan doit notamment créer :

- un namespace Serverless Containers ;
- un conteneur public au niveau Scaleway, mais protégé par le bearer token OpenTranscribe ;
- une startup probe et une liveness probe sur `/healthz` ;
- une configuration HTTPS-only ;
- des variables secrètes masquées par Scaleway.

Applique le plan enregistré :

```bash
terraform -chdir=infra/scaleway apply open-transcribe.tfplan
```

Le conteneur reste public au niveau de la passerelle Scaleway parce que les clients MCP
envoient un header `Authorization: Bearer`, pas le header propriétaire `X-Auth-Token` des
conteneurs privés Scaleway. Le middleware OpenTranscribe protège uniquement `/mcp` ; les
probes `/healthz` et `/readyz` restent accessibles sans exposer de transcript.

## 8. Vérifier le déploiement

Récupère les URL :

```bash
CONTAINER_ENDPOINT="$(terraform -chdir=infra/scaleway output -raw container_endpoint)"
MCP_ENDPOINT="$(terraform -chdir=infra/scaleway output -raw mcp_endpoint)"
```

Teste la vie du processus et la présence du fournisseur :

```bash
curl --fail --show-error "$CONTAINER_ENDPOINT/healthz"
curl --fail --show-error "$CONTAINER_ENDPOINT/readyz"
```

Les réponses attendues ressemblent à :

```json
{"status":"ok"}
```

```json
{"status":"ready","configured_providers":["microsoft"]}
```

Vérifie ensuite que `/mcp` refuse une requête sans jeton :

```bash
curl --output /dev/null --silent --write-out '%{http_code}\n' \
  --request POST \
  --header 'Content-Type: application/json' \
  --data '{"jsonrpc":"2.0","id":1,"method":"ping"}' \
  "$MCP_ENDPOINT"
```

Le statut attendu est `401`.

Enfin, charge le même jeton que dans `terraform.tfvars` sans l'inscrire dans l'historique et
lance le client d'exemple avec l'enregistrement synthétique public :

```bash
read -rsp "OpenTranscribe bearer token: " OT_MCP_TOKEN
uv run python examples/transcribe.py \
  --server "$MCP_ENDPOINT" \
  --token "$OT_MCP_TOKEN"
unset OT_MCP_TOKEN
```

Ce test consomme l'API du fournisseur configuré. N'utilise ensuite que des enregistrements
que tu es autorisé à transmettre et à transcrire.

## 9. Activer le stockage temporaire, si nécessaire

Le premier déploiement garde `enable_result_store = false`, ce qui correspond à la politique
de non-rétention par défaut. Active S3 uniquement si les réponses doivent être récupérées en
plusieurs chunks ou survivre à un scale-to-zero.

Ajoute dans `terraform.tfvars` :

```hcl
enable_result_store = true

secret_environment_variables = {
  OT_SECURITY__BEARER_TOKEN      = "<JETON_MCP_ALEATOIRE>"
  OT_MICROSOFT__API_KEY          = "<CLE_MICROSOFT>"
  OT_RESULT_STORE__CURSOR_SECRET = "<AUTRE_SECRET_ALEATOIRE>"
}
```

Vérifie alors que l'identité de déploiement possède les droits Object Storage et IAM décrits
à l'étape 2, puis exécute un nouveau `terraform plan` complet. Terraform créera un bucket
privé, une règle de cycle de vie TTL, une identité d'exécution dédiée et une bucket policy
limitée au préfixe des transcripts.

Le bucket est une option de stockage temporaire, pas une archive. L'application applique le
TTL précis et la règle de cycle de vie Scaleway sert de filet de sécurité.

## 10. Mettre à jour ou revenir en arrière

Pour une mise à jour :

1. choisis un nouveau `image_tag` immuable ;
2. modifie `terraform.tfvars` ;
3. recalcule `IMAGE_REFERENCE` ;
4. construis et pousse l'image ;
5. exécute un plan complet puis applique-le ;
6. rejoue les contrôles de l'étape 8.

Pour revenir en arrière, remets le tag précédent dans `terraform.tfvars`, puis planifie et
applique. Scaleway ne fournit pas de rollback automatique des Serverless Containers : garder
les tags précédents est donc volontaire.

## 11. Exploitation

Dans **Cockpit > Grafana**, surveille au minimum :

- les réponses HTTP 5xx ;
- la durée des requêtes ;
- la mémoire et le CPU ;
- les redémarrages et cold starts ;
- le nombre d'instances ;
- les volumes réseau.

Les logs ne doivent contenir ni transcript, ni phrase hint, ni credential, ni query string
d'URL signée. Consulte le
[guide de supervision Scaleway](https://www.scaleway.com/en/docs/serverless-containers/how-to/monitor-container/)
et configure une alerte de facturation pour FBO Holding.

## Dépannage rapide

| Symptôme | Vérification |
| --- | --- |
| Image refusée | l'image annoncée par `imagetools inspect` doit être `linux/amd64` |
| Échec lors du premier apply | le Registry et le tag doivent exister avant le plan complet |
| `/readyz` renvoie 503 | endpoint ou clé du fournisseur absent ou invalide |
| `/mcp` renvoie 401 | bearer token absent ou différent de `OT_SECURITY__BEARER_TOKEN` |
| Les chunks disparaissent | activer le result store S3 ; ne pas utiliser le store mémoire en production |
| Un apply redemande tous les secrets | vérifier le fichier local et l'accès au state utilisé |

## Checklist de fin

- [ ] l'identité de déploiement est dédiée et temporaire ;
- [ ] le Project ID est celui de FBO Holding ;
- [ ] le plan Terraform a été relu avant application ;
- [ ] l'image est versionnée et construite pour `linux/amd64` ;
- [ ] `/healthz` et `/readyz` répondent 200 ;
- [ ] `/mcp` sans bearer token répond 401 ;
- [ ] le client MCP authentifié voit les cinq outils attendus ;
- [ ] aucune donnée sensible n'apparaît dans Cockpit ;
- [ ] le state est stocké sur un support chiffré et n'est pas commité ;
- [ ] une alerte de facturation est configurée.
