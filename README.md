# Memora

Memora est une plateforme web permettant aux invites d'un evenement de partager instantanement leurs photos et videos grace a un QR Code unique.

> Revivez votre evenement a travers les yeux de vos invites.

## Etat actuel

Etapes realisees du MVP :

- projet Django `memora` initialise ;
- apps de base creees : `accounts`, `events`, `uploads`, `dashboard`, `core`, `processing` ;
- configuration par variables d'environnement ;
- configuration PostgreSQL via `DATABASE_URL` ;
- structure `templates/`, `static/` et `media/` ;
- page d'accueil simple et mobile-first ;
- modeles principaux crees : `Event`, `EventType`, `UploadCategoryTemplate`, `UploadCategory`, `GuestUpload`, `GeneratedMovie` ;
- types d'evenements gerables dans l'admin ;
- modeles de moments geres par type d'evenement dans l'admin Memora ;
- categories de moments copiees automatiquement dans chaque evenement ;
- admin Django minimal pour inspecter les donnees ;
- inscription et connexion organisateur ;
- interface organisateur minimale pour lister, creer, modifier et consulter un evenement ;
- page publique evenement accessible via un lien prive `/e/<slug>/<access_key>/` ;
- generation automatique du QR code pointant vers le lien prive de la page publique ;
- code d'acces invite optionnel par evenement, valide une fois par session ;
- affichage et telechargement du QR code cote organisateur ;
- upload invite sans compte via `/e/<slug>/<access_key>/souvenir/` ;
- choix obligatoire du moment ;
- validations simples : taille, format, limites par session, IP et evenement ;
- limitation anti-spam avec delai minimal configurable entre deux envois ;
- dashboard media evenement avec compteurs photos/videos, repartition par moment et derniers souvenirs ;
- medias acceptes automatiquement, avec rejet/restauration manuel par l'organisateur en cas de probleme ;
- telechargement ZIP des medias d'un evenement, organises par moments ;
- videos invitees limitees a 10 secondes avec verification serveur via FFprobe ;
- generation automatique d'un premier film souvenir avec FFmpeg, planifiable a J+1 12h ;
- analyse automatique des medias avec scores qualite, emotion, energie et selection film IA-ready ;
- integration preparee pour Google Video Intelligence, Runway, montage final `runway_final` et choix musical avec ducking de voix ;
- suppression automatique preparee : les medias sont marques supprimes 7 jours apres la date de l'evenement.

Les fonctionnalites de suppression physique des fichiers et traitement media avance asynchrone ne sont pas encore implementees.

## Installation locale

```bash
python -m venv .venv
.venv\Scripts\activate
python -m pip install -r requirements.txt
copy .env.example .env
```

Mettre ensuite a jour `.env` avec les informations PostgreSQL locales :

```env
DATABASE_URL=postgres://memora:memora@localhost:5432/memora
DJANGO_SECRET_KEY=change-me
DJANGO_DEBUG=True
DJANGO_ALLOWED_HOSTS=localhost,127.0.0.1
```

Puis lancer les migrations Django initiales :

```bash
python manage.py migrate
python manage.py runserver
```

## Film souvenir

La generation du film souvenir necessite FFmpeg et FFprobe disponibles dans le `PATH` ou configures via :

```env
MEMORA_FFMPEG_BINARY=ffmpeg
MEMORA_FFPROBE_BINARY=ffprobe
MEMORA_MAX_VIDEO_UPLOAD_DURATION_SECONDS=10
MEMORA_MOVIE_IMAGE_DURATION_SECONDS=3
MEMORA_MOVIE_VIDEO_MAX_SECONDS=10
MEMORA_MOVIE_MAX_DURATION_SECONDS=600
MEMORA_MOVIE_AUTOGENERATE_HOUR=12
MEMORA_MOVIE_VIDEO_ENCODER=libx264
MEMORA_MOVIE_WIDTH=1280
MEMORA_MOVIE_HEIGHT=720
MEMORA_MOVIE_PHOTO_TARGET_RATIO=0.20
MEMORA_MOVIE_MIN_PHOTO_COUNT_WITH_VIDEOS=2
MEMORA_MOVIE_MAX_CONSECUTIVE_VIDEOS_BEFORE_PHOTO=3
MEMORA_MOVIE_MUSIC_DIR=assets/music
MEMORA_MOVIE_MUSIC_VOLUME=0.22
MEMORA_MOVIE_VOICE_VOLUME=1.0
MEMORA_MOVIE_DUCKED_MUSIC_VOLUME=0.08
```

Memora selectionne automatiquement les videos acceptees les mieux scorees, ajoute aussi les meilleures photos dans le montage, limite le film final a 10 minutes, puis ignore les medias rejetes ou supprimes. Les videos invitees restent limitees a 10 secondes chacune pour garder un rythme vif.

