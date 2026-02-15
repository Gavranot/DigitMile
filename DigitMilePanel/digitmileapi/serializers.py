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


# Make sure this is below the new serializers if they are referenced by existing ones.
# For now, placing it at the end of the new additions.


# ==================== Run Analytics Ingestion Serializers ====================


class SpecialTileTriggerInputSerializer(serializers.Serializer):
    """Validates individual special tile trigger data."""

    chain_index = serializers.IntegerField(min_value=0)
    special_tile_index = serializers.IntegerField(min_value=0)
    special_tile_type = serializers.IntegerField()
    effect_delta_tiles = serializers.IntegerField()
    target_tile_index = serializers.IntegerField(min_value=0)
    target_tile_type = serializers.IntegerField()
    place_before = serializers.IntegerField(min_value=1)
    place_after = serializers.IntegerField(min_value=1)


class TurnEventInputSerializer(serializers.Serializer):
    """Validates individual turn event data."""

    turn_index = serializers.IntegerField(min_value=0)
    timestamp_played_unix_ms = serializers.IntegerField()
    chosen_card = serializers.DictField()
    offered_cards = serializers.ListField(child=serializers.DictField())
    was_correct = serializers.BooleanField()
    tile_before_index = serializers.IntegerField(min_value=0)
    tile_before_type = serializers.IntegerField()
    tile_after_index = serializers.IntegerField(min_value=0)
    place_before = serializers.IntegerField(min_value=1)
    place_after = serializers.IntegerField(min_value=1)
    bot_positions_before = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    bot_positions_after = serializers.ListField(
        child=serializers.DictField(), required=False, default=list
    )
    card_decision_time_ms = serializers.IntegerField(min_value=0)
    offered_numbers = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    chosen_number = serializers.IntegerField(required=False, allow_null=True)
    number_decision_time_ms = serializers.IntegerField(required=False, allow_null=True)
    special_tile_triggers = SpecialTileTriggerInputSerializer(
        many=True, required=False, default=list
    )

    def validate_chosen_number(self, value):
        """Convert -1 sentinel to None."""
        if value == -1:
            return None
        return value

    def validate_number_decision_time_ms(self, value):
        """Convert -1 sentinel to None."""
        if value == -1:
            return None
        return value


class RunIngestionSerializer(serializers.Serializer):
    """
    Main serializer for run ingestion endpoint.
    Validates the entire payload structure from Unity client.
    """

    run_id = serializers.CharField(max_length=36)  # Prefixed ID: run_<32-char-hex>
    student_id = serializers.CharField(max_length=16)  # Prefixed ID: stu_<12-char-hex>
    level = serializers.IntegerField(min_value=1)
    player_won = serializers.BooleanField()
    score = serializers.IntegerField(min_value=0)
    elapsed_ms = serializers.IntegerField(min_value=0)
    correct_moves = serializers.IntegerField(min_value=0)
    wrong_moves = serializers.IntegerField(min_value=0)
    map_version = serializers.CharField(max_length=50, required=False, default="1")
    bot_version = serializers.CharField(max_length=50, required=False, default="1")
    rng_seed = serializers.IntegerField(required=False, allow_null=True)
    turn_events = TurnEventInputSerializer(many=True)

    def validate_student_id(self, value):
        """Verify student exists (expects prefixed string ID like 'stu_abc123...')."""
        if not Student.objects.filter(pk=value).exists():
            raise serializers.ValidationError(f"Student with id {value} does not exist")
        return value

    def validate_turn_events(self, value):
        """Validate turn events are properly ordered."""
        if not value:
            return value

        # Check turn indices are sequential starting from 0
        indices = [event["turn_index"] for event in value]
        expected = list(range(len(value)))

        if sorted(indices) != expected:
            raise serializers.ValidationError(
                "Turn indices must be sequential starting from 0"
            )

        # Check chain indices within each turn
        for event in value:
            triggers = event.get("special_tile_triggers", [])
            if triggers:
                chain_indices = [t["chain_index"] for t in triggers]
                expected_chain = list(range(len(triggers)))
                if sorted(chain_indices) != expected_chain:
                    raise serializers.ValidationError(
                        f"Chain indices for turn {event['turn_index']} must be sequential starting from 0"
                    )

        return value

    def validate(self, data):
        """Cross-field validation."""
        total_turns = len(data.get("turn_events", []))
        reported_moves = data["correct_moves"] + data["wrong_moves"]

        if total_turns != reported_moves:
            raise serializers.ValidationError(
                f"Turn count ({total_turns}) does not match correct_moves + wrong_moves ({reported_moves})"
            )

        return data


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


