"""
Structured evaluation dataset schema for SecureLink V4.

Supports:
- Single-utterance text classification scenarios
- Multi-turn conversational scenarios with timestamps and speaker roles
- Audio transcription and end-to-end audio-to-incident scenarios (with optional WAV fixtures)
- Separate development (`dev`) and held-out (`held_out`) evaluation splits
"""

from __future__ import annotations

import json
from enum import Enum
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from pydantic import BaseModel, Field, model_validator


class SplitType(str, Enum):
    DEV = "dev"
    HELD_OUT = "held_out"


class EvaluationMode(str, Enum):
    TEXT = "text"
    MULTI_TURN = "multi_turn"
    AUDIO = "audio"
    END_TO_END = "end_to_end"


class LanguageCode(str, Enum):
    TL = "tl"
    EN = "en"
    TAGLISH = "taglish"
    SILENCE = "silence"
    NOISE = "noise"


class TurnItem(BaseModel):
    """A single conversational turn inside a multi-turn scenario."""
    utterance: str = Field(..., description="Spoken text for this turn.")
    timestamp_offset_sec: float = Field(
        default=0.0, ge=0.0, description="Seconds elapsed since start of scenario."
    )
    speaker_role: str = Field(
        default="unknown",
        description="Optional speaker role (e.g., peer, aggressor, wearer, bystander, unknown).",
    )
    expected_intent: Optional[str] = Field(
        default=None, description="Expected ThreatIntent value for this turn."
    )
    expected_level: Optional[str] = Field(
        default=None, description="Expected IncidentLevel (NORMAL, WARNING, THREAT, DANGER)."
    )
    provisional_severity: Optional[float] = Field(
        default=None, ge=0.0, le=10.0, description="Provisional reference severity (0-10)."
    )
    provisional_severity_range: Optional[Tuple[float, float]] = Field(
        default=None, description="Acceptable [min, max] severity band for this turn."
    )
    expected_review_required: Optional[bool] = Field(
        default=None, description="Whether human review should be flagged for this turn."
    )
    is_friendly_teasing: bool = False
    is_serious_threat: bool = False


class EvalScenario(BaseModel):
    """A single isolated evaluation scenario (single utterance, multi-turn, or audio)."""
    id: str = Field(..., min_length=1, description="Unique scenario identifier.")
    split: SplitType = Field(..., description="Dataset partition: dev or held_out.")
    mode: EvaluationMode = Field(..., description="Evaluation mode for this scenario.")
    language: LanguageCode = Field(default=LanguageCode.TAGLISH)
    conversational_context: str = Field(
        default="",
        description="Human-readable situational context (e.g., friendly banter, hallway intimidation).",
    )

    # Text / multi-turn inputs
    utterance: Optional[str] = Field(
        default=None, description="Single utterance text (for text mode)."
    )
    turns: List[TurnItem] = Field(
        default_factory=list, description="Ordered conversational turns (for multi_turn mode)."
    )

    # Audio / ASR inputs & reference
    audio_path: Optional[str] = Field(
        default=None,
        description="Relative (to repo root) or absolute path to 16kHz 16-bit mono WAV fixture.",
    )
    reference_transcript: Optional[str] = Field(
        default=None, description="Ground-truth reference transcript for WER/CER evaluation."
    )
    expected_transcription_status: Optional[str] = Field(
        default=None,
        description="Optional expected TranscriptionStatus (e.g., TRANSCRIBED, NO_SPEECH, UNCERTAIN_TRANSCRIPTION).",
    )
    critical_words: List[str] = Field(
        default_factory=list,
        description="Threat/bullying keywords that must be preserved by ASR.",
    )
    negation_words: List[str] = Field(
        default_factory=list,
        description="Negation/disclaimer tokens (e.g., hindi, di, not, won't) that must be preserved by ASR.",
    )

    # Detection & severity expectations (final turn for multi_turn)
    expected_intent: Optional[str] = Field(
        default=None, description="Expected ThreatIntent value (or AMBIGUOUS_CONTEXT for V4 targets)."
    )
    expected_level: Optional[str] = Field(
        default=None, description="Expected IncidentLevel (NORMAL, WARNING, THREAT, DANGER)."
    )
    provisional_severity: Optional[float] = Field(
        default=None, ge=0.0, le=10.0, description="Provisional severity score (0-10)."
    )
    provisional_severity_range: Optional[Tuple[float, float]] = Field(
        default=None, description="Acceptable [min, max] provisional severity band."
    )
    expected_review_required: Optional[bool] = Field(
        default=None, description="Whether human review is expected to be flagged."
    )

    # Safety-slice flags
    is_friendly_teasing: bool = Field(
        default=False,
        description="True when utterance represents friendly banter/teasing that should not trigger THREAT/DANGER.",
    )
    is_serious_threat: bool = Field(
        default=False,
        description="True when scenario represents a credible serious threat/extortion/coercion that must not be suppressed.",
    )

    tags: List[str] = Field(default_factory=list)
    notes: str = Field(default="")

    @model_validator(mode="after")
    def validate_mode_inputs(self) -> "EvalScenario":
        if self.mode == EvaluationMode.TEXT and not self.utterance:
            raise ValueError(f"Scenario '{self.id}' (text) requires 'utterance'.")
        if self.mode == EvaluationMode.MULTI_TURN and len(self.turns) < 2:
            raise ValueError(f"Scenario '{self.id}' (multi_turn) requires at least 2 'turns'.")
        if self.mode in (EvaluationMode.AUDIO, EvaluationMode.END_TO_END) and not self.audio_path:
            raise ValueError(f"Scenario '{self.id}' ({self.mode.value}) requires 'audio_path'.")
        if self.provisional_severity_range is not None:
            lo, hi = self.provisional_severity_range
            if lo < 0.0 or hi > 10.0 or lo > hi:
                raise ValueError(
                    f"Scenario '{self.id}' has invalid provisional_severity_range {(lo, hi)}."
                )
        return self


