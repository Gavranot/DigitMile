"""
Django management command to seed the database with mock data.

Usage:
    python manage.py seed_database
    python manage.py seed_database --clear  # Clear existing data first
"""
import random
import string
from datetime import date, timedelta
from django.core.management.base import BaseCommand
from django.contrib.auth.models import User
from digitmileapi.models import (
    School, Teacher, TeacherSchoolAssignment,
    Classroom, Student, RunStatistics
)


class Command(BaseCommand):
    help = 'Seed the database with mock data for demonstration purposes'

    # Macedonian-style names and locations for realistic data
    FIRST_NAMES = [
        'Aleksandar', 'Ana', 'Andrej', 'Angela', 'Boris', 'Bojana', 'Darko', 'Daniela',
        'Elena', 'Filip', 'Goran', 'Gordana', 'Igor', 'Ivana', 'Jovan', 'Jelena',
        'Kiril', 'Kristina', 'Lazar', 'Lidija', 'Marko', 'Marija', 'Nikola', 'Natalija',
        'Oliver', 'Olivera', 'Petar', 'Petra', 'Riste', 'Rosica', 'Stefan', 'Sofija',
        'Todor', 'Tanja', 'Viktor', 'Vesna', 'Zoran', 'Zorica', 'Martin', 'Maja',
        'David', 'Dimitar', 'Emilija', 'Eva', 'Hristijan', 'Hristina', 'Ilija', 'Irena',
        'Jasmina', 'Jana', 'Kliment', 'Katerina', 'Ljupco', 'Ljupka', 'Metodija', 'Milica',
        'Naum', 'Natasa', 'Ognen', 'Olga', 'Pavle', 'Paulina', 'Robert', 'Radica',
        'Simeon', 'Sanja', 'Trajko', 'Teodora', 'Vlado', 'Valentina', 'Zdravko', 'Zaklina'
    ]

    LAST_NAMES = [
        'Angelovski', 'Atanasovski', 'Bogdanovski', 'Cvetanovski', 'Dimitrovski',
        'Efremovski', 'Filipovski', 'Georgievski', 'Hristovski', 'Ivanovski',
        'Jankulovski', 'Kocevski', 'Lazarovski', 'Mancevski', 'Nikolovski',
        'Ognjenovski', 'Petrevski', 'Ristevski', 'Stojkovski', 'Trajkovski',
        'Velkovski', 'Zdravkovski', 'Arsovski', 'Boskovski', 'Celeski',
        'Damjanski', 'Eftimovski', 'Fidanoski', 'Gligoroski', 'Hadzi-Nikolovski',
        'Ilievski', 'Joveski', 'Kostovski', 'Levkovski', 'Mitreski',
        'Naumovski', 'Ognenovski', 'Pavlovski', 'Radevski', 'Saveski',
        'Tasevski', 'Uzunovski', 'Vasilevski', 'Zafirov', 'Andonovski'
    ]

    MUNICIPALITIES = [
        'Centar', 'Karpos', 'Aerodrom', 'Kisela Voda', 'Gazi Baba',
        'Butel', 'Cair', 'Gjorce Petrov', 'Saraj', 'Suto Orizari'
    ]

    REGIONS = [
        'Skopje', 'Bitola', 'Kumanovo', 'Prilep', 'Tetovo',
        'Veles', 'Stip', 'Ohrid', 'Gostivar', 'Strumica',
        'Kavadarci', 'Kocani', 'Kicevo', 'Struga', 'Radovis'
    ]

    SCHOOL_TYPES = [
        'OU', 'SOU', 'OSOU', 'SOUG', 'OU'  # Primary (OU) more common
    ]

    SCHOOL_NAME_PARTS = [
        'Sveti Kiril i Metodij', 'Goce Delcev', 'Braka Miladinovci', 'Kuzman Josifoski Pitu',
        'Nikola Karev', 'Krste Misirkov', 'Kliment Ohridski', 'Naum Ohridski',
        'Vasil Glavinov', 'Dimitar Vlahov', 'Koco Racin', 'Strasho Pindzur',
        'Blazhe Koneski', 'Vera Ciriviri Trena', 'Jane Sandanski', 'Dame Gruev',
        'Petar Pop Arsov', 'Gjorgji Sugarev', 'Josip Broz Tito', 'Aco Sopov',
        'Vuk Karadzic', 'Aleksandar Makedonski', 'Hristo Tatarcev', 'Boris Trajkovski'
    ]

    CLASSROOM_PREFIXES = ['1', '2', '3', '4', '5', '6', '7', '8', '9']
    CLASSROOM_SUFFIXES = ['a', 'b', 'v', 'g', 'd']

    def add_arguments(self, parser):
        parser.add_argument(
            '--clear',
            action='store_true',
            help='Clear existing seeded data before adding new data',
        )
        parser.add_argument(
            '--schools',
            type=int,
            default=25,
            help='Number of schools to create (default: 25)',
        )
        parser.add_argument(
            '--teachers',
            type=int,
            default=15,
            help='Number of teachers to create (default: 15)',
        )
        parser.add_argument(
            '--min-students',
            type=int,
            default=150,
            help='Minimum number of students to create (default: 150)',
        )
        parser.add_argument(
            '--min-statistics',
            type=int,
            default=1500,
            help='Minimum number of run statistics to create (default: 1500)',
        )

    def handle(self, *args, **options):
        if options['clear']:
            self.clear_data()

        self.stdout.write(self.style.NOTICE('Starting database seeding...'))

        schools = self.create_schools(options['schools'])
        teachers = self.create_teachers(options['teachers'], schools)
        classrooms = self.create_classrooms(teachers)
        students = self.create_students(classrooms, options['min_students'])
        statistics = self.create_run_statistics(students, options['min_statistics'])

        self.stdout.write(self.style.SUCCESS(f'''
Database seeding completed!
----------------------------
Schools created:        {len(schools)}
Teachers created:       {len(teachers)}
Classrooms created:     {len(classrooms)}
Students created:       {len(students)}
Run statistics created: {len(statistics)}
        '''))

    def clear_data(self):
        """Clear existing seeded data (preserving superusers)"""
        self.stdout.write(self.style.WARNING('Clearing existing data...'))

        # Delete in reverse order of dependencies
        RunStatistics.objects.all().delete()
        Student.objects.all().delete()
        Classroom.objects.all().delete()
        TeacherSchoolAssignment.objects.all().delete()

        # Delete teacher users (but not superusers)
        teacher_users = User.objects.filter(teacher_profile__isnull=False)
        Teacher.objects.all().delete()
        teacher_users.delete()

        School.objects.all().delete()

        self.stdout.write(self.style.SUCCESS('Data cleared successfully'))

    def generate_name(self):
        """Generate a random full name"""
        return f"{random.choice(self.FIRST_NAMES)} {random.choice(self.LAST_NAMES)}"

    def generate_email(self, name, domain='example.com'):
        """Generate email from name"""
        clean_name = name.lower().replace(' ', '.').replace('č', 'c').replace('š', 's').replace('ž', 'z')
        random_suffix = ''.join(random.choices(string.digits, k=3))
        return f"{clean_name}{random_suffix}@{domain}"

    def generate_phone(self):
        """Generate a Macedonian-style phone number"""
        prefixes = ['070', '071', '072', '075', '076', '077', '078']
        return f"{random.choice(prefixes)}{random.randint(100000, 999999)}"

    def generate_classroom_key(self):
        """Generate a unique classroom key"""
        letters = ''.join(random.choices(string.ascii_uppercase, k=3))
        numbers = ''.join(random.choices(string.digits, k=4))
        return f"{letters}-{numbers}"

    def create_schools(self, count):
        """Create mock schools"""
        self.stdout.write(f'Creating {count} schools...')
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
                status = 'APPROVED'
            elif status_roll < 0.9:
                status = 'PENDING'
            else:
                status = 'REJECTED'

            school = School.objects.create(
                name=full_name,
                municipality=municipality,
                region=region,
                address=f"ul. {random.choice(self.SCHOOL_NAME_PARTS)} br. {random.randint(1, 200)}",
                latitude=41.0 + random.uniform(-0.5, 0.5),
                longitude=21.4 + random.uniform(-0.5, 0.5),
                website=f"https://www.{full_name.lower().replace(' ', '')}.edu.mk" if random.random() > 0.3 else '',
                contact_person_name=contact_name,
                contact_person_email=self.generate_email(contact_name, 'gmail.com'),
                contact_person_phone=self.generate_phone(),
                director_name=director_name,
                director_email=self.generate_email(director_name, 'schools.edu.mk'),
                school_email=f"contact@{full_name.lower().replace(' ', '')[:20]}.edu.mk",
                school_phone=f"02-{random.randint(3000000, 3999999)}",
                status=status,
            )
            schools.append(school)

        approved_count = len([s for s in schools if s.status == 'APPROVED'])
        self.stdout.write(f'  - {approved_count} approved, {len(schools) - approved_count} pending/rejected')
        return schools

    def create_teachers(self, count, schools):
        """Create mock teachers with user accounts"""
        self.stdout.write(f'Creating {count} teachers...')
        teachers = []
        approved_schools = [s for s in schools if s.status == 'APPROVED']

        if not approved_schools:
            self.stdout.write(self.style.ERROR('No approved schools available!'))
            return teachers

        for i in range(count):
            full_name = self.generate_name()
            email = self.generate_email(full_name, 'teachers.edu.mk')

            # Ensure unique email
            counter = 1
            base_email = email
            while Teacher.objects.filter(email=email).exists():
                email = base_email.replace('@', f'{counter}@')
                counter += 1

            # 80% approved, 15% pending, 5% rejected
            status_roll = random.random()
            if status_roll < 0.8:
                status = 'APPROVED'
            elif status_roll < 0.95:
                status = 'PENDING'
            else:
                status = 'REJECTED'

            # Create user account only for approved teachers
            user = None
            if status == 'APPROVED':
                username = email.split('@')[0][:30]
                counter = 1
                base_username = username
                while User.objects.filter(username=username).exists():
                    username = f"{base_username[:27]}{counter}"
                    counter += 1

                name_parts = full_name.split(' ', 1)
                user = User.objects.create_user(
                    username=username,
                    email=email,
                    password='demo_password_123',
                    first_name=name_parts[0] if len(name_parts) > 0 else '',
                    last_name=name_parts[1] if len(name_parts) > 1 else '',
                    is_active=True,
                )

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
                    years_at_school=random.randint(1, min(15, teacher.years_teaching or 1)),
                )

            teachers.append(teacher)

        approved_count = len([t for t in teachers if t.status == 'APPROVED'])
        self.stdout.write(f'  - {approved_count} approved with user accounts')
        return teachers

    def create_classrooms(self, teachers):
        """Create classrooms for approved teachers"""
        self.stdout.write('Creating classrooms...')
        classrooms = []
        approved_teachers = [t for t in teachers if t.status == 'APPROVED']

        for teacher in approved_teachers:
            # Each approved teacher gets 1-4 classrooms
            num_classrooms = random.randint(1, 4)
            teacher_schools = list(teacher.schools.filter(status='APPROVED'))

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

        self.stdout.write(f'  - Created {len(classrooms)} classrooms')
        return classrooms

    def create_students(self, classrooms, min_count):
        """Create students in classrooms"""
        self.stdout.write(f'Creating at least {min_count} students...')
        students = []

        if not classrooms:
            self.stdout.write(self.style.ERROR('No classrooms available!'))
            return students

        # First ensure minimum count
        students_per_classroom = max(5, min_count // len(classrooms))

        for classroom in classrooms:
            # Each classroom gets 15-30 students
            num_students = random.randint(
                max(15, students_per_classroom),
                max(30, students_per_classroom + 10)
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
                    birth_year,
                    random.randint(1, 12),
                    random.randint(1, 28)
                )

                student = Student.objects.create(
                    full_name=full_name,
                    date_of_birth=birth_date,
                    grade=classroom.grade,
                    classroom=classroom,
                )
                students.append(student)

        self.stdout.write(f'  - Created {len(students)} students across {len(classrooms)} classrooms')
        return students

    def create_run_statistics(self, students, min_count):
        """Create game run statistics for students"""
        self.stdout.write(f'Creating at least {min_count} run statistics...')
        statistics = []

        if not students:
            self.stdout.write(self.style.ERROR('No students available!'))
            return statistics

        # Ensure we create at least min_count statistics
        stats_per_student = max(5, min_count // len(students))

        for student in students:
            # Each student has 5-20 game runs
            num_runs = random.randint(
                max(5, stats_per_student),
                max(20, stats_per_student + 10)
            )

            for _ in range(num_runs):
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
                wrong_moves = random.randint(0, level * 2) if player_won else random.randint(level, level * 4)

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
        self.stdout.write(f'  - Created {len(statistics)} run statistics ({win_count} wins, {len(statistics) - win_count} losses)')
        return statistics
