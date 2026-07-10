from time import sleep

from django.core.management.base import BaseCommand

from processing.analysis import (
    analyze_pending_media,
    create_missing_media_analysis_jobs,
    get_pending_media_analyses,
    get_uploads_needing_analysis,
)


class Command(BaseCommand):
    help = "Analyse les medias invites en attente pour alimenter la selection IA du film."

    def add_arguments(self, parser):
        parser.add_argument(
            "--limit",
            type=int,
            default=20,
            help="Nombre maximum de medias a analyser pendant cette execution.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche les medias a analyser sans lancer l'analyse.",
        )
        parser.add_argument(
            "--loop",
            action="store_true",
            help="Continue a surveiller les medias en attente.",
        )
        parser.add_argument(
            "--sleep",
            type=int,
            default=30,
            help="Secondes entre deux passages quand --loop est actif.",
        )

    def handle(self, *args, **options):
        while True:
            self.process_once(options)
            if not options["loop"]:
                return
            sleep(options["sleep"])

    def process_once(self, options):
        if options["dry_run"]:
            uploads = get_uploads_needing_analysis(limit=options["limit"])
            analyses = get_pending_media_analyses(limit=options["limit"])
            if not uploads and not analyses:
                self.stdout.write("Aucun media a analyser.")
                return
            for upload in uploads:
                self.stdout.write(f"[dry-run] Media #{upload.pk} - {upload.original_filename}")
            for analysis in analyses:
                self.stdout.write(f"[dry-run] Media #{analysis.upload_id} - {analysis.upload.original_filename}")
            return

        create_missing_media_analysis_jobs(limit=options["limit"])
        analyses = get_pending_media_analyses(limit=options["limit"])
        if not analyses:
            self.stdout.write("Aucun media a analyser.")
            return

        processed_analyses = analyze_pending_media(limit=options["limit"])
        for analysis in processed_analyses:
            self.stdout.write(
                f"Media #{analysis.upload_id} - {analysis.upload.original_filename}: "
                f"{analysis.get_status_display().lower()} ({analysis.movie_score:.1f})."
            )
