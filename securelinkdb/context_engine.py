"""
SecureLink Context Engine & Threat Severity Assessment System (V3)
=================================================================
A multi-stage, explainable, context-aware NLP threat evaluation engine
specifically designed for Philippine educational institutions.

Supports:
- Filipino/Tagalog, English, and Taglish code-switching
- Distinguishing direct threats, reported threats, quoted speech, past incidents,
  hypotheticals, negations, idioms, and verbal harassment
- Indirect school intimidation patterns (e.g. "Alam mo na mangyayari sa'yo mamaya")
- Device-isolated, time-bounded escalation tracking (no cross-device contamination)
- Normalized 0-10 severity scoring with backward-compatible (score, category) interface
"""

from __future__ import annotations

import re
import threading
import time
from collections import deque
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple, Union

from pydantic import BaseModel, Field


# =============================================================================
# ENUMS & DATA MODELS
# =============================================================================

class ThreatIntent(str, Enum):
    DIRECT_THREAT = "DIRECT_THREAT"
    REPORTED_THREAT = "REPORTED_THREAT"
    QUOTED_THREAT = "QUOTED_THREAT"
    PAST_INCIDENT = "PAST_INCIDENT"
    HYPOTHETICAL_THREAT = "HYPOTHETICAL_THREAT"
    NEGATED_THREAT = "NEGATED_THREAT"
    VERBAL_HARASSMENT = "VERBAL_HARASSMENT"
    BULLYING = "BULLYING"
    EXTORTION = "EXTORTION"
    COERCION = "COERCION"
    ORDINARY_CONVERSATION = "ORDINARY_CONVERSATION"
    UNKNOWN = "UNKNOWN"


class ThreatType(str, Enum):
    PHYSICAL_VIOLENCE = "PHYSICAL_VIOLENCE"
    EXTORTION = "EXTORTION"
    VERBAL_HARASSMENT = "VERBAL_HARASSMENT"
    COERCION = "COERCION"
    SOCIAL_INTIMIDATION = "SOCIAL_INTIMIDATION"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class Targetedness(str, Enum):
    DIRECT_SECOND_PERSON = "DIRECT_SECOND_PERSON"
    NAMED_INDIVIDUAL = "NAMED_INDIVIDUAL"
    GROUP_TARGETED = "GROUP_TARGETED"
    SELF_DIRECTED = "SELF_DIRECTED"
    UNTARGETED = "UNTARGETED"
    UNKNOWN = "UNKNOWN"


class Imminence(str, Enum):
    IMMEDIATE = "IMMEDIATE"                    # e.g., "ngayon na", "right now", weapon drawn
    FUTURE_SPECIFIC = "FUTURE_SPECIFIC"        # e.g., "mamaya sa gate", "pagkatapos ng klase"
    CONDITIONAL_FUTURE = "CONDITIONAL_FUTURE"  # e.g., "sa susunod na makita kita", "pag nagsumbong ka"
    PAST = "PAST"                              # e.g., "kahapon", "kanina", "last week"
    HYPOTHETICAL = "HYPOTHETICAL"              # e.g., "kung may kutsilyo lang ako", "napanaginipan ko"
    NONE = "NONE"
    UNKNOWN = "UNKNOWN"


class EvidenceReliability(str, Enum):
    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"
    UNCERTAIN = "UNCERTAIN"


class IncidentLevel(str, Enum):
    NORMAL = "NORMAL"      # 0.0 - 1.9
    WARNING = "WARNING"    # 2.0 - 3.9
    THREAT = "THREAT"      # 4.0 - 7.9
    DANGER = "DANGER"      # 8.0 - 10.0


class ContextExtraction(BaseModel):
    intent: ThreatIntent = ThreatIntent.ORDINARY_CONVERSATION
    threat_type: ThreatType = ThreatType.NONE
    targetedness: Targetedness = Targetedness.UNTARGETED
    target_reference: Optional[str] = None
    harmful_action: Optional[str] = None
    potential_harm: Optional[str] = None
    time_reference: Optional[str] = None
    location_reference: Optional[str] = None
    imminence: Imminence = Imminence.NONE
    specificity: str = "LOW"                   # HIGH, MEDIUM, LOW
    repetition: bool = False
    persistence: bool = False
    reported_speech: bool = False
    negated: bool = False
    evidence_reliability: EvidenceReliability = EvidenceReliability.HIGH
    model_confidence: float = 1.0


class SeverityAssessment(BaseModel):
    """
    Rich structured threat assessment output.
    Implements tuple protocol for 100% backward compatibility:
    `score, category = context_engine.evaluate(text)`
    """
    score: float
    level: str
    category: str
    intent: ThreatIntent
    threat_type: ThreatType
    targetedness: Targetedness
    imminence: Imminence
    risk_factors: List[str] = Field(default_factory=list)
    evidence_confidence: float = 1.0
    explanation: str = ""
    recommended_response: str = ""
    human_review_required: bool = False
    context: Optional[ContextExtraction] = None

    def __iter__(self):
        """Allows unpacking as (score, category) for legacy callers."""
        return iter((self.score, self.category))

    def __getitem__(self, idx: int):
        """Allows index-based tuple access [0]=score, [1]=category."""
        if idx == 0:
            return self.score
        elif idx == 1:
            return self.category
        raise IndexError("SeverityAssessment index out of range (expected 0 or 1)")

    def __len__(self) -> int:
        return 2


