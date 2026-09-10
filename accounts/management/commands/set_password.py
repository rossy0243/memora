from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand, CommandError


class Command(BaseCommand):
    help = "Definit le mot de passe d'un compte existant (sans toucher aux droits)."

    def add_arguments(self, parser):
        parser.add_argument("username")
        parser.add_argument("password")

    def handle(self, *args, **options):
        User = get_user_model()
        try:
            user = User.objects.get(username=options["username"])
        except User.DoesNotExist as exc:
            raise CommandError(f"Compte introuvable : {options['username']}") from exc
        user.set_password(options["password"])
        user.save(update_fields=["password"])
        self.stdout.write(
            f"Mot de passe mis a jour : {user.username} "
            f"(staff={user.is_staff}, superuser={user.is_superuser}, "
            f"agent={hasattr(user, 'agent_profile')})"
        )
