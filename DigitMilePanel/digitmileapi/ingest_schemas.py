from __future__ import annotations

from typing import Any, Optional

from pydantic import BaseModel, Field, field_validator, model_validator

from .run_ingestion import clamp_elapsed_ms


# ==================== Unity camelCase schemas ====================


class UnityTileSnapshot(BaseModel):
    tileMapIndex: int = Field(ge=0)
    tileIndex: int = Field(ge=0)
    tileType: Optional[int] = None
    special: str = "normal"
    special_delta: int = 0


class UnityPlayerPositionSnapshot(BaseModel):
    placeRelativeToBots: int = Field(ge=1)
    tileMapIndex: int = Field(ge=0)


class UnityBotPositionSnapshot(BaseModel):
    tileMapIndex: int = Field(ge=0)
    botID: str


class UnitySpecialTileTrigger(BaseModel):
    chainIndex: int = Field(ge=0)
    specialTile: UnityTileSnapshot
    positionOnSpecialTile: UnityPlayerPositionSnapshot
    effectDeltaTiles: int
    positionAfterEffect: UnityPlayerPositionSnapshot


class UnityTurnEvent(BaseModel):
    runId: Optional[str] = None
    turnIndex: int = Field(ge=0)
    timestampPlayedUnixMs: int
    chosenCard: dict[str, Any]
    wasCorrect: bool
    offeredCards: list[dict[str, Any]] = []
    playerPositionBefore: UnityPlayerPositionSnapshot
    playerPositionAfter: UnityPlayerPositionSnapshot
    botPositionsBefore: list[UnityBotPositionSnapshot] = []
    botPositionsAfter: list[UnityBotPositionSnapshot] = []
    tileBefore: UnityTileSnapshot
    cardDecisionTimeMs: int = Field(ge=0)
    offeredNumbers: list[int] = []
    chosenNumber: Optional[int] = None
    numberDecisionTimeMs: Optional[int] = None
    specialTileTriggers: list[UnitySpecialTileTrigger] = []

    @field_validator("chosenNumber", mode="before")
    @classmethod
    def _sentinel_chosen_number(cls, v: Any) -> Optional[int]:
        return None if v == -1 else v

    @field_validator("numberDecisionTimeMs", mode="before")
    @classmethod
    def _sentinel_number_dt(cls, v: Any) -> Optional[int]:
        return None if v == -1 else v


class UnityMapForRun(BaseModel):
    mapTiles: list[UnityTileSnapshot]


class UnityRunEvent(BaseModel):
    runId: Optional[str] = None
    level: int = Field(ge=0)
    score: int = Field(ge=0)
    place: int = Field(ge=1, le=4)
    correct_moves: int = Field(ge=0)
    wrong_moves: int = Field(ge=0)
    runStartedUnixMs: int
    runEndedUnixMs: int
    turns: list[UnityTurnEvent]
    gameMap: UnityMapForRun


class UnityIngestPayload(BaseModel):
    classroomKey: str
    user: str
    userID: str
    run: UnityRunEvent

    @model_validator(mode="after")
    def _validate_moves_and_indices(self) -> "UnityIngestPayload":
        run = self.run
        turns = run.turns
        correct_from_turns = sum(1 for t in turns if t.wasCorrect)
        wrong_from_turns = len(turns) - correct_from_turns

        adj = run.correct_moves - 1 if run.place == 1 else run.correct_moves
        if adj != correct_from_turns:
            raise ValueError(
                f"correct_moves mismatch: Unity says {run.correct_moves} but turns show {correct_from_turns}"
            )
        if run.wrong_moves != wrong_from_turns:
            raise ValueError(
                f"wrong_moves mismatch: Unity says {run.wrong_moves} but turns show {wrong_from_turns}"
            )

        indices = [t.turnIndex for t in turns]
        if sorted(indices) != list(range(len(turns))):
            raise ValueError("Turn indices must be sequential starting from 0")

        for t in turns:
            if t.specialTileTriggers:
                chain_indices = [tr.chainIndex for tr in t.specialTileTriggers]
                if sorted(chain_indices) != list(range(len(t.specialTileTriggers))):
                    raise ValueError(
                        f"Chain indices for turn {t.turnIndex} must be sequential starting from 0"
                    )

        return self


# ==================== Canonical snake_case schemas ====================


