"""
Django management command to seed the database with mock data.

Usage:
    python manage.py seed_database                    # Default (medium preset)
    python manage.py seed_database --preset low       # Low amount of data
    python manage.py seed_database --preset medium    # Medium amount (default)
    python manage.py seed_database --preset high      # Production-like amount
    python manage.py seed_database --clear            # Clear existing data first
"""

import json
import random
import re
import string
import uuid
from datetime import date, datetime, timezone as dt_timezone
from pathlib import Path

from django.core.management.base import BaseCommand
from django.contrib.auth.models import Group, User
from digitmileapi.models import (
    School,
    Teacher,
    TeacherSchoolAssignment,
    Classroom,
    Student,
    RunStatistics,
    Run,
    TurnEvent,
    SpecialTileTrigger,
)


# Presets for different data volumes
PRESETS = {
    "low": {
        "schools": 5,
        "teachers": 5,
        "min_students": 100,
        "min_runs": 1000,
        "min_legacy_statistics": 500,
    },
    "medium": {
        "schools": 25,
        "teachers": 15,
        "min_students": 1500,
        "min_runs": 10000,
        "min_legacy_statistics": 5000,
    },
    "high": {
        "schools": 50,
        "teachers": 100,
        "min_students": 15000,
        "min_runs": 100000,
        "min_legacy_statistics": 20000,
    },
}


