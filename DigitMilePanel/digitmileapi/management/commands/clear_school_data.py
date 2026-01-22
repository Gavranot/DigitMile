from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from digitmileapi.models import (
    Classroom,
    RunStatistics,
    School,
    Student,
    Teacher,
    TeacherSchoolAssignment,
)


class Command(BaseCommand):
    help = "Clear school, teacher, classroom, student, and statistics data"

    def add_arguments(self, parser):
        parser.add_argument(
            "--yes",
            action="store_true",
            help="Skip confirmation prompt and delete data immediately",
        )

    def handle(self, *args, **options):
        counts = self._get_counts()
        total_records = sum(counts.values())

        if total_records == 0:
            self.stdout.write(self.style.SUCCESS("No matching data found to delete."))
            return

        self.stdout.write(self.style.WARNING("This will permanently delete:"))
        for label, count in counts.items():
            self.stdout.write(f"- {label}: {count}")

        if not options["yes"]:
            confirmation = input('Type "yes" to continue: ').strip().lower()
            if confirmation != "yes":
                self.stdout.write(self.style.WARNING("Deletion cancelled."))
                return

        self.stdout.write(self.style.WARNING("Deleting data..."))

        User = get_user_model()

        with transaction.atomic():
            RunStatistics.objects.all().delete()
            Student.objects.all().delete()
            Classroom.objects.all().delete()
            TeacherSchoolAssignment.objects.all().delete()
            User.objects.filter(teacher_profile__isnull=False).delete()
            Teacher.objects.all().delete()
            School.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Data cleared successfully."))

    def _get_counts(self):
        User = get_user_model()
        return {
            "Run statistics": RunStatistics.objects.count(),
            "Students": Student.objects.count(),
            "Classrooms": Classroom.objects.count(),
            "Teacher-school assignments": TeacherSchoolAssignment.objects.count(),
            "Teacher users": User.objects.filter(teacher_profile__isnull=False).count(),
            "Teachers": Teacher.objects.count(),
            "Schools": School.objects.count(),
        }