# =============================================================================
# LINGUISTIC PATTERNS & SCHOOL SCENARIO DICTIONARIES
# =============================================================================

# Idiomatic Tagalog expressions that contain threat/violence keywords but are completely benign
IDIOMATIC_NON_THREATS: List[Tuple[re.Pattern, str]] = [
    # Romantic / Attraction
    (re.compile(r"\bpatay\s+na\s+patay\b", re.IGNORECASE), "Romantic infatuation idiom ('patay na patay')"),
    (re.compile(r"\bmahal\s+(kita|ka|ko)\b", re.IGNORECASE), "Expression of affection ('mahal kita')"),
    (re.compile(r"\bcrush\s+(kita|ka|ko)\b", re.IGNORECASE), "Expression of attraction ('crush kita')"),
    (re.compile(r"\bi\s+love\s+you\b", re.IGNORECASE), "Expression of affection ('I love you')"),
    # Hyperbole / School Exaggeration
    (re.compile(r"\bnakakamatay\s+(yung|ang)?\s*(exam|test|quiz|project|homework|traffic|init|gutom|pagod)\b", re.IGNORECASE), "Academic or environmental hyperbole ('nakakamatay ang exam')"),
    (re.compile(r"\bmamatay\s+sa\s+(tawa|gutom|pagod)\b", re.IGNORECASE), "Colloquial hyperbole ('mamatay sa tawa')"),
    (re.compile(r"\bdying\s+of\s+(laughter|hunger)\b", re.IGNORECASE), "English hyperbole ('dying of laughter')"),
    # Sports / Academics determination
    (re.compile(r"\bbabawi\s+a?ko\s+(sa\s+susunod|next\s+time)\b", re.IGNORECASE), "Positive determination / promise to improve ('babawi ako sa susunod')"),
    # Banter / Reassurance
    (re.compile(r"\b(biro|joke|char|charot)\s+lang\b", re.IGNORECASE), "Explicit conversational humor / joke indicator"),
    (re.compile(r"\bwag\s+(ka\s+)?mag-?alala\b", re.IGNORECASE), "Conversational reassurance"),
    (re.compile(r"\bjust\s+kidding\b", re.IGNORECASE), "Conversational humor indicator"),
]

# Negation patterns (harm explicitly denied or disclaimed)
NEGATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(hindi|di|hinde)\s+(kita|ka|ko|namin|nila)?\s*(sasaktan|papatayin|aawayin|bubu?gbugin|susuntukin|sasapakin|tatadyakan|hihiwain|gagalawin)\b", re.IGNORECASE),
    re.compile(r"\b(hindi|di|hinde)\s+ako\s+(mananakit|mang-?aaway|magagalit)\b", re.IGNORECASE),
    re.compile(r"\bwala\s+(akong|kaming)\s+gagawing\s+masama\b", re.IGNORECASE),
    re.compile(r"\b(i\s+)?(will\s+not|won'?t|never|do\s+not|don'?t)\s+(hurt|kill|punch|beat|harm|touch)\s+(you|him|her|them)?\b", re.IGNORECASE),
]

# Reported speech markers (someone reporting what another person threatened)
REPORTED_SPEECH_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(sinabi|sabi|kwento)\s+(niya|nila|nung\s+isa|ng\s+lalaki|ng\s+babae)\s+na\b", re.IGNORECASE),
    re.compile(r"\b(sabi\s+(niya|nila)|sinabi\s+(niya|nila))\b", re.IGNORECASE),
    re.compile(r"\b(nagbanta|nagba-?banta)\s+(siya|sila)\s+na\b", re.IGNORECASE),
    re.compile(r"\b(papatayin|sasapakin|bubugbugin|aabangan|babarilin)\s+(daw|raw)\b", re.IGNORECASE),
    re.compile(r"\b(he|she|they|someone)\s+(said|told\s+me|threatened)\s+(that)?\b", re.IGNORECASE),
    re.compile(r"\bbalita\s+ko\s+na\b", re.IGNORECASE),
]

# Hypothetical or dream markers
HYPOTHETICAL_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bnapanaginipan\s+(kong?|ko\s+na)\b", re.IGNORECASE),
    re.compile(r"\bpanaginip\s+(ko\s+na|lang)\b", re.IGNORECASE),
    re.compile(r"\bdream(t|ed)\s+(that|about)\b", re.IGNORECASE),
    re.compile(r"\b(paano|pano)\s+kung\b", re.IGNORECASE),
    re.compile(r"\bwhat\s+if\b", re.IGNORECASE),
    re.compile(r"\bkunwari\s+lang\b", re.IGNORECASE),
    re.compile(r"\bkung\s+sakaling?\b", re.IGNORECASE),
]

