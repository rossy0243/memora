"""Exploitation : battements de coeur des taches planifiees, detection des problemes, alertes.

Pourquoi : les taches (films, livre d'or, nettoyage) attrapent leurs propres erreurs et marquent
le film « en echec » sans faire echouer le processus : Render ne voit rien et personne n'est
prevenu. Ici, chaque probleme reel (film en echec, film bloque, film en retard, tache arretee,
sauvegarde absente) declenche UN e-mail a l'equipe, repete au plus toutes les 12 h tant qu'il dure.
"""
import logging
from collections import namedtuple
from datetime import timedelta

from django.conf import settings
from django.core.mail import send_mail
from django.utils import timezone

from .models import OperationalState, SiteConfiguration

logger = logging.getLogger(__name__)

FILM_CRON = "heartbeat:film-cron"
MAINTENANCE_CRON = "heartbeat:maintenance-cron"
BACKUP = "heartbeat:backup"

ALERT_COOLDOWN = timedelta(hours=12)
PENDING_STUCK_AFTER = timedelta(minutes=45)  # la tache passe toutes les 15 min
PROCESSING_STUCK_AFTER = timedelta(minutes=75)  # un rendu met a jour sa progression en continu
OVERDUE_AFTER = timedelta(hours=2)  # film du au-dela de l'heure prevue et jamais cree
FAILURE_WINDOW = timedelta(days=14)
FILM_CRON_MAX_AGE = timedelta(minutes=45)
MAINTENANCE_MAX_AGE = timedelta(hours=36)
BACKUP_MAX_AGE = timedelta(hours=36)

Issue = namedtuple("Issue", "key title detail")


# -- battements de coeur ------------------------------------------------------------------------
def beat(name, now=None):
    now = now or timezone.now()
    OperationalState.objects.update_or_create(key=name, defaults={"value": {"at": now.isoformat()}})


def last_beat(name):
    state = OperationalState.objects.filter(key=name).first()
    if not state:
        return None
    try:
        return timezone.datetime.fromisoformat(state.value["at"])
    except (KeyError, ValueError, TypeError):
        return None


def beat_age(name, now=None):
    seen = last_beat(name)
    return None if seen is None else (now or timezone.now()) - seen


def film_processing_is_alive(now=None, within=timedelta(minutes=20)):
    """Un film en cours de rendu qui bouge encore prouve que la tache tourne (rendu long)."""
    from guestbook.models import GuestBookMovie
    from processing.models import GeneratedMovie

    since = (now or timezone.now()) - within
    return (
        GeneratedMovie.objects.filter(status=GeneratedMovie.Status.PROCESSING, updated_at__gte=since).exists()
        or GuestBookMovie.objects.filter(status=GuestBookMovie.Status.PROCESSING, updated_at__gte=since).exists()
    )


def film_cron_status(now=None):
    """(vivant, phrase) : la tache des films tourne-t-elle encore ? Sert a la page de sante."""
    now = now or timezone.now()
    age = beat_age(FILM_CRON, now)
    if age is not None and age <= FILM_CRON_MAX_AGE:
        return True, f"tache des films vue il y a {int(age.total_seconds() // 60)} min"
    if film_processing_is_alive(now):
        return True, "un rendu est en cours"
    if age is None:
        return False, "tache des films jamais vue"
    return False, f"tache des films silencieuse depuis {int(age.total_seconds() // 3600)} h {int(age.total_seconds() % 3600 // 60)} min"