class EvalDataset(BaseModel):
    """Top-level evaluation dataset container."""
    schema_version: str = Field(default="1.0.0")
    dataset_name: str
    split: SplitType
    description: str = ""
    scenarios: List[EvalScenario] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_unique_ids_and_split(self) -> "EvalDataset":
        seen = set()
        for sc in self.scenarios:
            if sc.id in seen:
                raise ValueError(f"Duplicate scenario id '{sc.id}' in dataset '{self.dataset_name}'.")
            seen.add(sc.id)
            if sc.split != self.split:
                raise ValueError(
                    f"Scenario '{sc.id}' split '{sc.split.value}' does not match dataset split '{self.split.value}'."
                )
        return self


def load_dataset(path: str | Path) -> EvalDataset:
    """Load and validate an EvalDataset from a JSON file."""
    p = Path(path)
    if not p.exists():
        raise FileNotFoundError(f"Evaluation dataset not found: {p}")
    with p.open("r", encoding="utf-8") as f:
        raw = json.load(f)
    return EvalDataset.model_validate(raw)


def verify_split_isolation(dev_dataset: EvalDataset, held_out_dataset: EvalDataset) -> Dict[str, List[str]]:
    """
    Verify zero ID overlap and zero exact utterance/transcript leakage between dev and held_out datasets.
    Returns dict with 'overlapping_ids' and 'overlapping_texts'.
    """
    dev_ids = {s.id for s in dev_dataset.scenarios}
    held_ids = {s.id for s in held_out_dataset.scenarios}
    overlapping_ids = sorted(dev_ids & held_ids)

    def _extract_texts(ds: EvalDataset) -> set[str]:
        texts: set[str] = set()
        for s in ds.scenarios:
            if s.utterance and s.utterance.strip():
                texts.add(s.utterance.strip().lower())
            if s.reference_transcript and s.reference_transcript.strip():
                texts.add(s.reference_transcript.strip().lower())
            for t in s.turns:
                if t.utterance.strip():
                    texts.add(t.utterance.strip().lower())
        return texts

    overlapping_texts = sorted(_extract_texts(dev_dataset) & _extract_texts(held_out_dataset))
    return {
        "overlapping_ids": overlapping_ids,
        "overlapping_texts": overlapping_texts,
    }