Quand photos et videos sont disponibles, Memora reserve une part cible du film aux photos (`MEMORA_MOVIE_PHOTO_TARGET_RATIO`, 20% par defaut), garantit quelques photos fortes si elles existent, puis les place entre les videos pour creer des respirations emotionnelles sans transformer le film en diaporama.

La bibliotheque musicale versionnee vit dans `assets/music/` par defaut, donc elle est disponible en local et dans l'image Docker de production. Si une bibliotheque musicale existe dans `MEMORA_MOVIE_MUSIC_DIR`, Memora choisit automatiquement une piste selon l'ambiance dominante (`romantic_cinematic`, `cinematic_emotional`, `joyful_party`, `warm_lounge`, `elegant_warm`). Quand la video finale contient de la voix, FFmpeg ajoute la musique en fond et la baisse automatiquement sous les voix avec `sidechaincompress`.

## Analyse IA des medias

Memora cree une analyse par media accepte avec :

- score technique ;
- score emotion ;
- score energie ;
- score final pour le film ;
- luminosite, nettete, tags et resume court.

Le moteur par defaut est local et heuristique : il extrait une frame video avec FFmpeg, analyse l'image avec Pillow, puis score les moments forts.

Pour activer Google Video Intelligence :

```env
MEMORA_AI_ANALYSIS_PROVIDER=google_video_intelligence_v1
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_ENABLED=True
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_LANGUAGE=fr-FR
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_TIMEOUT_SECONDS=180
MEMORA_GOOGLE_VIDEO_INTELLIGENCE_USE_LATEST_MODEL=True
GOOGLE_APPLICATION_CREDENTIALS=/chemin/vers/service-account.json
# Ou sur Render, plus pratique pour une variable secrete :
GOOGLE_APPLICATION_CREDENTIALS_B64=<service-account-json-encode-en-base64>
```

Le provider Google enrichit le scoring avec labels video, detection de plans, contenu explicite, visages et transcription. Les voix et visages boostent les moments humains ; le contenu explicite penalise fortement la selection.

Pour preparer le rendu premium Runway :

```env
MEMORA_RUNWAY_ENABLED=True
RUNWAYML_API_SECRET=...
MEMORA_RUNWAY_WORKFLOW_ID=...
MEMORA_RUNWAY_WORKFLOW_VERSION=2026-06
MEMORA_RUNWAY_VIDEO_MODEL=gen4_aleph
MEMORA_RUNWAY_VIDEO_RATIO=1280:720
MEMORA_RUNWAY_MAX_ENHANCED_CLIPS=3
MEMORA_RUNWAY_TASK_TIMEOUT_SECONDS=900
MEMORA_RUNWAY_FALLBACK_TO_FFMPEG=True
```

Memora stocke un plan de montage structure dans `GeneratedMovie.edit_decision_data` avec clips selectionnes, mood musical, strategie audio et payload Runway.

Modes de rendu :

- `ffmpeg` : Memora assemble le film localement avec FFmpeg.
- `runway` : Memora ameliore certains clips video avec Runway, puis assemble le film final avec FFmpeg.
- `runway_final` : Memora envoie un brief complet et les medias selectionnes a un workflow Runway publie pour produire le film souvenir final. FFmpeg reste utilise ensuite pour garantir le badge permanent, l'encodage final et le fallback.

Le mode cible produit est `runway_final`. Il necessite `MEMORA_RUNWAY_WORKFLOW_ID` et des credits API Runway actifs. Si Runway echoue et que `MEMORA_RUNWAY_FALLBACK_TO_FFMPEG=True`, Memora revient au montage FFmpeg pour ne pas bloquer la livraison du film.

Le workflow Runway doit accepter un objet `inputs` contenant le brief, les contraintes, la liste des medias selectionnes, le mood musical et la strategie audio.

Analyser les medias en attente :

```bash
python manage.py analyze_pending_media
```

Mode worker :

```bash
python manage.py analyze_pending_media --loop --sleep 30
```

Le worker de film analyse aussi les medias manquants avant le montage, afin que la selection automatique utilise les scores disponibles.

Planifier les films dus a lancer via cron, worker planifie ou ordonnanceur :

```bash
python manage.py generate_scheduled_movies
```

Traiter les films en attente avec le worker local :

```bash
python manage.py process_pending_movies
```

Verifier sans modifier :

```bash
python manage.py generate_scheduled_movies --dry-run
python manage.py process_pending_movies --dry-run
```

En developpement, `generate_scheduled_movies --process-now` permet de planifier et traiter dans la meme execution.

## Stockage media

Par defaut, Memora stocke les medias localement dans `MEDIA_ROOT`.

```env
MEMORA_STORAGE_BACKEND=local
```

Pour utiliser un stockage S3 compatible comme AWS S3, Cloudflare R2 ou Backblaze B2 :

