import gzip
import hashlib
import json
from collections import defaultdict
from pathlib import Path

from django.conf import settings
from django.utils import timezone

from .models import ReplayArchive, SpecialTileTrigger, TurnEvent


def archive_relative_path(run_id, archived_at=None):
    archived_at = archived_at or timezone.now()
    return (
        Path(str(archived_at.year)) / f"{archived_at.month:02d}" / f"{run_id}.json.gz"
    )


def archive_absolute_path(relative_path):
    return Path(settings.REPLAY_ARCHIVE_ROOT) / relative_path


def compute_sha256(content_bytes):
    return hashlib.sha256(content_bytes).hexdigest()


def build_replay_payload(run):
    turns_queryset = TurnEvent.objects.filter(run=run).order_by("turn_index")
    triggers = SpecialTileTrigger.objects.filter(turn__run=run).values(
        "turn__turn_index",
        "chain_index",
        "special_tile_index",
        "special_tile_type",
        "effect_delta_tiles",
        "target_tile_index",
        "target_tile_type",
        "place_before",
        "place_after",
    )

    triggers_by_turn = defaultdict(list)
    for trigger in triggers:
        turn_index = trigger["turn__turn_index"]
        triggers_by_turn[turn_index].append(
            {
                "chain_index": trigger["chain_index"],
                "special_tile_index": trigger["special_tile_index"],
                "special_tile_type": trigger["special_tile_type"],
                "effect_delta_tiles": trigger["effect_delta_tiles"],
                "target_tile_index": trigger["target_tile_index"],
                "target_tile_type": trigger["target_tile_type"],
                "place_before": trigger["place_before"],
                "place_after": trigger["place_after"],
            }
        )

    turns = []
    for turn in turns_queryset:
        turns.append(
            {
                "turn_index": turn.turn_index,
                "timestamp_played": turn.timestamp_played.isoformat(),
                "chosen_card": turn.chosen_card,
                "offered_cards": turn.offered_cards,
                "was_correct": turn.was_correct,
                "tile_before_index": turn.tile_before_index,
                "tile_before_type": turn.tile_before_type,
                "tile_after_index": turn.tile_after_index,
                "place_before": turn.place_before,
                "place_after": turn.place_after,
                "bot_positions_before": turn.bot_positions_before,
                "bot_positions_after": turn.bot_positions_after,
                "card_decision_time_ms": turn.card_decision_time_ms,
                "offered_numbers": turn.offered_numbers,
                "chosen_number": turn.chosen_number,
                "number_decision_time_ms": turn.number_decision_time_ms,
                "special_triggers": triggers_by_turn.get(turn.turn_index, []),
            }
        )

    return {
        "schema_version": 1,
        "archived_at": timezone.now().isoformat(),
        "run": {
            "run_id": run.id,
            "student_id": run.student_id,
            "student_name": run.student.full_name,
            "classroom_id": run.student.classroom_id,
            "level": run.level,
            "player_won": run.player_won,
            "score": run.score,
            "place": run.place,
            "elapsed_ms": run.elapsed_ms,
            "correct_moves": run.correct_moves,
            "wrong_moves": run.wrong_moves,
            "created_at": run.created_at.isoformat(),
        },
        "game_map": run.game_map,
        "turns": turns,
    }


def serialize_payload(payload):
    return json.dumps(payload, separators=(",", ":"), sort_keys=True).encode("utf-8")


def write_replay_archive(run):
    payload = build_replay_payload(run)
    payload_bytes = serialize_payload(payload)
    checksum = compute_sha256(payload_bytes)
    archived_at = timezone.now()
    relative_path = archive_relative_path(run.id, archived_at=archived_at)
    absolute_path = archive_absolute_path(relative_path)
    absolute_path.parent.mkdir(parents=True, exist_ok=True)

    temp_path = absolute_path.with_suffix(absolute_path.suffix + ".tmp")
    with gzip.open(
        temp_path,
        "wb",
        compresslevel=settings.REPLAY_ARCHIVE_COMPRESSION_LEVEL,
    ) as handle:
        handle.write(payload_bytes)

    temp_path.replace(absolute_path)
    compressed_size = absolute_path.stat().st_size

    archive, _ = ReplayArchive.objects.get_or_create(run=run)
    archive.archive_status = ReplayArchive.ArchiveStatus.READY
    archive.archive_format = "json.gz"
    archive.archive_schema_version = payload["schema_version"]
    archive.storage_path = str(relative_path).replace("\\", "/")
    archive.compressed_size_bytes = compressed_size
    archive.uncompressed_size_bytes = len(payload_bytes)
    archive.checksum_sha256 = checksum
    archive.archived_at = archived_at
    archive.verification_error = ""
    archive.save()
    return archive


def load_archive_bytes(archive):
    archive_path = archive_absolute_path(archive.storage_path)
    with gzip.open(archive_path, "rb") as handle:
        return handle.read()


def load_archive_payload(archive):
    return json.loads(load_archive_bytes(archive).decode("utf-8"))


def replay_view_payload_from_archive_payload(payload):
    run_payload = payload["run"]
    return {
        "run_id": run_payload["run_id"],
        "student": run_payload["student_name"],
        "level": run_payload["level"],
        "player_won": run_payload["player_won"],
        "score": run_payload["score"],
        "place": run_payload["place"],
        "elapsed_ms": run_payload["elapsed_ms"],
        "correct_moves": run_payload["correct_moves"],
        "wrong_moves": run_payload["wrong_moves"],
        "game_map": payload.get("game_map", []),
        "turns": payload.get("turns", []),
    }


def verify_replay_archive(archive):
    archive_path = archive_absolute_path(archive.storage_path)
    if not archive_path.exists():
        archive.archive_status = ReplayArchive.ArchiveStatus.MISSING
        archive.verification_error = f"Archive file not found: {archive.storage_path}"
        archive.save(
            update_fields=["archive_status", "verification_error", "updated_at"]
        )
        return False

    payload_bytes = load_archive_bytes(archive)
    checksum = compute_sha256(payload_bytes)
    if checksum != archive.checksum_sha256:
        archive.archive_status = ReplayArchive.ArchiveStatus.CORRUPT
        archive.verification_error = "Checksum mismatch"
        archive.save(
            update_fields=["archive_status", "verification_error", "updated_at"]
        )
        return False

    archive.archive_status = ReplayArchive.ArchiveStatus.READY
    archive.verified_at = timezone.now()
    archive.verification_error = ""
    archive.save(
        update_fields=[
            "archive_status",
            "verified_at",
            "verification_error",
            "updated_at",
        ]
    )
    return True


def get_replay_payload_for_run(run):
    if run.raw_data_compacted_at and hasattr(run, "replay_archive"):
        return replay_view_payload_from_archive_payload(
            load_archive_payload(run.replay_archive)
        )

    payload = build_replay_payload(run)
    return replay_view_payload_from_archive_payload(payload)


def ensure_archive_root():
    Path(settings.REPLAY_ARCHIVE_ROOT).mkdir(parents=True, exist_ok=True)