class SpecialTileTriggerInput(BaseModel):
    chain_index: int = Field(ge=0)
    special_tile_index: int = Field(ge=0)
    special_tile_type: int
    effect_delta_tiles: int
    target_tile_index: int = Field(ge=0)
    target_tile_type: int
    place_before: int = Field(ge=1)
    place_after: int = Field(ge=1)


class TurnEventInput(BaseModel):
    turn_index: int = Field(ge=0)
    timestamp_played_unix_ms: int
    chosen_card: dict[str, Any]
    offered_cards: list[dict[str, Any]] = []
    was_correct: bool
    tile_before_index: int = Field(ge=0)
    tile_before_type: int
    tile_after_index: int = Field(ge=0)
    place_before: int = Field(ge=1)
    place_after: int = Field(ge=1)
    bot_positions_before: list[dict[str, Any]] = []
    bot_positions_after: list[dict[str, Any]] = []
    card_decision_time_ms: int = Field(ge=0)
    offered_numbers: list[int] = []
    chosen_number: Optional[int] = None
    number_decision_time_ms: Optional[int] = None
    special_tile_triggers: list[SpecialTileTriggerInput] = []

    @field_validator("chosen_number", mode="before")
    @classmethod
    def _sentinel_chosen_number(cls, v: Any) -> Optional[int]:
        return None if v == -1 else v

    @field_validator("number_decision_time_ms", mode="before")
    @classmethod
    def _sentinel_number_dt(cls, v: Any) -> Optional[int]:
        return None if v == -1 else v


class CanonicalIngestPayload(BaseModel):
    run_id: str = Field(max_length=36)
    student_id: str = Field(max_length=16)
    level: int = Field(ge=1)
    player_won: Optional[bool] = None
    score: int = Field(ge=0)
    place: Optional[int] = Field(default=None, ge=1, le=4)
    elapsed_ms: Optional[int] = Field(default=None, ge=0)
    run_started_unix_ms: Optional[int] = None
    run_ended_unix_ms: Optional[int] = None
    correct_moves: int = Field(ge=0)
    wrong_moves: int = Field(ge=0)
    game_map: list[dict[str, Any]] = []
    map_version: str = "1"
    bot_version: str = "1"
    rng_seed: Optional[int] = None
    turn_events: list[TurnEventInput]

    @model_validator(mode="after")
    def _validate_cross_fields(self) -> "CanonicalIngestPayload":
        # Elapsed ms derivation
        if self.elapsed_ms is None:
            if self.run_started_unix_ms is not None and self.run_ended_unix_ms is not None:
                self.elapsed_ms = clamp_elapsed_ms(
                    self.run_started_unix_ms, self.run_ended_unix_ms
                )
            else:
                raise ValueError(
                    "Either elapsed_ms or run_started_unix_ms/run_ended_unix_ms must be provided"
                )

        # player_won from place
        if self.place is not None:
            derived = self.place == 1
            if self.player_won is not None and self.player_won != derived:
                raise ValueError("player_won must match the value derived from place")
            self.player_won = derived
        elif self.player_won is None:
            raise ValueError("Either player_won or place must be provided")

        # Moves count validation
        turns = self.turn_events
        total = len(turns)
        correct_from_turns = sum(1 for t in turns if t.was_correct)
        wrong_from_turns = total - correct_from_turns

        if self.place is not None:
            adj = self.correct_moves - 1 if self.place == 1 else self.correct_moves
            if adj != correct_from_turns:
                raise ValueError(
                    f"correct_moves mismatch: reported {self.correct_moves} but turns show {correct_from_turns}"
                )
            if self.wrong_moves != wrong_from_turns:
                raise ValueError(
                    f"wrong_moves mismatch: reported {self.wrong_moves} but turns show {wrong_from_turns}"
                )
        else:
            reported = self.correct_moves + self.wrong_moves
            if total != reported:
                raise ValueError(
                    f"Turn count ({total}) does not match correct_moves + wrong_moves ({reported})"
                )

        # Turn indices must be sequential starting from 0
        indices = [t.turn_index for t in turns]
        if sorted(indices) != list(range(total)):
            raise ValueError("Turn indices must be sequential starting from 0")

        # Chain indices per turn must be sequential starting from 0
        for t in turns:
            if t.special_tile_triggers:
                chain_indices = [tr.chain_index for tr in t.special_tile_triggers]
                if sorted(chain_indices) != list(range(len(t.special_tile_triggers))):
                    raise ValueError(
                        f"Chain indices for turn {t.turn_index} must be sequential starting from 0"
                    )

        return self
