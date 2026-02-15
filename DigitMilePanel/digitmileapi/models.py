import uuid
from django.contrib.auth.models import User
from django.db import models


# =============================================================================
# Prefixed ID Generation Functions
# =============================================================================
# Each model gets a unique prefix for easy identification and non-sequential IDs


def generate_school_id():
    """Generate a prefixed ID for School: sch_xxxxxxxx"""
    return f"sch_{uuid.uuid4().hex[:12]}"


def generate_teacher_id():
    """Generate a prefixed ID for Teacher: tch_xxxxxxxx"""
    return f"tch_{uuid.uuid4().hex[:12]}"


def generate_teacher_school_assignment_id():
    """Generate a prefixed ID for TeacherSchoolAssignment: tsa_xxxxxxxx"""
    return f"tsa_{uuid.uuid4().hex[:12]}"


def generate_classroom_id():
    """Generate a prefixed ID for Classroom: cls_xxxxxxxx"""
    return f"cls_{uuid.uuid4().hex[:12]}"


def generate_student_id():
    """Generate a prefixed ID for Student: stu_xxxxxxxx"""
    return f"stu_{uuid.uuid4().hex[:12]}"


def generate_run_statistics_id():
    """Generate a prefixed ID for RunStatistics (legacy): rst_xxxxxxxx"""
    return f"rst_{uuid.uuid4().hex[:12]}"


def generate_run_id():
    """Generate a prefixed ID for Run: run_xxxxxxxx (full UUID for idempotency)"""
    return f"run_{uuid.uuid4().hex}"


def generate_turn_event_id():
    """Generate a prefixed ID for TurnEvent: trn_xxxxxxxx"""
    return f"trn_{uuid.uuid4().hex[:12]}"


def generate_special_tile_trigger_id():
    """Generate a prefixed ID for SpecialTileTrigger: stt_xxxxxxxx"""
    return f"stt_{uuid.uuid4().hex[:12]}"


class SchoolManager(models.Manager):
    """Custom manager to easily filter schools by status"""

    def approved(self):
        return self.filter(status="APPROVED")

    def pending(self):
        return self.filter(status="PENDING")

    def rejected(self):
        return self.filter(status="REJECTED")


