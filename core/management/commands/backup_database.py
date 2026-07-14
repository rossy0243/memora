from pathlib import Path
import os
import shutil
import subprocess

from django.conf import settings
from django.core.management.base import BaseCommand, CommandError
from django.utils import timezone


class Command(BaseCommand):
    help = "Cree une sauvegarde PostgreSQL avec pg_dump."

    def add_arguments(self, parser):
        parser.add_argument(
            "--output",
            help="Chemin du fichier de sauvegarde. Par defaut: backups/memora-YYYYmmdd-HHMMSS.dump.",
        )
        parser.add_argument(
            "--format",
            choices=["custom", "plain"],
            default="custom",
            help="Format pg_dump. custom est recommande pour restaurer avec pg_restore.",
        )
        parser.add_argument(
            "--dry-run",
            action="store_true",
            help="Affiche la destination sans lancer pg_dump.",
        )

    def handle(self, *args, **options):
        database = settings.DATABASES["default"]
        if "postgresql" not in database.get("ENGINE", ""):
            raise CommandError("backup_database ne supporte que PostgreSQL.")

        pg_dump = shutil.which("pg_dump")
        if not pg_dump:
            raise CommandError("pg_dump est introuvable. Installez les outils PostgreSQL.")

        output_path = self._output_path(options["output"])
        command = self._pg_dump_command(pg_dump, database, output_path, options["format"])

        if options["dry_run"]:
            self.stdout.write(f"[dry-run] Sauvegarde prevue: {output_path}")
            return

        output_path.parent.mkdir(parents=True, exist_ok=True)
        env = os.environ.copy()
        password = database.get("PASSWORD")
        if password:
            env["PGPASSWORD"] = password

        result = subprocess.run(command, env=env, capture_output=True, text=True, check=False)
        if result.returncode != 0:
            message = (result.stderr or result.stdout or "pg_dump a echoue.").strip()
            raise CommandError(message)

        self.stdout.write(self.style.SUCCESS(f"Sauvegarde creee: {output_path}"))

    def _output_path(self, raw_output):
        if raw_output:
            return Path(raw_output).expanduser().resolve()

        stamp = timezone.now().strftime("%Y%m%d-%H%M%S")
        return (settings.BASE_DIR / "backups" / f"memora-{stamp}.dump").resolve()

    def _pg_dump_command(self, pg_dump, database, output_path, dump_format):
        command = [
            pg_dump,
            "--format",
            "custom" if dump_format == "custom" else "plain",
            "--no-owner",
            "--no-privileges",
            "--file",
            str(output_path),
        ]

        if database.get("HOST"):
            command.extend(["--host", database["HOST"]])
        if database.get("PORT"):
            command.extend(["--port", str(database["PORT"])])
        if database.get("USER"):
            command.extend(["--username", database["USER"]])
        command.append(database["NAME"])
        return command