# ==================== Unity Payload Input Serializers ====================
# These serializers match the exact camelCase field names from Unity's C# classes


class UnityTileSnapshotSerializer(serializers.Serializer):
    """
    Validates TileSnapshot from Unity.
    C# fields: tileMapIndex, tileIndex, tileType, special, special_delta
    """

    tileMapIndex = serializers.IntegerField(min_value=0)  # Position on the map
    tileIndex = serializers.IntegerField(min_value=0)  # Texture tile index (0-6)
    tileType = serializers.IntegerField(
        required=False
    )  # Enum value (derived from tileIndex)
    special = serializers.CharField(
        max_length=20, required=False, default="normal"
    )  # "skateboard", "clown", "normal"
    special_delta = serializers.IntegerField(required=False, default=0)  # 5, -3, 0


class UnityPlayerPositionSnapshotSerializer(serializers.Serializer):
    """
    Validates PlayerPositionSnapshot from Unity.
    C# fields: placeRelativeToBots, tileMapIndex
    """

    placeRelativeToBots = serializers.IntegerField(min_value=1)  # 1st, 2nd, 3rd, 4th
    tileMapIndex = serializers.IntegerField(min_value=0)  # Where player is on the map


class UnityBotPositionSnapshotSerializer(serializers.Serializer):
    """
    Validates BotPositionSnapshot from Unity.
    C# fields: tileMapIndex, botID
    """

    tileMapIndex = serializers.IntegerField(min_value=0)
    botID = serializers.CharField(max_length=50)


class UnitySpecialTileTriggerSerializer(serializers.Serializer):
    """
    Validates SpecialTileTriggerData from Unity.
    C# fields: chainIndex, specialTile, positionOnSpecialTile, effectDeltaTiles, positionAfterEffect
    """

    chainIndex = serializers.IntegerField(min_value=0)
    specialTile = UnityTileSnapshotSerializer()  # The tile that triggered the effect
    positionOnSpecialTile = (
        UnityPlayerPositionSnapshotSerializer()
    )  # Player position when stepping on it
    effectDeltaTiles = serializers.IntegerField()  # +5 for skateboard, -3 for clown
    positionAfterEffect = (
        UnityPlayerPositionSnapshotSerializer()
    )  # Player position after effect


class UnityTurnEventSerializer(serializers.Serializer):
    """
    Validates TurnEventData from Unity.
    C# fields match exactly.
    """

    runId = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )  # Ignored
    turnIndex = serializers.IntegerField(min_value=0)
    timestampPlayedUnixMs = serializers.IntegerField()
    chosenCard = serializers.DictField()
    wasCorrect = serializers.BooleanField()
    offeredCards = serializers.ListField(child=serializers.DictField())
    playerPositionBefore = UnityPlayerPositionSnapshotSerializer()
    playerPositionAfter = UnityPlayerPositionSnapshotSerializer()
    botPositionsBefore = UnityBotPositionSnapshotSerializer(
        many=True, required=False, default=list
    )
    botPositionsAfter = UnityBotPositionSnapshotSerializer(
        many=True, required=False, default=list
    )
    tileBefore = UnityTileSnapshotSerializer()
    cardDecisionTimeMs = serializers.IntegerField(min_value=0)
    offeredNumbers = serializers.ListField(
        child=serializers.IntegerField(), required=False, default=list
    )
    chosenNumber = serializers.IntegerField(required=False, allow_null=True, default=-1)
    numberDecisionTimeMs = serializers.IntegerField(
        required=False, allow_null=True, default=-1
    )
    specialTileTriggers = UnitySpecialTileTriggerSerializer(
        many=True, required=False, default=list
    )

    def validate_chosenNumber(self, value):
        """Convert -1 sentinel to None."""
        if value == -1:
            return None
        return value

    def validate_numberDecisionTimeMs(self, value):
        """Convert -1 sentinel to None."""
        if value == -1:
            return None
        return value