# Past incident markers (reporting a historical event that already concluded)
PAST_INCIDENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(kahapon|kanina|noong\s+isang\s+linggo|nung\s+isang\s+araw|dati|last\s+week|yesterday|earlier)\b", re.IGNORECASE),
    re.compile(r"\b(sinapak|binugbog|sinuntok|tinadyakan|kinuha|hinoldap)\s+(ako|kami|siya|sila)\s+(kahapon|kanina|nung|dati)\b", re.IGNORECASE),
    re.compile(r"\bnamatay\s+(yung|ang|si)\s+\w+\s+(kahapon|kanina|dati|noong)\b", re.IGNORECASE),
]

# Extortion patterns (compelling payment or surrender of money/allowance)
EXTORTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bakin\s+na\s+(yang\s+|yung\s+)?(baon|pera|allowance|barya)\s*(mo)?\b", re.IGNORECASE),
    re.compile(r"\baraw-?araw\s+mo\s+(akong|kaming)\s+babayaran\b", re.IGNORECASE),
    re.compile(r"\b(ibigay|ilabas|iabot)\s+mo\s+(na\s+)?(yang\s+|yung\s+|ang\s+)?(pera|baon|gamit|allowance)\s*(mo)?\b", re.IGNORECASE),
    re.compile(r"\bmagbayad\s+ka\s+(sa\s+akin|sa\s+amin|araw-?araw)\b", re.IGNORECASE),
    re.compile(r"\b(give\s+me|hand\s+over|cough\s+up)\s+(your\s+|the\s+)?(money|lunch\s+money|allowance)\b", re.IGNORECASE),
    re.compile(r"\bpay\s+up\s+or\s+else\b", re.IGNORECASE),
]

# Coercion and secrecy enforcement patterns
COERCION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(huwag|wag)\s+mong\s+sabihin\s+sa\s+(teacher|guro|magulang|guidance|pulis|dean|nanay|tatay)\b", re.IGNORECASE),
    re.compile(r"\b(huwag|wag)\s+kang\s+mag-?susumbong\b", re.IGNORECASE),
    re.compile(r"\bpag\s+nag-?sumbong\s+ka\b", re.IGNORECASE),
    re.compile(r"\bsubukan\s+mong\s+mag-?sumbong\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+(dare\s+)?tell\s+(the\s+teacher|anyone|the\s+principal)\b", re.IGNORECASE),
    re.compile(r"\bif\s+you\s+(snitch|tell\s+anyone)\b", re.IGNORECASE),
]

# Indirect, veiled, and school-specific intimidation patterns
INDIRECT_INTIMIDATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\balam\s+mo\s+na\s+mangyayari\s+sa'?yo\s+mamaya\b", re.IGNORECASE),
    re.compile(r"\bmay\s+kakausap\s+sa'?yo\s+pagkatapos\s+ng\s+klase\b", re.IGNORECASE),
    re.compile(r"\bsa\s+susunod\s+na\s+makita\s+kita[,\s]+ewan\s+ko\s+na\s+lang\b", re.IGNORECASE),
    re.compile(r"\bhindi\s+pa\s+tayo\s+tapos\b", re.IGNORECASE),
    re.compile(r"\bdi\s+pa\s+tayo\s+tapos\b", re.IGNORECASE),
    re.compile(r"\ba?abangan\s+kita\s+(sa\s+labas|sa\s+gate|mamaya|paglabas)\b", re.IGNORECASE),
    re.compile(r"\bhumanda\s+ka\s+(sa\s+akin|mamaya|paglabas)\b", re.IGNORECASE),
    re.compile(r"\blagot\s+ka\s+(sa\s+akin|mamaya)\b", re.IGNORECASE),
    re.compile(r"\breresbakan\s+kita\b", re.IGNORECASE),
    re.compile(r"\bwait\s+until\s+(after\s+class|we\s+get\s+outside)\b", re.IGNORECASE),
    re.compile(r"\byou'?ll\s+regret\s+this\b", re.IGNORECASE),
]

# Direct physical violence threats (explicit intent to inflict serious harm/death)
DIRECT_PHYSICAL_THREAT_PATTERNS: List[re.Pattern] = [
    # Lethal / extreme harm
    re.compile(r"\b(papatayin|papatay|itutumba|liligpitin|kikitilin)\s+(kita|ka|kayo)\b", re.IGNORECASE),
    re.compile(r"\bi\s*(will|'ll)\s+(kill|murder)\s+you\b", re.IGNORECASE),
    re.compile(r"\b(sasaksakin|babarilin|tatagpasin)\s+(kita|ka)\b", re.IGNORECASE),
    re.compile(r"\bi\s*(will|'ll)\s+(stab|shoot)\s+you\b", re.IGNORECASE),
    # Battery / severe physical violence
    re.compile(r"\b(sasapakin|bubugbugin|susuntukin|tatadyakan|uupakan)\s+(kita|ka|kayo)\b", re.IGNORECASE),
    re.compile(r"\bi\s*(will|'ll)\s+(beat|punch|beat\s+up|break\s+your\s+face)\b", re.IGNORECASE),
]

