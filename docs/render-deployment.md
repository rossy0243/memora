# Deploiement Render

Memora est prepare pour Render avec un Blueprint `render.yaml` a la racine du depot.

Le Blueprint cree :

- `memora-web` : service web Django/Gunicorn ;
- `memora-movie-worker` : worker long-running pour traiter les films en attente ;
- `memora-schedule-movies` : cron horaire qui declenche les films dus, dont J+1 a 12h cote application ;
- `memora-cleanup-expired-media` : cron quotidien pour marquer les medias expires ;
- `memora-db` : base PostgreSQL Render.

## Secrets a renseigner dans Render

Render demandera les valeurs marquees `sync: false` au premier import du Blueprint :

```text
RUNWAYML_API_SECRET
MEMORA_RUNWAY_WORKFLOW_ID
MEMORA_S3_ACCESS_KEY_ID
MEMORA_S3_SECRET_ACCESS_KEY
```

Le bucket Cloudflare R2 `memora`, l'endpoint R2, la region `auto`, le domaine custom vide et l'adressage `path` sont deja declares dans `render.yaml`.

Pour Cloudflare R2, utiliser :

```text
MEMORA_S3_BUCKET_NAME=memora
MEMORA_S3_ENDPOINT_URL=https://<cloudflare-account-id>.r2.cloudflarestorage.com
MEMORA_S3_REGION_NAME=auto
MEMORA_S3_ADDRESSING_STYLE=path
MEMORA_S3_QUERYSTRING_AUTH=True
```

## Pourquoi S3 est obligatoire en production

Le service web recoit les uploads, puis le worker lit ces fichiers pour analyser et monter le film. Sur Render, le stockage local d'un service n'est pas partage avec les autres services et ne doit pas servir de stockage media durable. Le Blueprint force donc `MEMORA_STORAGE_BACKEND=s3`.

Backblaze B2, Cloudflare R2 et AWS S3 conviennent.

## Taille des instances de montage

Le montage FFmpeg a besoin de plus de memoire que le web Django. Le Blueprint met donc `memora-movie-worker` et `memora-schedule-movies` en plan `standard` pour disposer de 2 GB RAM. En dessous, Render peut arreter le process pendant la generation sans laisser d'erreur applicative exploitable.

## Activation Google Video Intelligence

Ajouter le JSON du compte de service dans Render sous forme Base64 :

```text
MEMORA_AI_ANALYSIS_PROVIDER=google_video_intelligence_v1
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_ENABLED=True
GOOGLE_APPLICATION_CREDENTIALS_B64=<service-account-json-encode-en-base64>
```

Au demarrage, Memora materialise ce secret dans un fichier temporaire et renseigne `GOOGLE_APPLICATION_CREDENTIALS` pour la librairie Google.

## Activation Runway

Le Blueprint configure Memora en mode cible :

```text
MEMORA_MOVIE_RENDER_PROVIDER=runway_final
MEMORA_RUNWAY_ENABLED=True
```

Dans ce mode, Memora envoie a Runway un brief complet de film souvenir avec les medias selectionnes, le mood musical, la strategie audio et les contraintes de rendu. Runway produit le master final, puis FFmpeg reste utilise pour garantir le badge permanent, l'encodage final et le fallback.

Secrets requis :

```text
RUNWAYML_API_SECRET=<cle-api-runway>
MEMORA_RUNWAY_WORKFLOW_ID=<workflow-runway-publie>
```

Le compte Runway doit avoir des credits API actifs. Sans credits, Runway peut refuser les uploads ou les workflows avec une erreur `403`.

Si `MEMORA_RUNWAY_WORKFLOW_ID` est absent ou si Runway echoue, Memora revient automatiquement au montage FFmpeg lorsque `MEMORA_RUNWAY_FALLBACK_TO_FFMPEG=True`.

Modes disponibles :

- `ffmpeg` : montage local complet par FFmpeg ;
- `runway` : amelioration de certains clips par Runway, montage final par FFmpeg ;
- `runway_final` : montage final confie a un workflow Runway publie, finition et fallback par FFmpeg.

## Notes de securite

Les cles API doivent rester dans Render et dans `.env` local uniquement. Elles ne doivent jamais etre commitees.

Si une cle a ete collee dans une conversation ou un ticket, il faut la regenerer avant un lancement public.
