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
MEMORA_S3_ACCESS_KEY_ID
MEMORA_S3_SECRET_ACCESS_KEY
MEMORA_S3_BUCKET_NAME
MEMORA_S3_ENDPOINT_URL
MEMORA_S3_REGION_NAME
MEMORA_S3_CUSTOM_DOMAIN
```

`MEMORA_S3_CUSTOM_DOMAIN` peut rester vide si le bucket S3 compatible n'utilise pas de domaine public dedie.

## Pourquoi S3 est obligatoire en production

Le service web recoit les uploads, puis le worker lit ces fichiers pour analyser et monter le film. Sur Render, le stockage local d'un service n'est pas partage avec les autres services et ne doit pas servir de stockage media durable. Le Blueprint force donc `MEMORA_STORAGE_BACKEND=s3`.

Backblaze B2, Cloudflare R2 et AWS S3 conviennent.

## Activation Google Video Intelligence

La production Render garde pour l'instant l'analyse locale active :

```text
MEMORA_AI_ANALYSIS_PROVIDER=local_heuristic_v1
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_ENABLED=False
```

Quand le compte de service Google sera pret, ajouter le fichier d'identifiants comme secret Render, definir `GOOGLE_APPLICATION_CREDENTIALS` vers ce chemin, puis passer :

```text
MEMORA_AI_ANALYSIS_PROVIDER=google_video_intelligence_v1
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_ENABLED=True
```

## Notes de securite

Les cles API doivent rester dans Render et dans `.env` local uniquement. Elles ne doivent jamais etre commitees.

Si une cle a ete collee dans une conversation ou un ticket, il faut la regenerer avant un lancement public.
