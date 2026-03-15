from django.contrib.auth import get_user_model
from django.core.management.base import BaseCommand
from django.db import transaction

from digitmileapi.models import (
    Classroom,
    ClassroomWeekStats,
    ReplayArchive,
    Run,
    RunStatistics,
    School,
    SpecialTileTrigger,
    Student,
    StudentWeekBackCardUsageStats,
    StudentWeekCardFamilyStats,
    StudentWeekChainLengthStats,
    StudentWeekConditionalStats,
    StudentWeekForeachContextStats,
    StudentWeekHotspotStats,
    StudentWeekLevelStats,
    StudentWeekNumberChoiceStats,
    StudentWeekSpecialTileStats,
    StudentWeekStats,
    Teacher,
    TeacherSchoolAssignment,
    TurnEvent,
    WeeklyCompactionRun,
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
            # Delete in order of dependencies (children first)
            ReplayArchive.objects.all().delete()
            SpecialTileTrigger.objects.all().delete()
            TurnEvent.objects.all().delete()
            Run.objects.all().delete()
            RunStatistics.objects.all().delete()
            StudentWeekBackCardUsageStats.objects.all().delete()
            StudentWeekCardFamilyStats.objects.all().delete()
            StudentWeekChainLengthStats.objects.all().delete()
            StudentWeekConditionalStats.objects.all().delete()
            StudentWeekForeachContextStats.objects.all().delete()
            StudentWeekHotspotStats.objects.all().delete()
            StudentWeekLevelStats.objects.all().delete()
            StudentWeekNumberChoiceStats.objects.all().delete()
            StudentWeekSpecialTileStats.objects.all().delete()
            StudentWeekStats.objects.all().delete()
            ClassroomWeekStats.objects.all().delete()
            WeeklyCompactionRun.objects.all().delete()
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
            "Replay archives": ReplayArchive.objects.count(),
            "Special tile triggers": SpecialTileTrigger.objects.count(),
            "Turn events": TurnEvent.objects.count(),
            "Runs (new)": Run.objects.count(),
            "Run statistics (legacy)": RunStatistics.objects.count(),
            "Student weekly stats": StudentWeekStats.objects.count(),
            "Student weekly level stats": StudentWeekLevelStats.objects.count(),
            "Student weekly hotspot stats": StudentWeekHotspotStats.objects.count(),
            "Student weekly special tile stats": StudentWeekSpecialTileStats.objects.count(),
            "Student weekly chain stats": StudentWeekChainLengthStats.objects.count(),
            "Student weekly card family stats": StudentWeekCardFamilyStats.objects.count(),
            "Student weekly conditional stats": StudentWeekConditionalStats.objects.count(),
            "Student weekly back card stats": StudentWeekBackCardUsageStats.objects.count(),
            "Student weekly foreach stats": StudentWeekForeachContextStats.objects.count(),
            "Student weekly number choice stats": StudentWeekNumberChoiceStats.objects.count(),
            "Classroom weekly stats": ClassroomWeekStats.objects.count(),
            "Weekly compaction runs": WeeklyCompactionRun.objects.count(),
            "Students": Student.objects.count(),
            "Classrooms": Classroom.objects.count(),
            "Teacher-school assignments": TeacherSchoolAssignment.objects.count(),
            "Teacher users": User.objects.filter(teacher_profile__isnull=False).count(),
            "Teachers": Teacher.objects.count(),
            "Schools": School.objects.count(),
        }