# Targeted verbal harassment (insults, slurs, body shaming)
VERBAL_HARASSMENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(ang\s+)?(bobo|tanga|inutil|gago|tarantado|pangit|monggoloid|abnoy|siraulo|pabigat|palamunin|salot)\s+(mo|ka|nyo|ninyo)\b", re.IGNORECASE),
    re.compile(r"\b(bobo|inutil|tanga|gago|pangit)\s+(ka|mo)\b", re.IGNORECASE),
    re.compile(r"\b(tangina|putangina)\s+mo\b", re.IGNORECASE),
    re.compile(r"\bwalang\s+(kang|kayong)\s+(kwenta|kuwenta)\b", re.IGNORECASE),
    re.compile(r"\byou('re|\s+are)\s+(so\s+)?(stupid|an\s+idiot|ugly|a\s+loser|worthless|a\s+freak)\b", re.IGNORECASE),
    re.compile(r"\bshut\s+up[,\s]+(idiot|loser|ugly)\b", re.IGNORECASE),
]

# Untargeted profanities / general frustration venting
UNTARGETED_PROFANITY_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(bwisit|leche|bwiset|lintik|puta|anak\s+ng\s+tokwa|pakshet|badtrip)\b", re.IGNORECASE),
    re.compile(r"\b(damn\s+it|shit|crap|fuck)\b", re.IGNORECASE),
]

# Second-person targeting markers (direct victim address)
TARGET_PRONOUNS = {"ka", "mo", "ikaw", "kita", "sayo", "sa'yo", "kayo", "ninyo", "niyo", "you", "your", "u"}

# Time / Imminence markers
IMMEDIATE_TIME_MARKERS = [r"\bngayon\s+na\b", r"\bdito\s+mismo\b", r"\bright\s+now\b", r"\bthis\s+instant\b"]
FUTURE_SPECIFIC_MARKERS = [r"\bmamaya\b", r"\bpagkatapos\s+ng\s+klase\b", r"\bsa\s+labas\b", r"\bsa\s+gate\b", r"\blater\b", r"\bafter\s+school\b", r"\bafter\s+class\b"]
CONDITIONAL_TIME_MARKERS = [r"\bsa\s+susunod\b", r"\bpag\s+nagkita\b", r"\bnext\s+time\b", r"\bwhenever\b"]


# =============================================================================
# STAGE 6: INCIDENT-SPECIFIC ESCALATION TRACKER (PER-DEVICE / THREAD-SAFE)
# =============================================================================

class HistoricalStatement(BaseModel):
    timestamp: float
    text: str
    intent: ThreatIntent
    threat_type: ThreatType
    score: float
    category: str


class DeviceIncidentTracker:
    """
    Tracks sequential conversational context for a single physical device.
    Keeps timelines strictly isolated between students and smart pins.
    """
    def __init__(self, device_id: str, window_seconds: float = 600.0, max_history: int = 20):
        self.device_id = device_id
        self.window_seconds = window_seconds
        self.max_history = max_history
        self.history: deque[HistoricalStatement] = deque(maxlen=max_history)
        self.last_activity: float = time.time()

    def add_statement(
        self,
        text: str,
        intent: ThreatIntent,
        threat_type: ThreatType,
        score: float,
        category: str,
        timestamp: Optional[float] = None
    ) -> None:
        ts = timestamp if timestamp is not None else time.time()
        self.last_activity = ts
        self.history.append(HistoricalStatement(
            timestamp=ts,
            text=text,
            intent=intent,
            threat_type=threat_type,
            score=score,
            category=category
        ))

    def prune_expired(self, current_time: Optional[float] = None) -> None:
        now = current_time if current_time is not None else time.time()
        cutoff = now - self.window_seconds
        while self.history and self.history[0].timestamp < cutoff:
            self.history.popleft()

    def get_escalation_metrics(self, current_time: Optional[float] = None) -> Dict[str, Any]:
        """
        Analyzes the recent sliding window for escalation signals:
        - harassment_count: repeated insults within window
        - extortion_count: repeated financial/coercive demands
        - intimidation_count: repeated veiled or indirect threats
        """
        self.prune_expired(current_time)
        harassment_count = 0
        extortion_count = 0
        intimidation_count = 0
        hostile_count = 0

        for stmt in self.history:
            if stmt.score >= 4.0:
                hostile_count += 1
            if stmt.intent in (ThreatIntent.VERBAL_HARASSMENT, ThreatIntent.BULLYING):
                harassment_count += 1
            elif stmt.intent in (ThreatIntent.EXTORTION, ThreatIntent.COERCION):
                extortion_count += 1
            elif stmt.intent == ThreatIntent.DIRECT_THREAT:
                intimidation_count += 1

        return {
            "total_recent": len(self.history),
            "hostile_count": hostile_count,
            "harassment_count": harassment_count,
            "extortion_count": extortion_count,
            "intimidation_count": intimidation_count,
        }