class Command(BaseCommand):
    help = "Seed the database with mock data for demonstration purposes"
    BOARD_SIZE = 60
    START_END_TILE_TYPE = 0
    NORMAL_TILE_TYPES = [1, 2, 3, 6]
    SPECIAL_TILE_DELTAS = {4: -4, 5: 4}
    LEVEL_RANGE = range(1, 7)

    # Macedonian-style names and locations for realistic data
    FIRST_NAMES = [
        "Aleksandar",
        "Ana",
        "Andrej",
        "Angela",
        "Boris",
        "Bojana",
        "Darko",
        "Daniela",
        "Elena",
        "Filip",
        "Goran",
        "Gordana",
        "Igor",
        "Ivana",
        "Jovan",
        "Jelena",
        "Kiril",
        "Kristina",
        "Lazar",
        "Lidija",
        "Marko",
        "Marija",
        "Nikola",
        "Natalija",
        "Oliver",
        "Olivera",
        "Petar",
        "Petra",
        "Riste",
        "Rosica",
        "Stefan",
        "Sofija",
        "Todor",
        "Tanja",
        "Viktor",
        "Vesna",
        "Zoran",
        "Zorica",
        "Martin",
        "Maja",
        "David",
        "Dimitar",
        "Emilija",
        "Eva",
        "Hristijan",
        "Hristina",
        "Ilija",
        "Irena",
        "Jasmina",
        "Jana",
        "Kliment",
        "Katerina",
        "Ljupco",
        "Ljupka",
        "Metodija",
        "Milica",
        "Naum",
        "Natasa",
        "Ognen",
        "Olga",
        "Pavle",
        "Paulina",
        "Robert",
        "Radica",
        "Simeon",
        "Sanja",
        "Trajko",
        "Teodora",
        "Vlado",
        "Valentina",
        "Zdravko",
        "Zaklina",
    ]

    LAST_NAMES = [
        "Angelovski",
        "Atanasovski",
        "Bogdanovski",
        "Cvetanovski",
        "Dimitrovski",
        "Efremovski",
        "Filipovski",
        "Georgievski",
        "Hristovski",
        "Ivanovski",
        "Jankulovski",
        "Kocevski",
        "Lazarovski",
        "Mancevski",
        "Nikolovski",
        "Ognjenovski",
        "Petrevski",
        "Ristevski",
        "Stojkovski",
        "Trajkovski",
        "Velkovski",
        "Zdravkovski",
        "Arsovski",
        "Boskovski",
        "Celeski",
        "Damjanski",
        "Eftimovski",
        "Fidanoski",
        "Gligoroski",
        "Hadzi-Nikolovski",
        "Ilievski",
        "Joveski",
        "Kostovski",
        "Levkovski",
        "Mitreski",
        "Naumovski",
        "Ognenovski",
        "Pavlovski",
        "Radevski",
        "Saveski",
        "Tasevski",
        "Uzunovski",
        "Vasilevski",
        "Zafirov",
        "Andonovski",
    ]

    MUNICIPALITIES = [
        "Centar",
        "Karpos",
        "Aerodrom",
        "Kisela Voda",
        "Gazi Baba",
        "Butel",
        "Cair",
        "Gjorce Petrov",
        "Saraj",
        "Suto Orizari",
    ]

    REGIONS = [
        "Skopje",
        "Bitola",
        "Kumanovo",
        "Prilep",
        "Tetovo",
        "Veles",
        "Stip",
        "Ohrid",
        "Gostivar",
        "Strumica",
        "Kavadarci",
        "Kocani",
        "Kicevo",
        "Struga",
        "Radovis",
    ]

    SCHOOL_TYPES = [
        "OU",
        "SOU",
        "OSOU",
        "SOUG",
        "OU",  # Primary (OU) more common
    ]

    SCHOOL_NAME_PARTS = [
        "Sveti Kiril i Metodij",
        "Goce Delcev",
        "Braka Miladinovci",
        "Kuzman Josifoski Pitu",
        "Nikola Karev",
        "Krste Misirkov",
        "Kliment Ohridski",
        "Naum Ohridski",
        "Vasil Glavinov",
        "Dimitar Vlahov",
        "Koco Racin",
        "Strasho Pindzur",
        "Blazhe Koneski",
        "Vera Ciriviri Trena",
        "Jane Sandanski",
        "Dame Gruev",
        "Petar Pop Arsov",
        "Gjorgji Sugarev",
        "Josip Broz Tito",
        "Aco Sopov",
        "Vuk Karadzic",
        "Aleksandar Makedonski",
        "Hristo Tatarcev",
        "Boris Trajkovski",
    ]

    CLASSROOM_PREFIXES = ["1", "2", "3", "4", "5", "6", "7", "8", "9"]
    CLASSROOM_SUFFIXES = ["a", "b", "v", "g", "d"]

    def add_arguments(self, parser):
        parser.add_argument(
            "--clear",
            action="store_true",
            help="Clear existing seeded data before adding new data",
        )
        parser.add_argument(
            "--preset",
            type=str,
            choices=["low", "medium", "high"],
            default="medium",
            help="Preset for data volume: low, medium (default), or high",
        )
        parser.add_argument(
            "--schools",
            type=int,
            help="Override number of schools to create",
        )
        parser.add_argument(
            "--teachers",
            type=int,
            help="Override number of teachers to create",
        )
        parser.add_argument(
            "--min-students",
            type=int,
            help="Override minimum number of students to create",
        )
        parser.add_argument(
            "--min-runs",
            type=int,
            help="Override minimum number of runs (new model) to create",
        )
        parser.add_argument(
            "--min-statistics",
            type=int,
            help="Override minimum number of legacy run statistics to create",
        )
        parser.add_argument(
            "--skip-legacy",
            action="store_true",
            help="Skip creating legacy RunStatistics (only create new Run model data)",
        )

    def handle(self, *args, **options):
        if options["clear"]:
            self.clear_data()

        # Get preset and apply overrides
        preset = PRESETS[options["preset"]]
        num_schools = options["schools"] or preset["schools"]
        num_teachers = options["teachers"] or preset["teachers"]
        min_students = options["min_students"] or preset["min_students"]
        min_runs = options["min_runs"] or preset["min_runs"]
        min_statistics = options["min_statistics"] or preset["min_legacy_statistics"]

        self.stdout.write(
            self.style.NOTICE(
                f"Starting database seeding (preset: {options['preset']})..."
            )
        )
        self.stdout.write(
            f"  Target: {num_schools} schools, {num_teachers} teachers, "
            f"{min_students}+ students, {min_runs}+ runs"
        )
        self.level_decks = self.load_level_decks()

        schools = self.create_schools(num_schools)
        teachers = self.create_teachers(num_teachers, schools)
        classrooms = self.create_classrooms(teachers)
        students = self.create_students(classrooms, min_students)

        # Create new Run model data (with TurnEvents and SpecialTileTriggers)
        runs_created, turns_created, triggers_created = self.create_runs(
            students, min_runs
        )

        # Optionally create legacy RunStatistics
        legacy_count = 0
        if not options["skip_legacy"]:
            legacy_stats = self.create_run_statistics(students, min_statistics)
            legacy_count = len(legacy_stats)

        self.stdout.write(
            self.style.SUCCESS(f"""
Database seeding completed!
----------------------------
Schools created:              {len(schools)}
Teachers created:             {len(teachers)}
Classrooms created:           {len(classrooms)}
Students created:             {len(students)}
Runs created (new model):     {runs_created}
Turn events created:          {turns_created}
Special tile triggers:        {triggers_created}
Legacy statistics created:    {legacy_count}
        """)
        )

    def clear_data(self):
        """Clear existing seeded data (preserving superusers)"""
        self.stdout.write(self.style.WARNING("Clearing existing data..."))

        # Delete in reverse order of dependencies
        SpecialTileTrigger.objects.all().delete()
        TurnEvent.objects.all().delete()
        Run.objects.all().delete()
        RunStatistics.objects.all().delete()
        Student.objects.all().delete()
        Classroom.objects.all().delete()
        TeacherSchoolAssignment.objects.all().delete()

        # Delete teacher users (but not superusers)
        teacher_users = User.objects.filter(teacher_profile__isnull=False)
        Teacher.objects.all().delete()
        teacher_users.delete()

        School.objects.all().delete()

        self.stdout.write(self.style.SUCCESS("Data cleared successfully"))

    def generate_name(self):
        """Generate a random full name"""
        return f"{random.choice(self.FIRST_NAMES)} {random.choice(self.LAST_NAMES)}"

    def generate_email(self, name, domain="example.com"):
        """Generate email from name"""
        clean_name = (
            name.lower()
            .replace(" ", ".")
            .replace("č", "c")
            .replace("š", "s")
            .replace("ž", "z")
        )
        random_suffix = "".join(random.choices(string.digits, k=3))
        return f"{clean_name}{random_suffix}@{domain}"

    def generate_phone(self):
        """Generate a Macedonian-style phone number"""
        prefixes = ["070", "071", "072", "075", "076", "077", "078"]
        return f"{random.choice(prefixes)}{random.randint(100000, 999999)}"

    def generate_classroom_key(self):
        """Generate a unique classroom key"""
        letters = "".join(random.choices(string.ascii_uppercase, k=3))
        numbers = "".join(random.choices(string.digits, k=4))
        return f"{letters}-{numbers}"

    def create_schools(self, count):
        """Create mock schools"""
        self.stdout.write(f"Creating {count} schools...")
        schools = []
        used_combinations = set()

        for i in range(count):
            # Generate unique school name combination
            while True:
                school_type = random.choice(self.SCHOOL_TYPES)
                school_name = random.choice(self.SCHOOL_NAME_PARTS)
                municipality = random.choice(self.MUNICIPALITIES)
                region = random.choice(self.REGIONS)
                full_name = f"{school_type} {school_name}"

                combo = (full_name, municipality, region)
                if combo not in used_combinations:
                    used_combinations.add(combo)
                    break

            director_name = self.generate_name()
            contact_name = self.generate_name()

            # 70% approved, 20% pending, 10% rejected
            status_roll = random.random()
            if status_roll < 0.7:
                status = "APPROVED"
            elif status_roll < 0.9:
                status = "PENDING"
            else:
                status = "REJECTED"

            school = School.objects.create(
                name=full_name,
                municipality=municipality,
                region=region,
                address=f"ul. {random.choice(self.SCHOOL_NAME_PARTS)} br. {random.randint(1, 200)}",
                latitude=41.0 + random.uniform(-0.5, 0.5),
                longitude=21.4 + random.uniform(-0.5, 0.5),
                website=f"https://www.{full_name.lower().replace(' ', '')}.edu.mk"
                if random.random() > 0.3
                else "",
                contact_person_name=contact_name,
                contact_person_email=self.generate_email(contact_name, "gmail.com"),
                contact_person_phone=self.generate_phone(),
                director_name=director_name,
                director_email=self.generate_email(director_name, "schools.edu.mk"),
                school_email=f"contact@{full_name.lower().replace(' ', '')[:20]}.edu.mk",
                school_phone=f"02-{random.randint(3000000, 3999999)}",
                status=status,
            )
            schools.append(school)

        approved_count = len([s for s in schools if s.status == "APPROVED"])
        self.stdout.write(
            f"  - {approved_count} approved, {len(schools) - approved_count} pending/rejected"
        )
        return schools

    def create_teachers(self, count, schools):
        """Create mock teachers with user accounts"""
        self.stdout.write(f"Creating {count} teachers...")
        teachers = []
        approved_schools = [s for s in schools if s.status == "APPROVED"]

        if not approved_schools:
            self.stdout.write(self.style.ERROR("No approved schools available!"))
            return teachers

        for i in range(count):
            full_name = self.generate_name()
            email = self.generate_email(full_name, "teachers.edu.mk")

            # Ensure unique email
            counter = 1
            base_email = email
            while Teacher.objects.filter(email=email).exists():
                email = base_email.replace("@", f"{counter}@")
                counter += 1

            # 80% approved, 15% pending, 5% rejected
            status_roll = random.random()
            if status_roll < 0.8:
                status = "APPROVED"
            elif status_roll < 0.95:
                status = "PENDING"
            else:
                status = "REJECTED"

            # Create user account only for approved teachers
            user = None
            if status == "APPROVED":
                username = email.split("@")[0][:30]
                counter = 1
                base_username = username
                while User.objects.filter(username=username).exists():
                    username = f"{base_username[:27]}{counter}"
                    counter += 1

                name_parts = full_name.split(" ", 1)
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password="demo_password_123",
                    first_name=name_parts[0] if len(name_parts) > 0 else "",
                    last_name=name_parts[1] if len(name_parts) > 1 else "",
                    is_active=True,
                    is_staff=True,
                )
                teachers_group, created = Group.objects.get_or_create(name="Teachers")
                user.groups.add(teachers_group)

            teacher = Teacher.objects.create(
                user=user,
                full_name=full_name,
                email=email,
                phone_number=self.generate_phone(),
                years_teaching=random.randint(1, 30),
                status=status,
            )

            # Assign to 1-3 approved schools
            num_schools = random.randint(1, min(3, len(approved_schools)))
            assigned_schools = random.sample(approved_schools, num_schools)

            for school in assigned_schools:
                TeacherSchoolAssignment.objects.create(
                    teacher=teacher,
                    school=school,
                    years_at_school=random.randint(
                        1, min(15, teacher.years_teaching or 1)
                    ),
                )

            teachers.append(teacher)

        approved_count = len([t for t in teachers if t.status == "APPROVED"])
        self.stdout.write(f"  - {approved_count} approved with user accounts")
        return teachers

    def create_classrooms(self, teachers):
        """Create classrooms for approved teachers"""
        self.stdout.write("Creating classrooms...")
        classrooms = []
        approved_teachers = [t for t in teachers if t.status == "APPROVED"]

        for teacher in approved_teachers:
            # Each approved teacher gets 1-4 classrooms
            num_classrooms = random.randint(1, 4)
            teacher_schools = list(teacher.schools.filter(status="APPROVED"))

            if not teacher_schools:
                continue

            for _ in range(num_classrooms):
                school = random.choice(teacher_schools)
                grade = random.choice(self.CLASSROOM_PREFIXES)
                suffix = random.choice(self.CLASSROOM_SUFFIXES)

                classroom = Classroom.objects.create(
                    classroom_key=self.generate_classroom_key(),
                    classroom_name=f"{grade}-{suffix}",
                    grade=int(grade),
                    teacher=teacher,
                    school=school,
                )
                classrooms.append(classroom)

        self.stdout.write(f"  - Created {len(classrooms)} classrooms")
        return classrooms

    def create_students(self, classrooms, min_count):
        """Create students in classrooms"""
        self.stdout.write(f"Creating at least {min_count} students...")
        students = []

        if not classrooms:
            self.stdout.write(self.style.ERROR("No classrooms available!"))
            return students

        # First ensure minimum count
        students_per_classroom = max(5, min_count // len(classrooms))

        for classroom in classrooms:
            # Each classroom gets 15-30 students
            num_students = random.randint(
                max(15, students_per_classroom), max(30, students_per_classroom + 10)
            )
            used_names = set()

            for _ in range(num_students):
                # Generate unique name for this classroom
                while True:
                    full_name = self.generate_name()
                    if full_name not in used_names:
                        used_names.add(full_name)
                        break

                # Calculate age based on classroom grade
                base_age = 6 + (classroom.grade or 1)
                birth_year = date.today().year - base_age - random.randint(0, 1)
                birth_date = date(
                    birth_year, random.randint(1, 12), random.randint(1, 28)
                )

                student = Student.objects.create(
                    full_name=full_name,
                    date_of_birth=birth_date,
                    grade=classroom.grade,
                    classroom=classroom,
                )
                students.append(student)

        self.stdout.write(
            f"  - Created {len(students)} students across {len(classrooms)} classrooms"
        )
        return students

    def create_runs(self, students, min_count):
        """Create Run records with TurnEvents and SpecialTileTriggers"""
        self.stdout.write(f"Creating at least {min_count} runs (new model)...")

        if not students:
            self.stdout.write(self.style.ERROR("No students available!"))
            return 0, 0, 0

        runs_per_student = max(1, min_count // len(students))
        total_runs = 0
        total_turns = 0
        total_triggers = 0

        # Process in batches to show progress
        batch_size = 100
        student_batches = [
            students[i : i + batch_size] for i in range(0, len(students), batch_size)
        ]

        for batch_idx, student_batch in enumerate(student_batches):
            runs_to_create = []
            turns_to_create = []
            triggers_to_create = []

            for student in student_batch:
                # Each student gets runs_per_student to runs_per_student+5 runs
                num_runs = random.randint(runs_per_student, runs_per_student + 5)

                for _ in range(num_runs):
                    run_data = self._generate_run_data(student)
                    runs_to_create.append(run_data["run"])
                    turns_to_create.extend(run_data["turns"])
                    triggers_to_create.extend(run_data["triggers"])

            # Bulk create runs
            Run.objects.bulk_create(runs_to_create)
            total_runs += len(runs_to_create)

            # Bulk create turn events
            TurnEvent.objects.bulk_create(turns_to_create)
            total_turns += len(turns_to_create)

            # Bulk create triggers
            if triggers_to_create:
                SpecialTileTrigger.objects.bulk_create(triggers_to_create)
                total_triggers += len(triggers_to_create)

            # Progress update
            progress = ((batch_idx + 1) / len(student_batches)) * 100
            self.stdout.write(
                f"  - Progress: {progress:.0f}% ({total_runs} runs, {total_turns} turns)"
            )

        self.stdout.write(
            f"  - Created {total_runs} runs, {total_turns} turn events, {total_triggers} triggers"
        )
        return total_runs, total_turns, total_triggers

    def load_level_decks(self):
        """
        Load level decks from assets.
        Primary path: digitmileapi/templates/assets/LevelX.json
        Legacy fallback: ../DigitMile/assets/LevelX.json
        """
        assets_dir = Path(__file__).resolve().parents[2] / "templates" / "assets"
        legacy_assets_dir = Path(__file__).resolve().parents[4] / "DigitMile" / "assets"

        decks = {}
        for level in self.LEVEL_RANGE:
            filename = f"Level{level}.json"
            deck_path = assets_dir / filename
            if not deck_path.exists():
                deck_path = legacy_assets_dir / filename

            if not deck_path.exists():
                self.stdout.write(
                    self.style.WARNING(
                        f"Deck asset missing for level {level} ({filename}); using fallback Move cards"
                    )
                )
                decks[level] = ["Move1", "Move2", "Move3", "Move4", "Move5"]
                continue

            with deck_path.open("r", encoding="utf-8") as handle:
                payload = json.load(handle)

            expanded_cards = []
            for entry in payload.get("cards", []):
                card_name = entry.get("cardName")
                count = int(entry.get("count") or 0)
                if not card_name or count <= 0:
                    continue
                expanded_cards.extend([card_name] * count)

            if not expanded_cards:
                expanded_cards = ["Move1", "Move2", "Move3", "Move4", "Move5"]

            decks[level] = expanded_cards

        return decks

    def _build_game_map(self):
        """Build a 60-tile map with tile types 0..6 and clown/skateboard special tiles."""
        tile_type_by_index = {}

        for tile_index in range(self.BOARD_SIZE):
            if tile_index == 0 or tile_index == self.BOARD_SIZE - 1:
                tile_type = self.START_END_TILE_TYPE
            else:
                roll = random.random()
                if roll < 0.11:
                    tile_type = 4
                elif roll < 0.22:
                    tile_type = 5
                else:
                    tile_type = random.choice(self.NORMAL_TILE_TYPES)
            tile_type_by_index[tile_index] = tile_type

        anchor = random.randint(8, self.BOARD_SIZE - 9)
        anchor_type = random.choice([4, 5])
        pair_index = anchor + (4 if anchor_type == 5 else -4)
        if 0 < pair_index < self.BOARD_SIZE - 1:
            tile_type_by_index[anchor] = anchor_type
            tile_type_by_index[pair_index] = random.choice([4, 5])

        game_map = []
        for tile_index in range(self.BOARD_SIZE):
            tile_type = tile_type_by_index[tile_index]
            if tile_type == 4:
                special = "clown"
                special_delta = -4
            elif tile_type == 5:
                special = "skateboard"
                special_delta = 4
            else:
                special = "normal"
                special_delta = 0

            game_map.append(
                {
                    "tileMapIndex": tile_index,
                    "tileIndex": tile_type,
                    "tileType": tile_type,
                    "special": special,
                    "special_delta": special_delta,
                }
            )

        return game_map, tile_type_by_index

    def _serialize_card_data(
        self,
        tile_type=None,
        if_sign=None,
        if_value=None,
        then_value=None,
        else_value=None,
    ):
        return (
            "[CardData: "
            f"tileType={'' if tile_type is None else tile_type}, "
            f"ifSign={'' if if_sign is None else if_sign}, "
            f"ifValue={'' if if_value is None else if_value}, "
            f"thenValue={'' if then_value is None else then_value}, "
            f"elseValue={'' if else_value is None else else_value}]"
        )

    def _parse_card_data(self, card_data):
        fields = {
            "tileType": None,
            "ifSign": None,
            "ifValue": None,
            "thenValue": None,
            "elseValue": None,
        }
        if not card_data:
            return fields

        raw = str(card_data).strip()
        if raw.startswith("[") and raw.endswith("]"):
            raw = raw[1:-1].strip()
        if raw.lower().startswith("carddata:"):
            raw = raw.split(":", 1)[1].strip()

        for key, value in re.findall(r"(\w+)\s*=\s*([^,]*)", raw):
            value = value.strip()
            if key == "ifSign":
                fields[key] = value or None
            elif key in fields:
                fields[key] = int(value) if value else None

        return fields

    def _normalize_card_type(self, card_type):
        if card_type in {"Bug", "Back"}:
            return "Back"
        if isinstance(card_type, str) and card_type.startswith("AllBack"):
            return "Back"
        return card_type

    def _make_card_from_deck_name(self, card_name, level=None):
        """Convert deck card names to persisted card payload shape."""
        move_else_match = re.match(r"^Move(\d+)Else(\d+)$", card_name)
        if move_else_match:
            then_value = int(move_else_match.group(1))
            else_value = int(move_else_match.group(2))

            if level in {5, 6} and random.random() < 0.45:
                bag_type = random.choice(
                    [
                        "IfBagEqualXMoveYElseMoveZ",
                        "IfBagLessXMoveYElseMoveZ",
                        "IfBagGreaterXMoveYElseMoveZ",
                    ]
                )
                bag_sign_by_type = {
                    "IfBagEqualXMoveYElseMoveZ": "==",
                    "IfBagLessXMoveYElseMoveZ": "<",
                    "IfBagGreaterXMoveYElseMoveZ": ">",
                }
                return {
                    "type": bag_type,
                    "data": self._serialize_card_data(
                        if_sign=bag_sign_by_type[bag_type],
                        if_value=random.randint(1, 5),
                        then_value=then_value,
                        else_value=else_value,
                    ),
                }

            return {
                "type": "IfXMoveYElseMoveZ",
                "data": self._serialize_card_data(
                    tile_type=random.randint(1, 6),
                    then_value=then_value,
                    else_value=else_value,
                ),
            }

        move_match = re.match(r"^Move(\d+)$", card_name)
        if move_match:
            move_steps = int(move_match.group(1))

            if level is not None and level >= 3 and random.random() < 0.12:
                return {
                    "type": "ForXMoveY",
                    "data": self._serialize_card_data(
                        tile_type=random.randint(1, 6),
                        then_value=move_steps,
                    ),
                }

            return {
                "type": "MoveX",
                "data": self._serialize_card_data(then_value=move_steps),
            }

        all_back_match = re.match(r"^AllBack(\d+)$", card_name)
        if all_back_match:
            return {
                "type": card_name,
                "data": self._serialize_card_data(then_value=int(all_back_match.group(1))),
            }

        if card_name == "BagMove":
            return {
                "type": "BagCount",
                "data": self._serialize_card_data(),
            }

        return {
            "type": "MoveX",
            "data": self._serialize_card_data(then_value=1),
        }

    def _count_players_on_tile_type(
        self, tile_type, player_position, bot_positions, tile_type_by_index
    ):
        count = 1 if tile_type_by_index.get(player_position) == tile_type else 0
        for bot in bot_positions:
            bot_index = bot.get("tileMapIndex")
            if tile_type_by_index.get(bot_index) == tile_type:
                count += 1
        return count

    def _evaluate_card_movement(
        self,
        card,
        tile_before_type,
        bag_before,
        player_position,
        bot_positions_before,
        tile_type_by_index,
    ):
        card_type = self._normalize_card_type(card.get("type"))
        data = self._parse_card_data(card.get("data"))
        then_value = data.get("thenValue")
        else_value = data.get("elseValue")
        tile_type = data.get("tileType")
        if_value = data.get("ifValue")

        if card_type == "MoveX":
            return then_value if then_value is not None else 1

        if card_type == "Back":
            return -(then_value if then_value is not None else 1)

        if card_type == "IfXMoveYElseMoveZ":
            if tile_before_type == tile_type:
                return then_value or 0
            return else_value or 0

        if card_type == "IfBagEqualXMoveYElseMoveZ":
            if bag_before == if_value:
                return then_value or 0
            return else_value or 0

        if card_type == "IfBagLessXMoveYElseMoveZ":
            if bag_before < if_value:
                return then_value or 0
            return else_value or 0

        if card_type == "IfBagGreaterXMoveYElseMoveZ":
            if bag_before > if_value:
                return then_value or 0
            return else_value or 0

        if card_type == "BagCount":
            return bag_before

        if card_type == "ForXMoveY":
            if tile_type is None or then_value is None:
                return 0
            players_count = self._count_players_on_tile_type(
                tile_type, player_position, bot_positions_before, tile_type_by_index
            )
            return players_count * then_value

        return 1

    def _draw_cards(self, deck_state, draw_count=3):
        drawn = []
        while len(drawn) < draw_count:
            if not deck_state["remaining"]:
                deck_state["remaining"] = deck_state["base"][:]
                random.shuffle(deck_state["remaining"])
            drawn.append(deck_state["remaining"].pop())
        return drawn

    def _copy_bot_positions(self, bot_positions):
        return [
            {"tileMapIndex": bot["tileMapIndex"], "botID": bot["botID"]}
            for bot in bot_positions
        ]

    def _compute_place(self, player_position, bot_positions):
        bots_ahead = 0
        for bot in bot_positions:
            if bot["tileMapIndex"] > player_position:
                bots_ahead += 1
        return 1 + bots_ahead

    def _resolve_special_chain(
        self,
        turn,
        start_position,
        bot_positions_after,
        tile_type_by_index,
    ):
        triggers = []
        current_position = start_position
        visited_positions = set()
        chain_index = 0

        while chain_index < 5:
            special_type = tile_type_by_index.get(current_position)
            if special_type not in self.SPECIAL_TILE_DELTAS:
                break
            if current_position in visited_positions:
                break

            visited_positions.add(current_position)
            delta = self.SPECIAL_TILE_DELTAS[special_type]
            target_position = max(
                0, min(self.BOARD_SIZE - 1, current_position + delta)
            )
            target_type = tile_type_by_index.get(target_position, self.START_END_TILE_TYPE)

            trigger = SpecialTileTrigger(
                turn=turn,
                chain_index=chain_index,
                special_tile_index=current_position,
                special_tile_type=special_type,
                effect_delta_tiles=delta,
                target_tile_index=target_position,
                target_tile_type=target_type,
                place_before=self._compute_place(current_position, bot_positions_after),
                place_after=self._compute_place(target_position, bot_positions_after),
            )
            triggers.append(trigger)

            current_position = target_position
            chain_index += 1

        return triggers, current_position

    def _generate_run_data(self, student):
        """
        Generate one run with realistic deck-based cards and 60-tile map payload.
        """
        run_id = f"run_{uuid.uuid4().hex}"
        level = random.choice(list(self.LEVEL_RANGE))
        deck_cards = self.level_decks.get(level) or [
            "Move1",
            "Move2",
            "Move3",
            "Move4",
            "Move5",
        ]
        deck_state = {"base": deck_cards[:], "remaining": deck_cards[:]}
        random.shuffle(deck_state["remaining"])

        min_turns = 20 + level
        max_turns = 40 + level
        max_turn_budget = random.randint(min_turns, max_turns)
        target_accuracy = max(0.45, 0.85 - (level * 0.06))

        base_timestamp = datetime.now(dt_timezone.utc).timestamp() - random.randint(
            0, 30 * 24 * 3600
        )
        timestamp_offset_ms = 0

        game_map, tile_type_by_index = self._build_game_map()
        finish_tile = self.BOARD_SIZE - 1
        current_position = 0
        bot_ids = ["bot_1", "bot_2"]
        bot_start_positions = random.sample(range(1, self.BOARD_SIZE - 1), k=2)
        bot_positions = [
            {"tileMapIndex": position, "botID": bot_id}
            for bot_id, position in zip(bot_ids, bot_start_positions)
        ]
        current_place = self._compute_place(current_position, bot_positions)
        bag_number = 1

        turns = []
        triggers = []
        correct_count = 0
        wrong_count = 0

        for turn_idx in range(max_turn_budget):
            if current_position >= finish_tile:
                break

            card_decision_ms = random.randint(1000, 10000)
            timestamp_offset_ms += card_decision_ms
            timestamp_played = datetime.fromtimestamp(
                base_timestamp + (timestamp_offset_ms / 1000), tz=dt_timezone.utc
            )

            tile_before_index = current_position
            tile_before_type = tile_type_by_index.get(
                current_position, self.START_END_TILE_TYPE
            )
            place_before = self._compute_place(current_position, bot_positions)

            offered_card_names = self._draw_cards(deck_state, draw_count=3)
            offered_candidates = []
            for card_name in offered_card_names:
                card_payload = self._make_card_from_deck_name(card_name, level=level)
                projected_movement = self._evaluate_card_movement(
                    card=card_payload,
                    tile_before_type=tile_before_type,
                    bag_before=bag_number,
                    player_position=current_position,
                    bot_positions_before=bot_positions,
                    tile_type_by_index=tile_type_by_index,
                )
                offered_candidates.append(
                    {"card": card_payload, "movement": projected_movement}
                )

            movements = [candidate["movement"] for candidate in offered_candidates]
            best_movement = max(movements)
            best_choices = [
                candidate
                for candidate in offered_candidates
                if candidate["movement"] == best_movement
            ]
            non_best_choices = [
                candidate
                for candidate in offered_candidates
                if candidate["movement"] != best_movement
            ]

            choose_best = random.random() < target_accuracy
            if choose_best or not non_best_choices:
                selected_candidate = random.choice(best_choices)
                was_correct = True if choose_best else False
            else:
                selected_candidate = random.choice(non_best_choices)
                was_correct = False

            movement = selected_candidate["movement"]
            chosen_card = selected_candidate["card"]
            offered_cards = [candidate["card"] for candidate in offered_candidates]

            if was_correct:
                correct_count += 1
            else:
                wrong_count += 1

            offered_numbers = []
            chosen_number = None
            number_decision_ms = None
            if level >= 5:
                offered_numbers = random.sample([1, 2, 3, 4, 5], 4)
                chosen_number = random.choice(offered_numbers)
                number_decision_ms = random.randint(500, 3000)
                timestamp_offset_ms += number_decision_ms

            bot_positions_before = self._copy_bot_positions(bot_positions)
            for bot in bot_positions:
                step = random.choices(
                    population=[-1, 0, 1, 2, 3],
                    weights=[8, 18, 32, 28, 14],
                    k=1,
                )[0]
                bot["tileMapIndex"] = max(
                    0, min(self.BOARD_SIZE - 1, bot["tileMapIndex"] + step)
                )
            bot_positions_after = self._copy_bot_positions(bot_positions)

            moved_position = max(0, min(finish_tile, tile_before_index + movement))
            turn = TurnEvent(
                run_id=run_id,
                turn_index=turn_idx,
                timestamp_played=timestamp_played,
                chosen_card=chosen_card,
                offered_cards=offered_cards,
                was_correct=was_correct,
                tile_before_index=tile_before_index,
                tile_before_type=tile_before_type,
                tile_after_index=moved_position,
                place_before=place_before,
                place_after=place_before,
                bot_positions_before=bot_positions_before,
                bot_positions_after=bot_positions_after,
                card_decision_time_ms=card_decision_ms,
                offered_numbers=offered_numbers,
                chosen_number=chosen_number,
                number_decision_time_ms=number_decision_ms,
            )
            turns.append(turn)

            turn_triggers, final_position = self._resolve_special_chain(
                turn=turn,
                start_position=moved_position,
                bot_positions_after=bot_positions_after,
                tile_type_by_index=tile_type_by_index,
            )
            triggers.extend(turn_triggers)

            final_place = self._compute_place(final_position, bot_positions_after)
            turn.tile_after_index = final_position
            turn.place_after = final_place

            current_position = final_position
            current_place = final_place
            if chosen_number is not None:
                bag_number = chosen_number

        elapsed_ms = max(1000, timestamp_offset_ms)
        player_won = current_position >= finish_tile or current_place == 1
        score = max(
            0,
            (level * 120)
            + (correct_count * 20)
            - (wrong_count * 8)
            + (250 if player_won else 0),
        )

        run = Run(
            id=run_id,
            student=student,
            level=level,
            player_won=player_won,
            score=score,
            place=current_place,
            elapsed_ms=elapsed_ms,
            correct_moves=correct_count,
            wrong_moves=wrong_count,
            game_map=game_map,
            map_version=random.choice(["1", "1.1", "1.2"]),
            bot_version=random.choice(["1", "2", "2.1"]),
            rng_seed=random.randint(1, 999999) if random.random() > 0.3 else None,
        )

        return {
            "run": run,
            "turns": turns,
            "triggers": triggers,
        }

    def create_run_statistics(self, students, min_count):
        """Create legacy game run statistics for students"""
        self.stdout.write(f"Creating at least {min_count} legacy run statistics...")
        statistics = []

        if not students:
            self.stdout.write(self.style.ERROR("No students available!"))
            return statistics

        # Ensure we create at least min_count statistics
        stats_per_student = max(5, min_count // len(students))

        for student in students:
            # Each student has some runs
            total_runs = random.randint(stats_per_student, stats_per_student + 5)

            for _ in range(total_runs):
                level = random.randint(1, 10)
                player_won = random.random() > 0.4  # 60% win rate

                # Score correlates with winning and level
                if player_won:
                    base_score = level * 100
                    score = base_score + random.randint(50, 200)
                else:
                    score = random.randint(10, level * 50)

                # Moves correlate with level difficulty
                correct_moves = random.randint(level * 2, level * 5)
                wrong_moves = (
                    random.randint(0, level * 2)
                    if player_won
                    else random.randint(level, level * 4)
                )

                # Time correlates with level (higher levels take longer)
                base_time = level * 30
                time_elapsed = base_time + random.uniform(-10, 60)

                stat = RunStatistics.objects.create(
                    student=student,
                    player_won=player_won,
                    level=level,
                    score=score,
                    place=random.randint(1, 5) if player_won else random.randint(3, 10),
                    correct_moves=correct_moves,
                    wrong_moves=wrong_moves,
                    time_elapsed=round(time_elapsed, 2),
                )
                statistics.append(stat)

        win_count = len([s for s in statistics if s.player_won])
        self.stdout.write(
            f"  - Created {len(statistics)} legacy run statistics ({win_count} wins)"
        )
        return statistics
