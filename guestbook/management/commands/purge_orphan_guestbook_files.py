from django.core.management.base import BaseCommand

from guestbook.models import GuestBookMovie


class Command(BaseCommand):
    help = (
        "Supprime du stockage les anciens fichiers de montage du livre d'or que plus "
        "aucun montage ne reference (restes de regenerations anterieures au nettoyage "
        "automatique). Sans --apply : liste seulement, ne supprime rien."
    )

    def add_arguments(self, parser):
        parser.add_argument("--apply", action="store_true", help="Supprime reellement les fichiers.")

    def handle(self, *args, **options):
        found = 0
        size_total = 0
        for movie in GuestBookMovie.objects.select_related("event"):
            # Un montage en cours n'a pas encore enregistre ses fichiers : on n'y touche pas.
            if movie.status == GuestBookMovie.Status.PROCESSING or not movie.event.slug:
                continue
            storage = GuestBookMovie._meta.get_field("final_file").storage
            directory = f"events/{movie.event.slug}/livre-dor/montage"
            referenced = {
                name.rsplit("/", 1)[-1]
                for name in (movie.final_file.name if movie.final_file else "", movie.light_file.name if movie.light_file else "")
                if name
            }
            try:
                _, files = storage.listdir(directory)
            except (FileNotFoundError, OSError):
                continue
            for filename in sorted(files):
                if filename in referenced or not filename.startswith("livre-dor-"):
                    continue
                path = f"{directory}/{filename}"
                try:
                    size = storage.size(path)
                except Exception:
                    size = 0
                found += 1
                size_total += size
                self.stdout.write(f"{'SUPPRIME' if options['apply'] else 'orphelin '} {path} ({size / 1e6:.1f} Mo)")
                if options["apply"]:
                    storage.delete(path)
            self.stdout.write(f"  evenement {movie.event_id} : conserves = {sorted(referenced) or '-'}")

        verb = "supprimes" if options["apply"] else "trouves (rien supprime, relancer avec --apply)"
        self.stdout.write(f"{found} fichier(s) orphelin(s) {verb}, {size_total / 1e6:.0f} Mo.")
