from django.core.management.base import BaseCommand

from digitmileapi.apps import create_teacher_group


class Command(BaseCommand):
    help = "Create/update the Teachers group permissions."

    def handle(self, *args, **options):
        create_teacher_group(sender=None)
        self.stdout.write(
            self.style.SUCCESS("Teachers group permissions were created/updated.")
        )
