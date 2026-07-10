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
MEMORA_MOVIE_MAX_DURATION_SECONDS=300
MEMORA_MOVIE_AUTOGENERATE_HOUR=12
MEMORA_MOVIE_VIDEO_ENCODER=libx264
MEMORA_MOVIE_WIDTH=1280
MEMORA_MOVIE_HEIGHT=720
```

Memora selectionne automatiquement les videos acceptees les mieux scorees, limite le film final a 5 minutes, puis ignore les medias rejetes ou supprimes.

## Analyse IA des medias

Memora cree une analyse par media accepte avec :

- score technique ;
- score emotion ;
- score energie ;
- score final pour le film ;
- luminosite, nettete, tags et resume court.

Le moteur actuel est local et heuristique : il extrait une frame video avec FFmpeg, analyse l'image avec Pillow, puis score les moments forts. Il est concu pour etre remplace ou enrichi par une vraie IA vision externe sans changer le flux produit.

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
MEMORA_S3_BUCKET_NAME=memora-media
MEMORA_S3_ENDPOINT_URL=https://...
MEMORA_S3_REGION_NAME=...
MEMORA_S3_ADDRESSING_STYLE=auto
MEMORA_S3_QUERYSTRING_AUTH=True
```

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