class UnityMapForRunSerializer(serializers.Serializer):
    """
    Validates MapForRun from Unity.
    C# fields: mapTiles (List<TileSnapshot>)
    """

    mapTiles = UnityTileSnapshotSerializer(many=True)


class UnityRunEventSerializer(serializers.Serializer):
    """
    Validates RunEventData from Unity.
    C# fields: runId, level, score, place, correct_moves, wrong_moves,
               runStartedUnixMs, runEndedUnixMs, turns, gameMap
    """

    runId = serializers.CharField(
        max_length=100, required=False, allow_blank=True
    )  # Ignored - Django generates
    level = serializers.IntegerField(min_value=0)  # Level number
    score = serializers.IntegerField(min_value=0)  # Final score from Unity
    place = serializers.IntegerField(
        min_value=1, max_value=4
    )  # Final place (1st, 2nd, 3rd, 4th)
    correct_moves = serializers.IntegerField(
        min_value=0
    )  # Correct moves count from Unity
    wrong_moves = serializers.IntegerField(min_value=0)  # Wrong moves count from Unity
    runStartedUnixMs = serializers.IntegerField()  # Unix ms
    runEndedUnixMs = serializers.IntegerField()  # Unix ms
    turns = UnityTurnEventSerializer(many=True)
    gameMap = UnityMapForRunSerializer()  # The game map for this run

    def validate_turns(self, value):
        """Validate turn events are properly ordered."""
        if not value:
            return value

        # Check turn indices are sequential starting from 0
        indices = [event["turnIndex"] for event in value]
        expected = list(range(len(value)))

        if sorted(indices) != expected:
            raise serializers.ValidationError(
                "Turn indices must be sequential starting from 0"
            )

        # Check chain indices within each turn
        for event in value:
            triggers = event.get("specialTileTriggers", [])
            if triggers:
                chain_indices = [t["chainIndex"] for t in triggers]
                expected_chain = list(range(len(triggers)))
                if sorted(chain_indices) != expected_chain:
                    raise serializers.ValidationError(
                        f"Chain indices for turn {event['turnIndex']} must be sequential starting from 0"
                    )

        return value


class UnityRunUploadPayloadSerializer(serializers.Serializer):
    """
    Main serializer for Unity run upload payload.
    Matches the RunUploadPayload C# class from Unity.

    Expected payload:
    {
        "classroomKey": "ABC123",
        "user": "Student Name",
        "userID": "stu_abc123def456",
        "run": { ... RunEventData ... }
    }
    """

    classroomKey = serializers.CharField(max_length=100)
    user = serializers.CharField(max_length=255)  # Student full name
    userID = serializers.CharField(max_length=20)  # Prefixed student ID (stu_xxx)
    run = UnityRunEventSerializer()

    def validate_userID(self, value):
        """Verify student exists by prefixed ID."""
        if not Student.objects.filter(pk=value).exists():
            raise serializers.ValidationError(f"Student with id {value} does not exist")
        return value

    def validate(self, data):
        """Cross-field validation."""
        run_data = data.get("run", {})
        turns = run_data.get("turns", [])

        # Verify Unity-provided correct/wrong moves match turn data
        correct_from_turns = sum(1 for t in turns if t["wasCorrect"])
        wrong_from_turns = sum(1 for t in turns if not t["wasCorrect"])

        # -1 because Unity counts the last turn
        adjustable_correct_moves = 0

        if run_data["place"] == 1:
            adjustable_correct_moves = run_data["correct_moves"] - 1
        else:
            adjustable_correct_moves = run_data["correct_moves"]

        if adjustable_correct_moves != correct_from_turns:
            raise serializers.ValidationError(
                f"correct_moves mismatch: Unity says {run_data['correct_moves']} but turns show {correct_from_turns}"
            )

        if run_data["wrong_moves"] != wrong_from_turns:
            raise serializers.ValidationError(
                f"wrong_moves mismatch: Unity says {run_data['wrong_moves']} but turns show {wrong_from_turns}"
            )

        return data
