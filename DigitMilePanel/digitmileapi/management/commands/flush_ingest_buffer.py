"""
Flush the Redis ingest buffer into PostgreSQL in batches.

Usage:
    python manage.py flush_ingest_buffer
    python manage.py flush_ingest_buffer --batch-size 100 --sleep-ms 50

Runs in a loop. Reads up to --batch-size items from the Redis ingest buffer,
bulk-creates Run + TurnEvent + SpecialTileTrigger objects in one transaction,
then sleeps for --sleep-ms milliseconds before the next iteration.
"""

import json
import logging
import time

import redis as redis_client
from django.conf import settings
from django.core.management.base import BaseCommand
from django.db import transaction

from digitmileapi.models import Run, SpecialTileTrigger, TurnEvent
from digitmileapi.run_ingestion import unix_ms_to_datetime
from digitmileapi.views import _extract_card_metadata, _normalize_cards_for_ingestion

logger = logging.getLogger(__name__)


class Command(BaseCommand):
    help = "Flush the Redis ingest buffer into PostgreSQL in batches."

    def add_arguments(self, parser):
        parser.add_argument(
            "--batch-size",
            type=int,
            default=settings.INGEST_BUFFER_BATCH_SIZE,
        )
        parser.add_argument(
            "--sleep-ms",
            type=int,
            default=settings.INGEST_BUFFER_SLEEP_MS,
        )

    def handle(self, *args, **options):
        batch_size = options["batch_size"]
        sleep_s = options["sleep_ms"] / 1000.0
        r = redis_client.from_url(settings.REDIS_URL)
        logger.info(
            "Flusher started: batch_size=%d, sleep_ms=%d",
            batch_size,
            options["sleep_ms"],
        )

        while True:
            flushed = self._flush_batch(r, batch_size)
            if flushed == 0:
                time.sleep(sleep_s)

    def _flush_batch(self, r, batch_size):
        # Atomic pop of up to batch_size items
        pipe = r.pipeline()
        pipe.lrange(settings.INGEST_BUFFER_REDIS_KEY, 0, batch_size - 1)
        pipe.ltrim(settings.INGEST_BUFFER_REDIS_KEY, batch_size, -1)
        results = pipe.execute()
        raw_items = results[0]

        if not raw_items:
            return 0

        payloads = [json.loads(item) for item in raw_items]

        # Deduplicate within batch + against DB
        run_ids = [p["run_id"] for p in payloads]
        existing_ids = set(
            str(rid)
            for rid in Run.objects.filter(id__in=run_ids).values_list("id", flat=True)
        )
        seen = set()
        unique_payloads = []
        for p in payloads:
            rid = str(p["run_id"])
            if rid not in existing_ids and rid not in seen:
                seen.add(rid)
                unique_payloads.append(p)

        if not unique_payloads:
            return len(payloads)  # All duplicates, nothing to insert

        try:
            with transaction.atomic():
                # Bulk-create Run objects
                run_objects = [
                    Run(
                        id=p["run_id"],
                        student_id=p["student_id"],
                        level=p["level"],
                        player_won=p["player_won"],
                        score=p["score"],
                        place=p.get("place", 1 if p["player_won"] else 4),
                        elapsed_ms=p["elapsed_ms"],
                        correct_moves=p["correct_moves"],
                        wrong_moves=p["wrong_moves"],
                        game_map=p.get("game_map", []),
                        map_version=p.get("map_version", "1"),
                        bot_version=p.get("bot_version", "1"),
                        rng_seed=p.get("rng_seed"),
                    )
                    for p in unique_payloads
                ]
                created_runs = Run.objects.bulk_create(run_objects)
                run_by_id = {str(r.id): r for r in created_runs}

                # Bulk-create TurnEvent objects across all runs in the batch
                all_turn_events = []
                all_trigger_sources = {}  # (run_id, turn_index) -> list of trigger dicts

                for p in unique_payloads:
                    run_obj = run_by_id[str(p["run_id"])]
                    for event_data in p.get("turn_events", []):
                        timestamp_played = unix_ms_to_datetime(
                            event_data["timestamp_played_unix_ms"]
                        )
                        chosen_card, offered_cards = _normalize_cards_for_ingestion(
                            event_data.get("chosen_card"),
                            event_data.get("offered_cards"),
                        )
                        ctype, cfamily, ctile = _extract_card_metadata(chosen_card)

                        te = TurnEvent(
                            run=run_obj,
                            turn_index=event_data["turn_index"],
                            timestamp_played=timestamp_played,
                            chosen_card=chosen_card,
                            chosen_card_type=ctype,
                            chosen_card_family=cfamily,
                            chosen_card_tile_type=ctile,
                            offered_cards=offered_cards,
                            was_correct=event_data["was_correct"],
                            tile_before_index=event_data["tile_before_index"],
                            tile_before_type=event_data["tile_before_type"],
                            tile_after_index=event_data["tile_after_index"],
                            place_before=event_data["place_before"],
                            place_after=event_data["place_after"],
                            bot_positions_before=event_data.get(
                                "bot_positions_before", []
                            ),
                            bot_positions_after=event_data.get(
                                "bot_positions_after", []
                            ),
                            card_decision_time_ms=event_data["card_decision_time_ms"],
                            offered_numbers=event_data.get("offered_numbers", []),
                            chosen_number=event_data.get("chosen_number"),
                            number_decision_time_ms=event_data.get(
                                "number_decision_time_ms"
                            ),
                        )
                        all_turn_events.append(te)

                        triggers = event_data.get("special_tile_triggers", [])
                        if triggers:
                            all_trigger_sources[
                                (str(p["run_id"]), event_data["turn_index"])
                            ] = triggers

                created_turns = TurnEvent.objects.bulk_create(all_turn_events)

                # Build trigger objects using the created TurnEvent PKs
                turn_lookup = {
                    (str(te.run_id), te.turn_index): te for te in created_turns
                }

                all_triggers = []
                for (run_id, turn_index), trigger_list in all_trigger_sources.items():
                    te = turn_lookup[(run_id, turn_index)]
                    for td in trigger_list:
                        all_triggers.append(
                            SpecialTileTrigger(
                                turn=te,
                                chain_index=td["chain_index"],
                                special_tile_index=td["special_tile_index"],
                                special_tile_type=td["special_tile_type"],
                                effect_delta_tiles=td["effect_delta_tiles"],
                                target_tile_index=td["target_tile_index"],
                                target_tile_type=td["target_tile_type"],
                                place_before=td["place_before"],
                                place_after=td["place_after"],
                            )
                        )

                if all_triggers:
                    SpecialTileTrigger.objects.bulk_create(all_triggers)

            logger.info(
                "Flushed %d runs (%d turns, %d triggers)",
                len(created_runs),
                len(created_turns),
                len(all_triggers),
            )
            return len(payloads)

        except Exception:
            logger.exception("Flusher batch failed — items returned to queue")
            # Push failed items back to the RIGHT side (tail) so they retry
            pipe = r.pipeline()
            for item in raw_items:
                pipe.rpush(settings.INGEST_BUFFER_REDIS_KEY, item)
            pipe.execute()
            return 0