class School(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    # Custom prefixed primary key
    id = models.CharField(
        max_length=16, primary_key=True, default=generate_school_id, editable=False
    )

    # Basic school information
    name = models.CharField(max_length=255)
    municipality = models.CharField(max_length=255)
    region = models.CharField(max_length=255, default="RegionPlaceholder")
    latitude = models.FloatField(null=True, blank=True)
    longitude = models.FloatField(null=True, blank=True)
    address = models.CharField(max_length=500)  # Required for uniqueness
    google_maps_address = models.CharField(max_length=500, blank=True, default="")
    website = models.URLField(max_length=255, blank=True, default="")

    # Contact person information (who registered the school)
    contact_person_name = models.CharField(max_length=255, blank=True, default="")
    contact_person_email = models.EmailField(blank=True, default="")
    contact_person_phone = models.CharField(max_length=50, blank=True, default="")

    # Official school information
    director_name = models.CharField(max_length=255)  # Required for uniqueness
    director_email = models.EmailField(blank=True, default="")
    school_email = models.EmailField()  # Required for uniqueness
    school_phone = models.CharField(max_length=50, blank=True, default="")

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    objects = SchoolManager()

    class Meta:
        unique_together = [["name", "municipality", "region"]]

    def __str__(self):
        status_badge = (
            f" [{self.get_status_display()}]" if self.status != "APPROVED" else ""
        )
        return f"{self.name} - {self.municipality}, {self.region}{status_badge}"

    @property
    def is_pending(self):
        return self.status == "PENDING"

    @property
    def is_approved(self):
        return self.status == "APPROVED"

    def save(self, *args, **kwargs):
        """Override save to handle status changes to REJECTED - disables access without deleting data"""
        # Check if this is an existing instance and status is changing to REJECTED
        if self.pk:
            try:
                old_instance = School.objects.get(pk=self.pk)
                if old_instance.status != "REJECTED" and self.status == "REJECTED":
                    # Save school first
                    super().save(*args, **kwargs)

                    # Find all teachers assigned to this school
                    from .models import Teacher

                    teachers_at_school = Teacher.objects.filter(schools=self)

                    # Reject teachers who ONLY have this school (data is preserved)
                    for teacher in teachers_at_school:
                        # Check if this is the teacher's ONLY school
                        if teacher.schools.count() == 1:
                            # Set teacher status to REJECTED (no data deletion)
                            teacher.status = "REJECTED"
                            # Disable user login if user exists
                            if teacher.user:
                                teacher.user.is_active = False
                                teacher.user.save()
                            # Save without triggering cascade again
                            Teacher.objects.filter(pk=teacher.pk).update(
                                status="REJECTED"
                            )

                    return  # Already saved above
            except School.DoesNotExist:
                pass

        super().save(*args, **kwargs)


class TeacherSchoolAssignment(models.Model):
    """Through model to track teacher assignments to schools with years at each school"""

    # Custom prefixed primary key
    id = models.CharField(
        max_length=16,
        primary_key=True,
        default=generate_teacher_school_assignment_id,
        editable=False,
    )

    teacher = models.ForeignKey(
        "Teacher", on_delete=models.CASCADE, related_name="school_assignments"
    )
    school = models.ForeignKey(
        School, on_delete=models.CASCADE, related_name="teacher_assignments"
    )
    years_at_school = models.IntegerField(null=True, blank=True)

    class Meta:
        unique_together = [["teacher", "school"]]

    def __str__(self):
        return f"{self.teacher.full_name} at {self.school.name} ({self.years_at_school} years)"


class TeacherManager(models.Manager):
    """Custom manager to easily filter teachers by status"""

    def approved(self):
        return self.filter(status="APPROVED")

    def pending(self):
        return self.filter(status="PENDING")

    def rejected(self):
        return self.filter(status="REJECTED")


class Teacher(models.Model):
    STATUS_CHOICES = [
        ("PENDING", "Pending Approval"),
        ("APPROVED", "Approved"),
        ("REJECTED", "Rejected"),
    ]

    # Custom prefixed primary key
    id = models.CharField(
        max_length=16, primary_key=True, default=generate_teacher_id, editable=False
    )

    # User account (only created when approved)
    user = models.OneToOneField(
        User,
        on_delete=models.CASCADE,
        null=True,
        blank=True,
        related_name="teacher_profile",
    )

    # Basic teacher information
    full_name = models.CharField(max_length=255)
    email = models.EmailField(unique=True, default="noemail@example.com")
    phone_number = models.CharField(max_length=50, blank=True, default="")
    years_teaching = models.IntegerField(
        null=True, blank=True, help_text="Total years of teaching experience"
    )

    # School assignments (can include pending schools)
    schools = models.ManyToManyField(
        School, through="TeacherSchoolAssignment", related_name="teachers"
    )

    # Status tracking
    status = models.CharField(max_length=20, choices=STATUS_CHOICES, default="PENDING")
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    objects = TeacherManager()

    def __str__(self):
        status_badge = (
            f" [{self.get_status_display()}]" if self.status != "APPROVED" else ""
        )
        if self.user:
            return f"{self.user.get_full_name() or self.user.username}{status_badge}"
        return f"{self.full_name}{status_badge}"

    @property
    def primary_school(self):
        """Returns the first approved school (for backwards compatibility)"""
        return self.schools.filter(status="APPROVED").first()

    @property
    def is_pending(self):
        return self.status == "PENDING"

    @property
    def is_approved(self):
        return self.status == "APPROVED"

    def save(self, *args, **kwargs):
        """Override save to handle status changes:
        - REJECTED: disables user login without deleting data
        - APPROVED (from REJECTED): re-enables user login
        """
        if self.pk:
            try:
                old_instance = Teacher.objects.get(pk=self.pk)

                # Handle transition TO REJECTED
                if old_instance.status != "REJECTED" and self.status == "REJECTED":
                    if self.user:
                        self.user.is_active = False
                        self.user.save()

                    super().save(*args, **kwargs)
                    return

                # Handle transition FROM REJECTED TO APPROVED (re-approval)
                if old_instance.status == "REJECTED" and self.status == "APPROVED":
                    if self.user:
                        self.user.is_active = True
                        self.user.save()

                    super().save(*args, **kwargs)
                    return

            except Teacher.DoesNotExist:
                pass

        super().save(*args, **kwargs)


class Classroom(models.Model):
    # Custom prefixed primary key
    id = models.CharField(
        max_length=16, primary_key=True, default=generate_classroom_id, editable=False
    )

    classroom_key = models.CharField(max_length=100, unique=True)
    classroom_name = models.CharField(
        max_length=255, default="ClassroomNamePlaceholder"
    )
    grade = models.IntegerField(
        null=True, blank=True, help_text="Grade level of the classroom"
    )
    teacher = models.ForeignKey(
        Teacher, on_delete=models.CASCADE, related_name="classrooms"
    )
    school = models.ForeignKey(
        School,
        on_delete=models.CASCADE,
        related_name="classrooms",
        null=True,
        blank=True,
        help_text="The school where this classroom is located",
    )

    class Meta:
        unique_together = [["classroom_key", "school"]]

    def __str__(self):
        return f"{self.classroom_key} at {self.school.name} (Teacher: {self.teacher.full_name})"

    def clean(self):
        """Validate that the teacher is assigned to this school"""
        from django.core.exceptions import ValidationError

        if self.teacher and self.school:
            if not self.teacher.schools.filter(id=self.school.id).exists():
                raise ValidationError(
                    f"Teacher {self.teacher.full_name} is not assigned to {self.school.name}"
                )


class Student(models.Model):
    # Custom prefixed primary key
    id = models.CharField(
        max_length=16, primary_key=True, default=generate_student_id, editable=False
    )

    full_name = models.CharField(max_length=255)
    date_of_birth = models.DateField(
        null=True, blank=True, help_text="Student date of birth"
    )
    grade = models.IntegerField(null=True, blank=True, help_text="Student grade level")
    classroom = models.ForeignKey(
        Classroom, on_delete=models.CASCADE, related_name="students"
    )

    class Meta:
        unique_together = [["full_name", "classroom"]]  # <--- ADDED

    def __str__(self):
        return self.full_name


class RunStatistics(models.Model):
    # Custom prefixed primary key
    id = models.CharField(
        max_length=16,
        primary_key=True,
        default=generate_run_statistics_id,
        editable=False,
    )

    student = models.ForeignKey(
        Student, on_delete=models.CASCADE, related_name="run_statistics"
    )
    player_won = models.BooleanField()
    level = models.IntegerField(null=True, blank=True)
    score = models.IntegerField(null=True, blank=True)
    place = models.IntegerField(null=True, blank=True)
    correct_moves = models.IntegerField(null=True, blank=True)
    wrong_moves = models.IntegerField(null=True, blank=True)
    time_elapsed = models.FloatField(null=True, blank=True)
    created_at = models.DateTimeField(auto_now_add=True, null=True, blank=True)
    updated_at = models.DateTimeField(auto_now=True, null=True, blank=True)

    def __str__(self):
        return f"Run for {self.student.full_name} - Level: {self.level} - Won: {self.player_won}"


class Run(models.Model):
    """
    Represents a single game session (run) for a student.
    Uses client-provided prefixed UUID for idempotent ingestion.
    Format: run_<32-char-hex> (e.g., run_a1b2c3d4e5f6...)
    """

    # Custom prefixed primary key (longer for full UUID to ensure idempotency)
    id = models.CharField(
        max_length=36, primary_key=True, default=generate_run_id, editable=False
    )

    student = models.ForeignKey(Student, on_delete=models.CASCADE, related_name="runs")
    level = models.IntegerField()
    player_won = models.BooleanField()
    score = models.IntegerField()
    place = models.IntegerField(default=4, help_text="Final place (1st, 2nd, 3rd, 4th)")
    elapsed_ms = models.IntegerField(help_text="Total game duration in milliseconds")
    correct_moves = models.IntegerField()
    wrong_moves = models.IntegerField()
    game_map = models.JSONField(
        default=list,
        help_text="The game map tiles for this run (list of TileSnapshot objects)",
    )
    map_version = models.CharField(max_length=50, default="1")
    bot_version = models.CharField(max_length=50, default="1")
    rng_seed = models.IntegerField(
        null=True, blank=True, help_text="Random seed for reproducibility"
    )
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [
            models.Index(
                fields=["student", "created_at"], name="run_student_created_idx"
            ),
            models.Index(fields=["student", "level"], name="run_student_level_idx"),
            models.Index(fields=["level", "created_at"], name="run_level_created_idx"),
        ]
        ordering = ["-created_at"]

    def __str__(self):
        return f"Run {self.id} - {self.student.full_name} - Level {self.level} - {'Won' if self.player_won else 'Lost'}"


class TurnEvent(models.Model):
    """
    Represents a single turn within a game run.
    Captures the player's card choice, timing, and resulting board state changes.
    """

    # Custom prefixed primary key
    id = models.CharField(
        max_length=16, primary_key=True, default=generate_turn_event_id, editable=False
    )

    run = models.ForeignKey(Run, on_delete=models.CASCADE, related_name="turn_events")
    turn_index = models.IntegerField()
    timestamp_played = models.DateTimeField()
    chosen_card = models.JSONField(help_text="The card chosen by the player")
    offered_cards = models.JSONField(help_text="All cards offered to the player")
    was_correct = models.BooleanField()
    tile_before_index = models.IntegerField(help_text="Player position before turn")
    tile_before_type = models.IntegerField(
        help_text="Tile type at position before turn"
    )
    tile_after_index = models.IntegerField(help_text="Player position after turn")
    place_before = models.IntegerField()
    place_after = models.IntegerField()
    bot_positions_before = models.JSONField(
        default=list,
        help_text="Bot positions before player move (list of {tileMapIndex, botID})",
    )
    bot_positions_after = models.JSONField(
        default=list,
        help_text="Bot positions after turn resolution (list of {tileMapIndex, botID})",
    )
    card_decision_time_ms = models.IntegerField(
        help_text="Time taken to choose card in ms"
    )
    offered_numbers = models.JSONField(
        default=list, help_text="Numbers offered for selection"
    )
    chosen_number = models.IntegerField(null=True, blank=True)
    number_decision_time_ms = models.IntegerField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["run", "turn_index"], name="unique_turn_per_run"
            )
        ]
        indexes = [
            models.Index(fields=["run", "turn_index"], name="turn_run_index_idx"),
            models.Index(
                fields=["run", "timestamp_played"], name="turn_run_timestamp_idx"
            ),
        ]
        ordering = ["run", "turn_index"]

    def __str__(self):
        return f"Turn {self.turn_index} - Run {self.run_id} - {'Correct' if self.was_correct else 'Wrong'}"


