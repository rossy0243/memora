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
- modeles principaux crees : `Event`, `EventType`, `UploadCategory`, `GuestUpload`, `GeneratedMovie` ;
- types d'evenements gerables dans l'admin ;
- categories de moments creees par evenement et gerables dans l'admin ;
- admin Django minimal pour inspecter les donnees ;
- inscription et connexion organisateur ;
- interface organisateur minimale pour lister, creer, modifier et consulter un evenement ;
- page publique evenement accessible via `/e/<slug>/` ;
- generation automatique du QR code pointant vers la page publique ;
- affichage et telechargement du QR code cote organisateur ;
- upload invite sans compte via `/e/<slug>/souvenir/` ;
- choix obligatoire du moment ;
- validations simples : taille, format, limites par session, IP et evenement ;
- dashboard media evenement avec compteurs photos/videos, repartition par moment et derniers souvenirs ;
- telechargement ZIP des medias d'un evenement, organises par moments.

Les fonctionnalites de suppression automatique et traitement media avance ne sont pas encore implementees.

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
