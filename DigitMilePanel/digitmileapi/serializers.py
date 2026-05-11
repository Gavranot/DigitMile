# myapi/serializers.py
from rest_framework import serializers

from .models import (
    School,
    Teacher,
    Student,
    Classroom,
    RunStatistics,
    Run,
    TurnEvent,
    SpecialTileTrigger,
)


class SchoolSerializer(serializers.ModelSerializer):
    class Meta:
        model = School
        fields = [
            "id",
            "name",
            "municipality",
            "region",
            "status",
            "address",
            "website",
        ]


class TeacherNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Teacher
        fields = ["full_name"]


class StudentNameSerializer(serializers.ModelSerializer):
    class Meta:
        model = Student
        fields = ["full_name"]


# Serializer for the output of /api/checkClassroomKey
class CheckClassroomResponseSerializer(serializers.Serializer):
    school = SchoolSerializer()
    teacher = serializers.CharField(
        source="teacher_data"
    )  # Expecting a string here based on your Flask code
    students = serializers.ListField(child=serializers.DictField())


# Serializer for the input of /api/insertLevelStatistics
class LevelStatisticsInputSerializer(serializers.Serializer):
    classroomKey = serializers.CharField(max_length=100)
    user = serializers.CharField(max_length=255)  # This is student's full_name
    levelStatistics = serializers.DictField()

    def validate_levelStatistics(self, value):
        # Example validation: ensure 'place' exists and is an integer
        if "place" not in value:
            raise serializers.ValidationError(
                "The 'place' key is required in levelStatistics."
            )
        if not isinstance(value["place"], int):
            raise serializers.ValidationError(
                "The 'place' for levelStatistics must be an integer."
            )
        # Add more validation for other expected keys in levelStatistics if needed
        # e.g., score, correctMoves, wrongMoves, timeElapsed
        return value


class RunStatisticsSerializer(serializers.ModelSerializer):
    class Meta:
        model = RunStatistics
        fields = [
            "id",
            "student",
            "player_won",
            "level",
            "score",
            "place",
            "correct_moves",
            "wrong_moves",
            "time_elapsed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = ["id", "created_at", "updated_at"]


class ClassroomBasicSerializer(serializers.ModelSerializer):
    school = SchoolSerializer(read_only=True)
    school_id = serializers.PrimaryKeyRelatedField(
        queryset=School.objects.all(), source="school", write_only=True
    )

    class Meta:
        model = Classroom
        fields = [
            "id",
            "classroom_key",
            "classroom_name",
            "grade",
            "school",
            "school_id",
        ]


class TeacherStudentManagementSerializer(serializers.ModelSerializer):
    # Display classroom details in a nested way for reads
    classroom = ClassroomBasicSerializer(read_only=True)
    # Allow setting classroom by ID for writes (create/update)
    classroom_id = serializers.PrimaryKeyRelatedField(
        queryset=Classroom.objects.all(), source="classroom", write_only=True
    )

    class Meta:
        model = Student
        fields = [
            "id",
            "full_name",
            "date_of_birth",
            "grade",
            "classroom",
            "classroom_id",
        ]
        read_only_fields = ["id"]

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        # Dynamically filter classroom_id queryset if a teacher is provided in context
        # This is crucial for ensuring teachers can only assign students to their own classrooms.
        request = self.context.get("request", None)
        if request and hasattr(request.user, "teacher_profile"):
            teacher = request.user.teacher_profile
            self.fields["classroom_id"].queryset = Classroom.objects.filter(
                teacher=teacher
            )
        elif (
            request
            and request.method in ["POST", "PUT", "PATCH"]
            and not (request.user.is_staff or request.user.is_superuser)
        ):
            # If it's a write operation by a non-staff user without a teacher_profile,
            # they shouldn't be able to set any classroom.
            # This scenario should ideally be caught by permissions in the view.
            self.fields["classroom_id"].queryset = Classroom.objects.none()


# ==================== Run Analytics Output Serializers ====================


class RunSerializer(serializers.ModelSerializer):
    """Serializer for Run model output."""

    class Meta:
        model = Run
        fields = [
            "id",
            "student",
            "level",
            "player_won",
            "score",
            "place",
            "elapsed_ms",
            "correct_moves",
            "wrong_moves",
            "game_map",
            "map_version",
            "bot_version",
            "rng_seed",
            "created_at",
            "updated_at",
        ]
        read_only_fields = fields


class TurnEventSerializer(serializers.ModelSerializer):
    """Serializer for TurnEvent model output."""

    class Meta:
        model = TurnEvent
        fields = [
            "id",
            "run",
            "turn_index",
            "timestamp_played",
            "chosen_card",
            "offered_cards",
            "was_correct",
            "tile_before_index",
            "tile_before_type",
            "tile_after_index",
            "place_before",
            "place_after",
            "bot_positions_before",
            "bot_positions_after",
            "card_decision_time_ms",
            "offered_numbers",
            "chosen_number",
            "number_decision_time_ms",
        ]
        read_only_fields = fields


class SpecialTileTriggerSerializer(serializers.ModelSerializer):
    """Serializer for SpecialTileTrigger model output."""

    class Meta:
        model = SpecialTileTrigger
        fields = [
            "id",
            "turn",
            "chain_index",
            "special_tile_index",
            "special_tile_type",
            "effect_delta_tiles",
            "target_tile_index",
            "target_tile_type",
            "place_before",
            "place_after",
        ]
        read_only_fields = fields


