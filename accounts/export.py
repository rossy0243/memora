"""Export RGPD : toutes les donnees d'un compte, en une archive ZIP streamee.

Contenu : `compte.json` a la racine (identite, profils, retraits, commissions),
puis un dossier par evenement avec ses metadonnees (`evenement.json`), les
medias des invites, les messages du livre d'or et les films generes.

Les identifiants techniques des invites (IP, user-agent, cle de session) ne
sont pas inclus : ce sont des donnees des invites, pas de l'organisateur.
"""
import json
from zipfile import ZIP_DEFLATED, ZipFile

from django.utils import timezone

from processing.services import _StreamingZipBuffer, _clean_name


def account_export_filename(user):
    return f"Memora_donnees_{_clean_name(user.get_username())}.zip"


def _dt(value):
    return value.isoformat() if value else None


def _account_payload(user):
    from accounts.models import CommissionLedger, OrganizerProfile, PayoutRequest

    profile = OrganizerProfile.objects.filter(user=user).first()
    agent = getattr(user, "agent_profile", None)

    return {
        "exporte_le": timezone.now().isoformat(),
        "compte": {
            "identifiant": user.get_username(),
            "email": user.email,
            "prenom": user.first_name,
            "nom": user.last_name,
            "inscrit_le": _dt(user.date_joined),
            "derniere_connexion": _dt(user.last_login),
        },
        "profil_organisateur": None
        if profile is None
        else {
            "est_ambassadeur": profile.is_ambassador,
            "palier": profile.tier,
            "code_parrainage": profile.referral_code,
            "parraine_par": profile.referred_by.get_username() if profile.referred_by_id else None,
            "cree_le": _dt(profile.created_at),
        },
        "profil_agent": None
        if agent is None
        else {"telephone": agent.phone_number, "cree_le": _dt(agent.created_at)},
        "demandes_de_retrait": [
            {
                "montant": str(payout.amount),
                "devise": payout.currency,
                "statut": payout.status,
                "methode": payout.method,
                "demande_le": _dt(payout.requested_at),
                "traite_le": _dt(payout.processed_at),
            }
            for payout in PayoutRequest.objects.filter(beneficiary=user).order_by("requested_at")
        ],
        "commissions": [
            {
                "montant": str(entry.amount),
                "devise": entry.currency,
                "statut": entry.status,
                "cree_le": _dt(entry.created_at),
            }
            for entry in CommissionLedger.objects.filter(beneficiary=user).order_by("created_at")
        ],
    }


def _event_payload(event):
    uploads = list(
        event.guest_uploads.filter(is_deleted=False, media_purged=False)
        .select_related("category")
        .order_by("uploaded_at", "pk")
    )
    messages = list(
        event.guestbook_messages.filter(media_purged=False).order_by("created_at", "pk")
    )
    movie = event.generated_movies.order_by("-created_at").first()
    montage = getattr(event, "guestbook_movie", None)

    films = []
    if movie:
        for kind, field in (("final", movie.final_file), ("integrale", movie.full_file), ("teaser", movie.teaser_file)):
            if field:
                films.append({"type": kind, "fichier": field.name.rsplit("/", 1)[-1]})
    if montage and montage.final_file:
        films.append({"type": "livre_dor", "fichier": montage.final_file.name.rsplit("/", 1)[-1]})

    return {
        "titre": event.title,
        "slug": event.slug,
        "type": event.event_type.label if event.event_type_id else None,
        "date": event.event_date.isoformat() if event.event_date else None,
        "lieu": event.location,
        "statut_paiement": event.payment_status,
        "cree_le": _dt(event.created_at),
        "retention_jours": event.media_retention_days,
        "medias": [
            {
                "fichier": u.media_file.name.rsplit("/", 1)[-1],
                "type": u.media_type,
                "nom_original": u.original_filename,
                "recu_le": _dt(u.uploaded_at),
                "moment": u.category.label if u.category_id else None,
                "moderation": u.moderation_status,
            }
            for u in uploads
        ],
        "livre_dor": [
            {
                "fichier": m.media_file.name.rsplit("/", 1)[-1],
                "de_la_part_de": m.guest_name,
                "enregistre_le": _dt(m.created_at),
            }
            for m in messages
        ],
        "films": films,
    }, uploads, messages, movie, montage


def iter_account_export_zip_chunks(user):
    from events.models import Event

    buffer = _StreamingZipBuffer()
    with ZipFile(buffer, "w", ZIP_DEFLATED) as archive:
        archive.writestr(
            "compte.json",
            json.dumps(_account_payload(user), ensure_ascii=False, indent=2),
        )
        yield from buffer.drain()

        events = (
            Event.objects.filter(organizer=user)
            .select_related("event_type")
            .order_by("event_date", "pk")
        )
        for event in events:
            root = f"evenements/{_clean_name(event.slug or str(event.pk))}"
            payload, uploads, messages, movie, montage = _event_payload(event)

            archive.writestr(
                f"{root}/evenement.json",
                json.dumps(payload, ensure_ascii=False, indent=2),
            )
            yield from buffer.drain()

            used = set()
            for upload in uploads:
                if not upload.media_file:
                    continue
                name = _unique(f"{root}/medias/{upload.media_file.name.rsplit('/', 1)[-1]}", used)
                yield from _write_file(archive, buffer, upload.media_file, name)

            for message in messages:
                if not message.media_file:
                    continue
                name = _unique(f"{root}/livre-dor/{message.media_file.name.rsplit('/', 1)[-1]}", used)
                yield from _write_file(archive, buffer, message.media_file, name)

            for field in _film_fields(movie, montage):
                name = _unique(f"{root}/films/{field.name.rsplit('/', 1)[-1]}", used)
                yield from _write_file(archive, buffer, field, name)

    yield from buffer.drain()


def _film_fields(movie, montage):
    fields = []
    if movie:
        fields += [f for f in (movie.final_file, movie.full_file, movie.teaser_file) if f]
    if montage and montage.final_file:
        fields.append(montage.final_file)
    return fields


def _unique(path, used):
    if path not in used:
        used.add(path)
        return path
    stem, _, ext = path.rpartition(".")
    index = 2
    while True:
        candidate = f"{stem}-{index}.{ext}" if stem else f"{path}-{index}"
        if candidate not in used:
            used.add(candidate)
            return candidate
        index += 1


def _write_file(archive, buffer, field_file, archive_path):
    try:
        field_file.open("rb")
    except Exception:
        return
    try:
        with archive.open(archive_path, "w") as destination:
            for chunk in field_file.chunks():
                destination.write(chunk)
                yield from buffer.drain()
    finally:
        field_file.close()
    yield from buffer.drain()