class DeviceEscalationManager:
    """Thread-safe manager for device-specific incident histories."""
    def __init__(self, window_seconds: float = 600.0, cleanup_interval_seconds: float = 3600.0):
        self.window_seconds = window_seconds
        self.cleanup_interval = cleanup_interval_seconds
        self.trackers: Dict[str, DeviceIncidentTracker] = {}
        self.lock = threading.Lock()
        self.last_cleanup = time.time()

    def get_tracker(self, device_id: str) -> DeviceIncidentTracker:
        with self.lock:
            self._maybe_cleanup()
            if device_id not in self.trackers:
                self.trackers[device_id] = DeviceIncidentTracker(
                    device_id=device_id,
                    window_seconds=self.window_seconds
                )
            return self.trackers[device_id]

    def _maybe_cleanup(self) -> None:
        now = time.time()
        if now - self.last_cleanup > self.cleanup_interval:
            self.last_cleanup = now
            stale_cutoff = now - self.cleanup_interval
            stale_keys = [
                d_id for d_id, tracker in self.trackers.items()
                if tracker.last_activity < stale_cutoff
            ]
            for d_id in stale_keys:
                del self.trackers[d_id]


# =============================================================================
# CONTEXT ENGINE IMPLEMENTATION
# =============================================================================

class ContextEngine:
    """
    SecureLink ContextEngine (V3).
    Evaluates spoken transcripts using linguistic analysis, contextual intent
    classification, school-specific intimidation recognition, and device-isolated
    escalation tracking.
    """

    def __init__(
        self,
        bert_model: Any = None,
        tokenizer: Any = None,
        escalation_window_seconds: float = 600.0
    ):
        self.bert_model = bert_model
        self.tokenizer = tokenizer
        self.escalation_manager = DeviceEscalationManager(window_seconds=escalation_window_seconds)

    # -------------------------------------------------------------------------
    # STAGE 1: TRANSCRIPT VALIDATION
    # -------------------------------------------------------------------------
    def validate_transcript(
        self,
        text: str,
        transcription_result: Optional[Any] = None
    ) -> Tuple[bool, EvidenceReliability, str]:
        """
        Validates the transcript input and determines evidence reliability.
        Returns (is_valid, reliability, reason).
        """
        clean_text = text.strip() if text else ""
        if len(clean_text) < 3:
            return False, EvidenceReliability.LOW, "Transcript shorter than 3 characters"

        if transcription_result is not None:
            status = getattr(transcription_result, "status", None)
            status_val = status.value if hasattr(status, "value") else str(status)

            if status_val == "NO_SPEECH":
                return False, EvidenceReliability.UNCERTAIN, "Silence buffer (NO_SPEECH)"
            if status_val == "TRANSCRIPTION_REJECTED":
                return False, EvidenceReliability.UNCERTAIN, "Acoustic burst or repetition loop (REJECTED)"
            if status_val == "UNCERTAIN_TRANSCRIPTION":
                return True, EvidenceReliability.UNCERTAIN, "Borderline acoustic confidence (UNCERTAIN)"

        return True, EvidenceReliability.HIGH, "Valid transcript accepted"

    # -------------------------------------------------------------------------
    # STAGE 2: LANGUAGE AND INTENT ANALYSIS
    # -------------------------------------------------------------------------
    def analyze_intent(self, text: str) -> Tuple[ThreatIntent, ThreatType, List[str]]:
        """
        Determines the conversational intent and underlying threat type of the statement.
        Considers Tagalog/English idioms, negation, reported speech, hypotheticals,
        extortion, coercion, school harassment, and direct violence.
        """
        text_lower = text.lower().strip()
        risk_flags: List[str] = []

        # 1. Idiomatic Non-Threat Filter (Tagalog idioms & common hyperbole)
        for pattern, explanation in IDIOMATIC_NON_THREATS:
            if pattern.search(text_lower):
                risk_flags.append(f"Recognized benign idiom: {explanation}")
                return ThreatIntent.ORDINARY_CONVERSATION, ThreatType.NONE, risk_flags

        # 2. Negated Threat Filter
        for pattern in NEGATION_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Threat action explicitly negated / disclaimed")
                return ThreatIntent.NEGATED_THREAT, ThreatType.NONE, risk_flags

        # 3. Hypothetical & Dream Filter
        for pattern in HYPOTHETICAL_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Hypothetical, dream, or speculative phrasing detected")
                return ThreatIntent.HYPOTHETICAL_THREAT, ThreatType.NONE, risk_flags

        # 4. Reported Speech Filter
        for pattern in REPORTED_SPEECH_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Reported speech: speaker is reporting what another person said")
                return ThreatIntent.REPORTED_THREAT, ThreatType.SOCIAL_INTIMIDATION, risk_flags

        # 5. Past Incident Filter
        for pattern in PAST_INCIDENT_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Past incident reference: event occurred in prior timeframe")
                return ThreatIntent.PAST_INCIDENT, ThreatType.PHYSICAL_VIOLENCE, risk_flags

        # 6. Direct Physical Violence Threat Filter
        for pattern in DIRECT_PHYSICAL_THREAT_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Explicit direct physical violence threat detected")
                return ThreatIntent.DIRECT_THREAT, ThreatType.PHYSICAL_VIOLENCE, risk_flags

        # 7. Extortion Filter
        for pattern in EXTORTION_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Extortion / demand for money or property detected")
                return ThreatIntent.EXTORTION, ThreatType.EXTORTION, risk_flags

        # 8. Coercion & Secrecy Filter
        for pattern in COERCION_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Coercion / secrecy enforcement pattern detected")
                return ThreatIntent.COERCION, ThreatType.COERCION, risk_flags

        # 9. Indirect / School Intimidation Filter
        for pattern in INDIRECT_INTIMIDATION_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Indirect or veiled intimidation pattern detected")
                return ThreatIntent.DIRECT_THREAT, ThreatType.SOCIAL_INTIMIDATION, risk_flags

        # 10. Targeted Verbal Harassment Filter
        for pattern in VERBAL_HARASSMENT_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Targeted derogatory insult / verbal harassment detected")
                return ThreatIntent.VERBAL_HARASSMENT, ThreatType.VERBAL_HARASSMENT, risk_flags

        # 11. Untargeted Profanity / Venting
        for pattern in UNTARGETED_PROFANITY_PATTERNS:
            if pattern.search(text_lower):
                risk_flags.append("Untargeted profanity / conversational venting")
                return ThreatIntent.ORDINARY_CONVERSATION, ThreatType.NONE, risk_flags

        # Default fallback
        return ThreatIntent.ORDINARY_CONVERSATION, ThreatType.NONE, risk_flags

    # -------------------------------------------------------------------------
    # STAGE 3: CONTEXT EXTRACTION
    # -------------------------------------------------------------------------
    def extract_context(
        self,
        text: str,
        intent: ThreatIntent,
        threat_type: ThreatType,
        evidence_reliability: EvidenceReliability
    ) -> ContextExtraction:
        """Extracts structured contextual dimensions from speech text."""
        text_lower = text.lower()
        words = set(re.findall(r"\b\w+\b", text_lower))

        # Determine targetedness
        is_second_person = any(p in words for p in TARGET_PRONOUNS)
        if is_second_person:
            targetedness = Targetedness.DIRECT_SECOND_PERSON
            target_ref = "second_person_victim"
        elif any(p in words for p in {"siya", "sila", "he", "she", "they"}):
            targetedness = Targetedness.NAMED_INDIVIDUAL
            target_ref = "third_person"
        elif any(p in words for p in {"ako", "ko", "sarili", "myself", "i"}):
            targetedness = Targetedness.SELF_DIRECTED
            target_ref = "self"
        else:
            targetedness = Targetedness.UNTARGETED
            target_ref = None

        # Determine imminence & time references
        imminence = Imminence.NONE
        time_ref = None
        for m in IMMEDIATE_TIME_MARKERS:
            if re.search(m, text_lower):
                imminence = Imminence.IMMEDIATE
                time_ref = "immediate"
                break
        if imminence == Imminence.NONE:
            for m in FUTURE_SPECIFIC_MARKERS:
                if re.search(m, text_lower):
                    imminence = Imminence.FUTURE_SPECIFIC
                    time_ref = "future_scheduled"
                    break
        if imminence == Imminence.NONE:
            for m in CONDITIONAL_TIME_MARKERS:
                if re.search(m, text_lower):
                    imminence = Imminence.CONDITIONAL_FUTURE
                    time_ref = "conditional"
                    break

        # Specificity
        has_specific_location = any(w in text_lower for w in ["gate", "labas", "classroom", "canteen", "banyo", "hallway"])
        has_specific_weapon = any(w in text_lower for w in ["kutsilyo", "baril", "patalim", "bote", "knife", "gun"])
        if has_specific_weapon or (has_specific_location and imminence in (Imminence.IMMEDIATE, Imminence.FUTURE_SPECIFIC)):
            specificity = "HIGH"
        elif has_specific_location or imminence != Imminence.NONE:
            specificity = "MEDIUM"
        else:
            specificity = "LOW"

        return ContextExtraction(
            intent=intent,
            threat_type=threat_type,
            targetedness=targetedness,
            target_reference=target_ref,
            harmful_action=threat_type.value if threat_type != ThreatType.NONE else None,
            time_reference=time_ref,
            location_reference="campus_location" if has_specific_location else None,
            imminence=imminence,
            specificity=specificity,
            evidence_reliability=evidence_reliability,
            reported_speech=(intent == ThreatIntent.REPORTED_THREAT),
            negated=(intent == ThreatIntent.NEGATED_THREAT),
        )

    # -------------------------------------------------------------------------
    # STAGE 4 & 5: SITUATIONAL RISK ASSESSMENT & SEVERITY SCORING
    # -------------------------------------------------------------------------
    def score_threat(
        self,
        text: str,
        context: ContextExtraction,
        risk_flags: List[str],
        escalation_metrics: Dict[str, Any]
    ) -> Tuple[float, str, str, str, str, bool]:
        """
        Calculates explainable severity score (0.0 to 10.0), incident level,
        category, human-readable explanation, response, and review requirement.
        """
        intent = context.intent
        threat_type = context.threat_type
        human_review = False

        # ---------------------------------------------------------------------
        # Base Score Assignment by Intent
        # ---------------------------------------------------------------------
        if intent == ThreatIntent.ORDINARY_CONVERSATION:
            base_score = 1.0
            category = "Conversational"
            explanation = "Ordinary conversational speech or benign idiom without threat indicators."
            response = "No action required. Normal background monitoring."

        elif intent == ThreatIntent.NEGATED_THREAT:
            base_score = 1.2
            category = "Conversational"
            explanation = "Potentially violent terms detected but explicitly negated (e.g. 'Hindi kita sasaktan')."
            response = "Log for audit; no safety intervention needed."

        elif intent == ThreatIntent.HYPOTHETICAL_THREAT:
            base_score = 1.8
            category = "Conversational"
            explanation = "Hypothetical, dream, or speculative statement without real-world hostile intent."
            response = "Log as conversational hypothetical; no intervention needed."

        elif intent == ThreatIntent.PAST_INCIDENT:
            base_score = 3.5
            category = "Warning / Incident Report"
            explanation = "Speaker described a past confrontation or historic altercation. Not an active emergency."
            response = "Flag for student counselor or prefect review during normal hours."
            human_review = True

        elif intent == ThreatIntent.REPORTED_THREAT:
            base_score = 5.0
            category = "Reported Threat"
            explanation = "Speaker reported a threat made by someone else. High administrative priority; not an active physical emergency."
            response = "Notify designated guidance counselor/prefect to interview the reporting student."
            human_review = True

        elif intent == ThreatIntent.VERBAL_HARASSMENT:
            # Targeted insult: 5.5 to 6.5. Untargeted: 3.0.
            if context.targetedness == Targetedness.DIRECT_SECOND_PERSON:
                base_score = 6.0
                category = "Verbal Harassment"
                explanation = "Direct personal insults or derogatory slurs targeting another individual."
                response = "Notify educator/prefect of verbal bullying for behavioral intervention."
            else:
                base_score = 2.8
                category = "Conversational"
                explanation = "Untargeted profanity or emotional venting without direct personal target."
                response = "Log as mild warning; monitor for escalation."

        elif intent == ThreatIntent.COERCION:
            base_score = 5.5
            category = "Coercion / Intimidation"
            explanation = "Coercive intimidation enforcing secrecy or obedience (e.g. 'Huwag mong sabihin sa teacher')."
            response = "High-priority alert: counselor follow-up required to prevent intimidation culture."
            human_review = True

        elif intent == ThreatIntent.EXTORTION:
            base_score = 6.5
            category = "Extortion / Demand"
            explanation = "Coercive demand for money, allowance, or food under threat of harm."
            response = "High-priority school alert: report to campus prefect for immediate investigation."
            human_review = True

        elif intent == ThreatIntent.DIRECT_THREAT:
            if threat_type == ThreatType.PHYSICAL_VIOLENCE:
                text_lower = text.lower()
                is_lethal = any(w in text_lower for w in ["patayin", "kill", "saksakin", "stab", "babarilin", "shoot", "itutumba"])
                if is_lethal:
                    base_score = 9.2
                    category = "Physical Threat"
                    explanation = "Direct, severe threat of lethal violence or major physical assault."
                    response = "EMERGENCY: Immediate campus security dispatch and photographic evidence capture."
                else:
                    base_score = 8.5
                    category = "Physical Threat"
                    explanation = "Direct physical threat of battery, punching, or assault."
                    response = "DANGER ALERT: Dispatch security/teacher to de-escalate confrontation."
            else:
                # Veiled / indirect threat (e.g. "Alam mo na mangyayari sa'yo mamaya")
                base_score = 6.2
                category = "Social Intimidation"
                explanation = "Veiled or indirect school intimidation forecasting future harm."
                response = "Elevated safety alert: check on targeted student and investigate aggressor."
                human_review = True
        else:
            base_score = 1.0
            category = "Conversational"
            explanation = "Indeterminate intent; classified as conversational."
            response = "Normal monitoring."

        # ---------------------------------------------------------------------
        # Contextual Adjustments (Time, Location, Weapons)
        # ---------------------------------------------------------------------
        score = base_score

        if context.imminence == Imminence.IMMEDIATE and category != "Conversational":
            score += 0.5
            risk_flags.append("Immediate temporal proximity (+0.5)")
        elif context.imminence == Imminence.FUTURE_SPECIFIC and category != "Conversational":
            score += 0.3
            risk_flags.append("Specific scheduled timeframe (+0.3)")

        if context.location_reference and category != "Conversational":
            score += 0.3
            risk_flags.append("Specific campus location referenced (+0.3)")

        # ---------------------------------------------------------------------
        # Stage 6: Incident-Specific Escalation Adjustments
        # ---------------------------------------------------------------------
        prior_harassment = escalation_metrics.get("harassment_count", 0)
        prior_extortion = escalation_metrics.get("extortion_count", 0)
        prior_intimidation = escalation_metrics.get("intimidation_count", 0)

        # Repeated verbal harassment escalates severity, but is STRICTLY CAPPED at 7.8 (NEVER DANGER)
        if intent == ThreatIntent.VERBAL_HARASSMENT:
            # If 2 or more harassment statements already occurred, this is the 3rd+ event
            if prior_harassment >= 2:
                score = max(score, 7.2)
                category = "Escalated Harassment"
                risk_flags.append(f"Repeated verbal harassment escalation ({prior_harassment + 1} events in window)")
            elif prior_harassment == 1:
                score = max(score, 6.5)
                risk_flags.append("Second consecutive harassment event in window")

        # Repeated extortion escalates within THREAT band
        elif intent == ThreatIntent.EXTORTION:
            if prior_extortion >= 1:
                score = max(score, 7.5)
                risk_flags.append(f"Repeated extortion pattern detected ({prior_extortion + 1} demands in window)")

        # Repeated indirect intimidation escalates within THREAT band
        elif intent == ThreatIntent.DIRECT_THREAT and threat_type == ThreatType.SOCIAL_INTIMIDATION:
            if prior_intimidation >= 1:
                score = max(score, 7.6)
                category = "Escalated Intimidation"
                risk_flags.append(f"Repeated indirect intimidation pattern ({prior_intimidation + 1} statements in window)")

        # ---------------------------------------------------------------------
        # Safety Boundary Constraints & Caps
        # ---------------------------------------------------------------------
        # 1. Non-physical categories CANNOT enter DANGER (>= 8.0)
        if intent != ThreatIntent.DIRECT_THREAT or threat_type != ThreatType.PHYSICAL_VIOLENCE:
            score = min(score, 7.8)

        # 2. Uncertain transcription evidence CANNOT enter DANGER
        if context.evidence_reliability == EvidenceReliability.UNCERTAIN:
            if score >= 8.0:
                score = 6.5
                risk_flags.append("Evidence uncertain: capped from DANGER to THREAT pending review")
                human_review = True

        # 3. Reported/Quoted/Past/Negated speech CANNOT enter DANGER
        if intent in (ThreatIntent.REPORTED_THREAT, ThreatIntent.QUOTED_THREAT, ThreatIntent.PAST_INCIDENT, ThreatIntent.NEGATED_THREAT):
            score = min(score, 6.0)

        # Bounds check
        final_score = round(max(0.0, min(10.0, score)), 1)

        # Map to operational incident levels
        if final_score >= 8.0:
            level = IncidentLevel.DANGER.value
        elif final_score >= 4.0:
            level = IncidentLevel.THREAT.value
        elif final_score >= 2.0:
            level = IncidentLevel.WARNING.value
        else:
            level = IncidentLevel.NORMAL.value

        return final_score, level, category, explanation, response, human_review

    # -------------------------------------------------------------------------
    # MAIN EVALUATE ENTRYPOINT
    # -------------------------------------------------------------------------
    def evaluate(
        self,
        text: str,
        device_id: Optional[str] = None,
        timestamp: Optional[float] = None,
        transcription_result: Optional[Any] = None
    ) -> SeverityAssessment:
        """
        Evaluates a transcript across all 6 stages of the SecureLink Context Engine.
        Returns a rich SeverityAssessment (which unpacks as `score, category` for legacy callers).
        """
        ts = timestamp if timestamp is not None else time.time()
        dev_id = device_id if device_id else "DEFAULT"

        # Stage 1: Validation
        is_valid, reliability, val_reason = self.validate_transcript(text, transcription_result)
        if not is_valid:
            return SeverityAssessment(
                score=0.0,
                level=IncidentLevel.NORMAL.value,
                category="Conversational",
                intent=ThreatIntent.ORDINARY_CONVERSATION,
                threat_type=ThreatType.NONE,
                targetedness=Targetedness.UNTARGETED,
                imminence=Imminence.NONE,
                risk_factors=[val_reason],
                evidence_confidence=0.0,
                explanation=val_reason,
                recommended_response="No action required.",
                human_review_required=False,
                context=None
            )

        # Stage 2: Language & Intent Analysis
        intent, threat_type, risk_flags = self.analyze_intent(text)

        # Stage 3: Context Extraction
        context = self.extract_context(text, intent, threat_type, reliability)

        # Stage 6: Retrieve device-specific escalation metrics
        tracker = self.escalation_manager.get_tracker(dev_id)
        escalation_metrics = tracker.get_escalation_metrics(ts)

        # Stage 4 & 5: Risk Assessment & Severity Scoring
        score, level, category, explanation, response, human_review = self.score_threat(
            text, context, risk_flags, escalation_metrics
        )

        # Record this statement in device history for future sequential escalation
        tracker.add_statement(
            text=text,
            intent=intent,
            threat_type=threat_type,
            score=score,
            category=category,
            timestamp=ts
        )

        return SeverityAssessment(
            score=score,
            level=level,
            category=category,
            intent=intent,
            threat_type=threat_type,
            targetedness=context.targetedness,
            imminence=context.imminence,
            risk_factors=risk_flags,
            evidence_confidence=1.0 if reliability == EvidenceReliability.HIGH else 0.5,
            explanation=explanation,
            recommended_response=response,
            human_review_required=human_review,
            context=context
        )

    # -------------------------------------------------------------------------
    # BACKWARD COMPATIBILITY ATTRIBUTE
    # -------------------------------------------------------------------------
    @property
    def history(self) -> List[float]:
        """Backward compatibility for legacy code checking context_engine.history."""
        tracker = self.escalation_manager.get_tracker("DEFAULT")
        return [stmt.score for stmt in tracker.history]


# Global singleton instance for server.py import
context_engine = ContextEngine()