# -- detection -----------------------------------------------------------------------------------------
def collect_issues(now=None, watch_film_cron=False, watch_maintenance=False):
    from guestbook.models import GuestBookMovie
    from processing.models import GeneratedMovie
    from processing.services import get_scheduled_movie_events

    now = now or timezone.now()
    issues = []

    # Films en echec (et pas de film reussi depuis).
    for movie in GeneratedMovie.objects.filter(status=GeneratedMovie.Status.FAILED, created_at__gte=now - FAILURE_WINDOW).select_related("event"):
        if movie.event.generated_movies.filter(status=GeneratedMovie.Status.COMPLETED).exists():
            continue
        issues.append(Issue(
            f"movie-failed:{movie.pk}", f"Film en échec — {movie.event.title}",
            f"Le film de « {movie.event.title} » (événement {movie.event_id}) a échoué.\nMessage : {movie.progress_message}\nDétail : {(movie.error_logs or '')[:600]}\n"
            f"À faire : ouvrir l'événement dans l'admin et relancer le film (« Générer le film maintenant »). "
            f"Les souvenirs ne sont retirés qu'après {settings.MEMORA_MEDIA_MASK_WAIT_FOR_MOVIE_DAYS} jours de plus tant que le film n'existe pas.",
        ))

    # Films bloques : jamais repris, ou plus aucune progression.
    for movie in GeneratedMovie.objects.filter(
        status__in=[GeneratedMovie.Status.PENDING, GeneratedMovie.Status.PROCESSING]
    ).select_related("event"):
        limit = PENDING_STUCK_AFTER if movie.status == GeneratedMovie.Status.PENDING else PROCESSING_STUCK_AFTER
        if now - movie.updated_at > limit:
            minutes = int((now - movie.updated_at).total_seconds() // 60)
            issues.append(Issue(
                f"movie-stuck:{movie.pk}", f"Film bloqué — {movie.event.title}",
                f"Le film de « {movie.event.title} » est « {movie.get_status_display()} » sans avancer depuis {minutes} min "
                f"({movie.progress_percent:.0f} %, {movie.progress_message}).\nÀ faire : vérifier la tâche « memora-schedule-movies » sur Render (journaux), puis relancer le film.",
            ))

    # Films en retard : evenement du, mais aucun film n'a jamais ete cree.
    for event in get_scheduled_movie_events(now - OVERDUE_AFTER):
        issues.append(Issue(
            f"movie-overdue:{event.pk}", f"Film en retard — {event.title}",
            f"Le film de « {event.title} » (événement {event.pk}) aurait dû être lancé il y a plus de 2 h et n'existe pas.\n"
            "À faire : vérifier la tâche « memora-schedule-movies » sur Render, ou lancer le film à la main depuis l'admin.",
        ))

    # Livre d'or.
    for montage in GuestBookMovie.objects.filter(status=GuestBookMovie.Status.FAILED, updated_at__gte=now - FAILURE_WINDOW).select_related("event"):
        issues.append(Issue(
            f"guestbook-failed:{montage.pk}", f"Montage du livre d'or en échec — {montage.event.title}",
            f"Le montage vidéo du livre d'or de « {montage.event.title} » a échoué.\nDétail : {(montage.error_message or '')[:600]}\nÀ faire : le relancer depuis la page « Livre d'or » de l'événement.",
        ))
    for montage in GuestBookMovie.objects.filter(status__in=[GuestBookMovie.Status.PENDING, GuestBookMovie.Status.PROCESSING]).select_related("event"):
        limit = PENDING_STUCK_AFTER if montage.status == GuestBookMovie.Status.PENDING else PROCESSING_STUCK_AFTER
        if now - montage.updated_at > limit:
            issues.append(Issue(
                f"guestbook-stuck:{montage.pk}", f"Montage du livre d'or bloqué — {montage.event.title}",
                f"Le montage de « {montage.event.title} » n'avance plus depuis {int((now - montage.updated_at).total_seconds() // 60)} min.",
            ))

    # Taches arretees : la premiere observation ne vaut pas alerte (registre encore vide).
    if watch_film_cron:
        alive, sentence = film_cron_status(now)
        if last_beat(FILM_CRON) is None:
            beat(FILM_CRON, now - FILM_CRON_MAX_AGE)  # amorce, sans alerte
        elif not alive:
            issues.append(Issue("film-cron-silent", "La tâche des films ne tourne plus", f"{sentence}.\nÀ faire : ouvrir « memora-schedule-movies » sur Render (dernière exécution, journaux)."))
    if watch_maintenance:
        for name, limit, label in ((MAINTENANCE_CRON, MAINTENANCE_MAX_AGE, "nettoyage quotidien"), (BACKUP, BACKUP_MAX_AGE, "sauvegarde de la base")):
            age = beat_age(name, now)
            if age is None:
                beat(name, now)  # amorce
            elif age > limit:
                issues.append(Issue(f"{name}-silent", f"Tâche silencieuse : {label}", f"Dernière exécution il y a {int(age.total_seconds() // 3600)} h.\nÀ faire : ouvrir « memora-cleanup-expired-media » sur Render (journaux)."))
    return issues


# -- alertes ---------------------------------------------------------------------------------------------
def alert_recipients():
    if settings.MEMORA_ALERT_EMAILS:
        return list(settings.MEMORA_ALERT_EMAILS)
    email = SiteConfiguration.current().effective_support_email
    return [email] if email else []


def send_alert(issue, now=None):
    """Envoie l'alerte, au plus une fois par ALERT_COOLDOWN et par probleme. True si envoyee."""
    now = now or timezone.now()
    recipients = alert_recipients()
    if not recipients:
        logger.warning("Alert not sent (no recipient) key=%s", issue.key)
        return False
    key = f"alert:{issue.key}"
    state = OperationalState.objects.filter(key=key).first()
    if state:
        try:
            if now - timezone.datetime.fromisoformat(state.value["sent_at"]) < ALERT_COOLDOWN:
                return False
        except (KeyError, ValueError, TypeError):
            pass
    base = (settings.MEMORA_PUBLIC_BASE_URL or "").rstrip("/")
    body = f"{issue.detail}\n\nAdmin : {base}/admin/\nJournal des alertes : ce message est repete au plus toutes les 12 h tant que le problème dure.\n"
    try:
        send_mail(f"[Memora] Alerte : {issue.title}", body, settings.DEFAULT_FROM_EMAIL, recipients, fail_silently=False)
    except Exception:  # noqa: BLE001 - un e-mail en echec ne doit jamais casser la tache
        logger.exception("Alert email failed key=%s", issue.key)
        return False
    OperationalState.objects.update_or_create(key=key, defaults={"value": {"sent_at": now.isoformat(), "title": issue.title}})
    logger.warning("Alert sent key=%s title=%s", issue.key, issue.title)
    return True


def run_checks(now=None, **kwargs):
    """Detecte puis alerte. Ne leve jamais : c'est un garde-fou, pas une etape critique."""
    try:
        issues = collect_issues(now, **kwargs)
        sent = sum(1 for issue in issues if send_alert(issue, now))
        return issues, sent
    except Exception:  # noqa: BLE001
        logger.exception("Operations check failed")
        return [], 0