```env
MEMORA_STORAGE_BACKEND=s3
MEMORA_S3_ACCESS_KEY_ID=...
MEMORA_S3_SECRET_ACCESS_KEY=...
MEMORA_S3_BUCKET_NAME=memora
MEMORA_S3_ENDPOINT_URL=https://<cloudflare-account-id>.r2.cloudflarestorage.com
MEMORA_S3_REGION_NAME=auto
MEMORA_S3_ADDRESSING_STYLE=path
MEMORA_S3_QUERYSTRING_AUTH=True
```

En local, le bucket Cloudflare R2 `memora` est valide avec le backend Django Storage.

Le montage video reste compatible avec le stockage cloud : les medias sont lus via Django Storage, copies temporairement en local pour FFmpeg, puis le film final est reenregistre dans le storage configure.

## Production

Memora est pret pour un premier deploiement Docker avec Gunicorn, WhiteNoise et FFmpeg :

```bash
docker build -t memora .
docker run --env-file .env -p 8000:8000 memora
```

Avant le premier demarrage production, appliquer les migrations :

```bash
python manage.py migrate
```

Process attendus :

```bash
gunicorn memora.wsgi:application --bind 0.0.0.0:8000 --workers 3 --timeout 180
python manage.py process_pending_movies --loop --sleep 30
python manage.py analyze_pending_media --loop --sleep 30
python manage.py generate_scheduled_movies
```

Un Blueprint Render est disponible dans `render.yaml`. Il prepare un service web Django, un worker de montage, deux cron jobs et une base PostgreSQL Render. Les details de configuration sont dans `docs/render-deployment.md`.

En production Render, le stockage media doit utiliser S3 compatible (`MEMORA_STORAGE_BACKEND=s3`) afin que le web, le worker et les cron jobs partagent les uploads et les films generes.

En production, definir au minimum :

```env
DJANGO_DEBUG=False
DJANGO_SECRET_KEY=...
DJANGO_ALLOWED_HOSTS=memora.example.com
DJANGO_CSRF_TRUSTED_ORIGINS=https://memora.example.com
DJANGO_SECURE_SSL_REDIRECT=True
DJANGO_SESSION_COOKIE_SECURE=True
DJANGO_CSRF_COOKIE_SECURE=True
DJANGO_SECURE_HSTS_SECONDS=31536000
DATABASE_URL=postgres://...
```

## Nettoyage des medias

Les medias invites expirent 7 jours apres la date de l'evenement. La commande suivante marque les medias expires avec `is_deleted=True` sans supprimer physiquement les fichiers :

```bash
python manage.py cleanup_expired_media
```

Verifier sans modifier :

```bash
python manage.py cleanup_expired_media --dry-run
```

## Securite et maintenance production

Points de securite couverts par le MVP :

- les liens publics utilisent un `public_access_key` aleatoire distinct du slug ;
- les pages organisateur restent protegees par compte ;
- la page publique du film n'est visible que lorsque le film est termine ;
- les invites sont limites a 5 souvenirs par appareil, avec limites IP/evenement en plus ;
- les extensions, types MIME, taille, magic bytes et duree video sont controles cote serveur ;
- les images invitees sont ouvertes avec Pillow, validees, puis reencodees en JPEG/PNG/WebP propre avant stockage ;
- le code invite optionnel est protege par un throttling IP/session/evenement avec delai progressif ;
- l'IP client utilisee pour les quotas ignore `X-Forwarded-For` par defaut et ne le lit que si `MEMORA_TRUST_X_FORWARDED_FOR=True` ;
- les videos invitees sont limitees a 10 secondes.

Commandes utiles en exploitation :

```bash
python manage.py process_pending_movies --loop --sleep 30
python manage.py process_event_movie <event_id> --include-processing
python manage.py generate_scheduled_movies
python manage.py notify_ready_movies
python manage.py cleanup_expired_media --dry-run
python manage.py backup_database --output backups/memora.dump
```

La sauvegarde utilise `pg_dump`. Le dossier `backups/` est ignore par Git pour eviter de versionner une sauvegarde locale.

## PostgreSQL local projet

Pour eviter de dependre du PostgreSQL systeme, un cluster local de developpement peut etre lance depuis `.postgres/data` sur le port `55432`.

Demarrer PostgreSQL :

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D "D:\memora\.postgres\data" -l "D:\memora\.postgres\postgres.log" -o "-p 55432" start
```

Arreter PostgreSQL :

```powershell
& "C:\Program Files\PostgreSQL\17\bin\pg_ctl.exe" -D "D:\memora\.postgres\data" stop
```

La configuration locale attendue dans `.env` est :

```env
DATABASE_URL=postgres://memora@localhost:55432/memora
```

## Structure

```text
memora/
  settings.py
  urls.py
accounts/
events/
uploads/
dashboard/
core/
processing/
templates/
static/
media/
```
