from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Cree ou met a jour un compte superutilisateur, de facon idempotente."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("email")
        parser.add_argument("password")

    def handle(self, *args, **options):
        User = get_user_model()
        user, created = User.objects.get_or_create(
            username=options["username"],
            defaults={"email": options["email"]},
        )
        user.email = options["email"]
        user.is_staff = True
        user.is_superuser = True
        user.set_password(options["password"])
        user.save()
        action = "cree" if created else "mis a jour"
        self.stdout.write(f"Superutilisateur {action} : {user.username}")