class SpecialTileTrigger(models.Model):
    """
    Represents a special tile effect triggered during a turn.
    Multiple triggers can chain from a single turn.
    """

    # Custom prefixed primary key
    id = models.CharField(
        max_length=16,
        primary_key=True,
        default=generate_special_tile_trigger_id,
        editable=False,
    )

    turn = models.ForeignKey(
        TurnEvent, on_delete=models.CASCADE, related_name="special_tile_triggers"
    )
    chain_index = models.IntegerField(
        help_text="Order in the chain of special tile effects"
    )
    special_tile_index = models.IntegerField()
    special_tile_type = models.IntegerField()
    effect_delta_tiles = models.IntegerField(
        help_text="Number of tiles moved by this effect"
    )
    target_tile_index = models.IntegerField()
    target_tile_type = models.IntegerField()
    place_before = models.IntegerField()
    place_after = models.IntegerField()

    class Meta:
        constraints = [
            models.UniqueConstraint(
                fields=["turn", "chain_index"], name="unique_chain_per_turn"
            )
        ]
        indexes = [
            models.Index(fields=["turn", "chain_index"], name="trigger_turn_chain_idx"),
            models.Index(fields=["special_tile_index"], name="trigger_tile_index_idx"),
            models.Index(fields=["special_tile_type"], name="trigger_tile_type_idx"),
        ]
        ordering = ["turn", "chain_index"]

    def __str__(self):
        return f"Trigger {self.chain_index} - Turn {self.turn.turn_index} - Tile {self.special_tile_type}"
