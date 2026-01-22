from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = 'Deprecated: Teachers group setup runs in AppConfig post_migrate'

    def handle(self, *args, **options):
        self.stdout.write(self.style.WARNING(
            "Deprecated: Teachers group setup now runs automatically after migrations. "
            "No changes were applied by this command."
        ))
