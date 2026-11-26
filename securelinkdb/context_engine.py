"""
SecureLink Context Engine & Threat Severity Assessment System (V4)
=================================================================
A compositional, hybrid (TagalogBERT + Filipino/Taglish/English rules),
episode-aware contextual threat assessment engine designed for Philippine schools.

Supports:
- Filipino/Tagalog, English, and Taglish code-switching
- Compositional signal extraction across contrastive clauses (preventing
  premature early-return suppression when humor, negation, or past tense
  co-occurs with an active threat)
- Active TagalogBERT inference (`jcblaise/roberta-tagalog-base` / local
  checkpoint) with confidence gating and graceful rules fallback
- Distinguishing direct threats, indirect intimidation, extortion, coercion,
  verbal harassment, ambiguous context (`AMBIGUOUS_CONTEXT`), friendly teasing,
  reported/quoted speech, past incidents, hypotheticals, and negations
- Episode-aware escalation tracking separating continuous ~8s USB stream
  chunks from distinct repeated bullying episodes
- Normalized 0-10 severity scoring preserving backward-compatible
  `(score, category)` tuple unpacking and `SeverityAssessment` schema
"""

from __future__ import annotations

import logging
import os
import re
import threading
import time
from collections import deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, Tuple

from pydantic import BaseModel, Field

logger = logging.getLogger("securelink.context_engine")


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
    AMBIGUOUS_CONTEXT = "AMBIGUOUS_CONTEXT"
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
    # Additive V4 interpretability fields
    model_used: bool = False
    model_label: Optional[int] = None
    model_probabilities: Optional[Dict[str, float]] = None
    humor_marker: bool = False
    quoted_speech: bool = False
    past_reference: bool = False
    episode_id: int = 1
    distinct_episodes: int = 1
    is_split_chunk: bool = False


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
# LINGUISTIC PATTERNS & SCHOOL SCENARIO DICTIONARIES (COMPOSITIONAL V4)
# =============================================================================

CONTRASTIVE_CLAUSE_SPLIT_RE = re.compile(
    r"(?:,|;)?\s*\b(?:pero|kaso|ngunit|subalit|but|however)\b\s*",
    re.IGNORECASE,
)

# Humor / joke disclaimers (modifier — never suppresses explicit threats in V4)
HUMOR_DISCLAIMER_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(biro|joke|char|charot|eme|charing)\s+lang\b", re.IGNORECASE), "Humor disclaimer ('joke/biro/charot lang')"),
    (re.compile(r"\bjust\s+kidding\b|\bjk\b", re.IGNORECASE), "English humor disclaimer ('just kidding')"),
]

# Non-humor benign idioms & academic/romantic hyperbole
IDIOMATIC_NON_THREATS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\bpatay\s+na\s+patay\b", re.IGNORECASE), "Romantic infatuation idiom ('patay na patay')"),
    (re.compile(r"\bmahal\s+(kita|ka|ko)\b", re.IGNORECASE), "Expression of affection ('mahal kita')"),
    (re.compile(r"\bcrush\s+(kita|ka|ko)\b", re.IGNORECASE), "Expression of attraction ('crush kita')"),
    (re.compile(r"\bi\s+love\s+you\b", re.IGNORECASE), "Expression of affection ('I love you')"),
    (re.compile(r"\bnakakamatay\s+(yung|ang|tong)?\s*(exam|test|quiz|project|homework|traffic|init|gutom|pagod|calculus|math|thesis)\b", re.IGNORECASE), "Academic or environmental hyperbole ('nakakamatay ang exam')"),
    (re.compile(r"\bmamatay\s+sa\s+(tawa|gutom|pagod|kilig|hiya)\b", re.IGNORECASE), "Colloquial hyperbole ('mamatay sa tawa')"),
    (re.compile(r"\bdying\s+of\s+(laughter|hunger|boredom)\b", re.IGNORECASE), "English hyperbole ('dying of laughter')"),
    (re.compile(r"\bbabawi\s+a?ko\s+(sa\s+susunod|next\s+time)\b", re.IGNORECASE), "Positive determination ('babawi ako sa susunod')"),
    (re.compile(r"\bwag\s+(ka\s+)?mag-?alala\b", re.IGNORECASE), "Conversational reassurance"),
    (re.compile(r"\bno\s+offense\b", re.IGNORECASE), "Mild conversational hedge"),
]

# Negation patterns (harm explicitly denied or disclaimed)
NEGATION_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"\b(hindi|di|hinde)\s+(ki\s*ta|ka|ko|namin|nila|ko\s+siya)?\s*"
        r"(?:(kailanman|kahit\s+kailan)\s+)?"
        r"(sasaktan|papatayin|pa\s*patayin|aawayin|bubugbugin|bubu?gbugin|susuntukin|sasapakin|tatadyakan|hihiwain|gagalawin|kukuhanin|kukunin)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\b(hindi|di|hinde)\s+(ako|kami|namin)\s+(?:nila\s+|sila\s+)?(mananakit|mang-?aaway|magagalit|manununtok|mambubugbog)\b", re.IGNORECASE),
    re.compile(r"\b(hindi|di|hinde)\s+(namin|ko)\s+(sila|siya|kayo)\s+(aawayin|sasaktan|gagalawin)\b", re.IGNORECASE),
    re.compile(r"\b(huwag|wag)\s+mong\s+(saktan|awayin|gagalawin|patulan)\b", re.IGNORECASE),
    re.compile(r"\bayoko(?:ng)?\s+(?:manakit|mang-?away|makipag-?away|mambully)\b", re.IGNORECASE),
    re.compile(r"\bwala\s+(akong|kaming)\s+gagawing\s+masama\b", re.IGNORECASE),
    re.compile(
        r"\b(?:i|we|he|she|they)?\s*(?:will\s+not|would\s+(?:not|never)|won'?t|never|do\s+not|don'?t)\s+"
        r"(?:want\s+to\s+|ever\s+)?(hurt|kill|punch|beat|harm|touch|bully)\b",
        re.IGNORECASE,
    ),
]

# Reported speech & quoted/digital relay markers
REPORTED_SPEECH_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(sinabi|sabi|kwento|kwinento|nag-?chat|nag-?text|nag-?post|sabi-?sabi)\s+(niya|nila|nung\s+\w+|ng\s+\w+|sa\s+gc|sa\s+chat)?\s*(?:na\b|raw\b|daw\b)", re.IGNORECASE),
    re.compile(r"\b(sinabi|sabi|kwento|kwinento)\s+(niya|nila|nung\s+\w+|ng\s+(?:kaklase|tropa|kaibigan|lalaki|babae|senior|estudyante)\w*)\b", re.IGNORECASE),
    re.compile(r"\b(nagbanta|nagba-?banta)\s+(siya|sila|nung\s+\w+|ng\s+\w+)\s*(?:na\b)?", re.IGNORECASE),
    re.compile(r"\b(nabasa|nakita|narinig)\s+ko\s+(?:sa\s+(?:gc|chat|post|group)|na)\b", re.IGNORECASE),
    re.compile(r"\b[a-zñ]+\s+(?:daw|raw)\b", re.IGNORECASE),
    re.compile(r"\b(he|she|they|someone|my\s+\w+)\s+(literally\s+)?(said|told\s+\w+|threatened|texted|messaged|wrote|posted|quoted)\b", re.IGNORECASE),
    re.compile(r"\bbalita\s+ko\s+na\b", re.IGNORECASE),
]

QUOTED_SPAN_RE = re.compile(r"['\"][^'\"]{4,}['\"]")
REPORTED_HARM_VERB_RE = re.compile(
    r"\b(papatayin|bubugbugin|sasapakin|susuntukin|sasaksakin|babarilin|aabangan|"
    r"sasaktan|kinukuha|kukunin|hinoldap|threatened|nagbanta|nagba-?banta|pinagbantaan|"
    r"kill|murder|stab|shoot|beat\s+(?:\w+\s+)?up|punch|hurt|harm|rob)\b",
    re.IGNORECASE,
)
FICTION_OR_MEDIA_RE = re.compile(
    r"\b(pelikula|eksena|kontrabida|teleserye|movie|scene|script|story|kwento\s+sa\s+libro|nobela)\b",
    re.IGNORECASE,
)

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

# Past-tense incident patterns: require BOTH past harm/altercation verb AND past timeframe
PAST_TIME_RE = re.compile(
    r"\b(kahapon|kanina|noong\s+isang\s+linggo|nung\s+isang\s+(?:linggo|araw)|noong|dati|last\s+week|yesterday|earlier|ago)\b",
    re.IGNORECASE,
)
PAST_HARM_VERB_RE = re.compile(
    r"\b(sinapak|binugbog|sinuntok|tinadyakan|kinuha|hinoldap|binully|pinagbantaan|pinagtawanan|"
    r"tinulak|sinigawan|sinaktan|namatay|got\s+threatened|threatened|punched|hit|beat|stole|bullied)\b",
    re.IGNORECASE,
)
PAST_INCIDENT_PATTERNS: List[re.Pattern] = [
    re.compile(
        r"\b(sinapak|binugbog|sinuntok|tinadyakan|kinuha|hinoldap|binully|pinagbantaan|pinagtawanan|tinulak|sinigawan|sinaktan)\b"
        r".*\b(kahapon|kanina|nung|noong|dati|last\s+week|yesterday|earlier)\b",
        re.IGNORECASE,
    ),
    re.compile(
        r"\b(kahapon|kanina|nung|noong|dati|last\s+week|yesterday|earlier)\b"
        r".*\b(sinapak|binugbog|sinuntok|tinadyakan|kinuha|hinoldap|binully|pinagbantaan|pinagtawanan|tinulak|sinigawan|sinaktan|got\s+threatened|threatened)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bnamatay\s+(yung|ang|si)\s+\w+\s+(kahapon|kanina|dati|noong)\b", re.IGNORECASE),
]

# Extortion patterns (compelling payment or surrender of money/allowance)
EXTORTION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bakin\s+na\s+(?:lang\s+)?(?:yang\s+|yung\s+|ang\s+|tong\s+)?(baon|bawn|pera|allowance|barya|cellphone|relos|laman\s+ng\s+bulsa)\s*(mo)?\b", re.IGNORECASE),
    re.compile(r"\baraw-?araw\s+mo\s+(akong|kaming)\s+babayaran\b", re.IGNORECASE),
    re.compile(
        r"\b(ibigay|ilabas|iabot|bigay)\s+mo\s+(?:na\s+)?(?:sa\s*kin\s+|sa\s+akin\s+|sa\s+amin\s+)?"
        r"(?:yang\s+|yung\s+|ang\s+)?(pera|baon|bawn|gamit|allowance|laman\s+ng\s+bulsa|barya)\b",
        re.IGNORECASE,
    ),
    re.compile(r"\bmagbayad\s+ka\s+(?:ng\s+\w+\s+)?(sa\s*kin|sa\s+akin|sa\s+amin|araw-?araw)\b", re.IGNORECASE),
    re.compile(r"\bbayad\s+muna\s+bago\s+(?:ka\s+)?dumaan\b", re.IGNORECASE),
    re.compile(r"\bwag\s+kang\s+dadaan\s+dito\s+kung\s+walang?\s+bayad\b", re.IGNORECASE),
    re.compile(r"\b(give\s+me|hand\s+over|cough\s+up)\s+(your\s+|the\s+)?(money|lunch\s+money|allowance|cash)\b", re.IGNORECASE),
    re.compile(r"\bpay\s+up\s+or\s+else\b", re.IGNORECASE),
    re.compile(r"\bhoy\s+bigyan\s+mo\s+ko\s+(ng\s+)?(pera|baon|barya)\b", re.IGNORECASE),
]

# Coercion and secrecy enforcement patterns
COERCION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(huwag|wag)\s+mong?\s+sabihin\s+sa\s+(teacher|guro|magulang|guidance|pulis|dean|nanay|tatay|kahit\s+kanino|principal)\b", re.IGNORECASE),
    re.compile(r"\b(huwag|wag)\s+kang\s+mag-?susumbong\b", re.IGNORECASE),
    re.compile(r"\bpag\s+nag-?sumbong\s+ka\b", re.IGNORECASE),
    re.compile(r"\bsubukan\s+mong\s+mag-?sumbong\b", re.IGNORECASE),
    re.compile(r"\bdon'?t\s+(dare\s+)?tell\s+(the\s+teacher|anyone|the\s+principal|your\s+parents)\b", re.IGNORECASE),
    re.compile(r"\bif\s+you\s+(snitch|tell\s+anyone|report\s+this)\b", re.IGNORECASE),
    re.compile(r"\bgawin\s+mo\s+(?:lang\s+)?(?:yung|ang)\s+sinabi\s+ko\b", re.IGNORECASE),
]

# Indirect, veiled, and school-specific intimidation patterns
INDIRECT_INTIMIDATION_PATTERNS: List[re.Pattern] = [
    re.compile(r"\balam\s+mo\s+na\s+(?:kung\s+ano\s+ang\s+)?(mangyayari|aabutin\s+mo)\b", re.IGNORECASE),
    re.compile(r"\bmay\s+kakausap\s+sa'?yo\s+pagkatapos\s+ng\s+klase\b", re.IGNORECASE),
    re.compile(r"\bsa\s+susunod\s+na\s+makita\s+kita[,\s]+ewan\s+ko\s+na\s+lang\b", re.IGNORECASE),
    re.compile(r"\bhindi\s+pa\s+tayo\s+tapos\b", re.IGNORECASE),
    re.compile(r"\bdi\s+pa\s+tayo\s+tapos\b", re.IGNORECASE),
    re.compile(r"\ba?abangan\s+kita\s+(?:sa\s+labas|sa\s+gate|mamaya|paglabas|pag-?uwian)\b", re.IGNORECASE),
    re.compile(r"\bhumanda\s+ka\s+(?:sa\s*kin|sa\s+akin|mamaya|paglabas)\b", re.IGNORECASE),
    re.compile(r"\b(lagot|yari)\s+ka\s+(?:sa\s*kin|sa\s+akin)\b", re.IGNORECASE),
    re.compile(r"\bwag\s+kang\s+lalabas\b.*\b(lagot|yari|abangan|humanda)\b", re.IGNORECASE),
    re.compile(r"\breresbakan\s+kita\b", re.IGNORECASE),
    re.compile(r"\bwait\s+until\s+(after\s+class|we\s+get\s+outside)\b", re.IGNORECASE),
    re.compile(r"\byou'?ll\s+regret\s+this\b", re.IGNORECASE),
    re.compile(r"\bkundi\s+lagot\s+ka\b", re.IGNORECASE),
]

# Direct physical violence threats (explicit intent to inflict serious harm/death)
DIRECT_PHYSICAL_THREAT_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(pa\s*patayin|papatay|i\s*tutumba|liligpitin|kikitilin|ka\s*katayin)\s+(ki\s*ta|ka|kayo)\b", re.IGNORECASE),
    re.compile(r"\bi\s*(?:will|'ll|m\s+gonna|am\s+going\s+to)\s+(?:kill|murder)\s+you\b", re.IGNORECASE),
    re.compile(r"\b(sa\s*saksakin|ba\s*barilin|tatagpasin)\s+(ki\s*ta|ka)\b", re.IGNORECASE),
    re.compile(r"\bi\s*(?:will|'ll|m\s+gonna|am\s+going\s+to)\s+(?:stab|shoot|choke)\s+you\b", re.IGNORECASE),
    re.compile(r"\b(sa\s*sapakin|bu\s*bugbugin|su\s*suntukin|ta\s*tadyakan|u\s*upakan|sa\s*sakalin|i\s*papabugbog)\s+(ki\s*ta|ka|kayo)\b", re.IGNORECASE),
    re.compile(r"\b(ba\s*basagin|du\s*duguin)\s+(?:ko\s+)?(?:ang\s+|yang\s+)?(mukha|nguso|ulo|ilong)\s+mo\b", re.IGNORECASE),
    re.compile(r"\bi\s*(?:will|'ll|m\s+gonna|am\s+going\s+to)\s+(?:punch|beat\s+(?:you\s+up|the\s+\w+\s+out\s+of\s+you|you\s+to\s+death)|break\s+your\s+(?:face|nose|jaw))\b", re.IGNORECASE),
]

# Labeled sub-patterns for rhetorical/hypothetical assault checks
RHETORICAL_ASSAULT_RE = re.compile(
    r"\b(sapakin|patayin|bugbugin|suntukin|saksakin|barilin|sakalin|break\s+your\s+(?:nose|face|jaw)|kill\s+you|stab\s+you|punch\s+you)\b",
    re.IGNORECASE,
)

# Targeted verbal harassment, exclusion, body shaming, and humiliation
VERBAL_HARASSMENT_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(ang\s+)?(am)?(bobo|tanga|inutil|gago|tarantado|pangit|monggoloid|abnoy|siraulo|pabigat|palamunin|salot|loser|freak)\s+(mo|ka|nyo|ninyo)\b", re.IGNORECASE),
    re.compile(r"\b(am)?(bobo|inutil|tanga|gago|pangit|siraulo)\s+(ka|mo)\b", re.IGNORECASE),
    re.compile(r"\b(tangina|putangina|putang\s+ina)\s+mo\b", re.IGNORECASE),
    re.compile(r"\bwala(?:ng)?\s+(?:kang|kayong)\s+(?:silbi|kwenta|kuwenta)\b", re.IGNORECASE),
    re.compile(r"\bwalang\s+(?:silbi|kwenta|kuwenta)\s+(?:mo|ng\s+pamilya\s+mo)\b", re.IGNORECASE),
    re.compile(r"\b(ang\s+(?:taba\s+taba|laki\s+ng\s+ilong|asim|baho|dumi\s+dumi|dami\s+mong\s+pimples|baduy)\s+mo|parang\s+baboy|mukha(?:ng)?\s+(?:ewan|basurahan))\b", re.IGNORECASE),
    re.compile(r"\b(kadiri\s+(?:ka|tignan)|nakakadiri\s+ka)\b", re.IGNORECASE),
    re.compile(r"\b(walang\s+may\s+gusto\s+sa'?yo|nobody\s+(?:likes|wants)\s+you|you\s+don'?t\s+belong\s+here|go\s+sit\s+by\s+yourself|alis\s+ka\s+na\s+sa\s+(?:table|upuan)|lumayas\s+ka\s+sa\s+upuan)\b", re.IGNORECASE),
    re.compile(r"\b(wag\s+ka(?:ng)?\s+(?:didikit|sumali|tumabi)\s+sa\s+(?:amin|samin|grupo)|wag\s+niyo\s+isali\s+yan)\b", re.IGNORECASE),
    re.compile(r"\b(salot\s+ka|lumipat\s+ka\s+na\s+ng\s+school|tumahimik\s+ka\s+nga.*wala\s+kang\s+karapatan|pinagtawanan\s+ka\s+ng\s+lahat|nakakahiya\s+ka\s+mag|biggest\s+loser)\b", re.IGNORECASE),
    re.compile(r"\byou(?:'re|\s+are)\s+(?:literally\s+)?(?:so\s+|the\s+)?(stupid|an\s+idiot|ugly|a\s+loser|pathetic|worthless|a\s+freak|a\s+complete\s+joke|the\s+biggest\s+loser)\b", re.IGNORECASE),
    re.compile(r"\beveryone\s+laughs\s+at\s+you\b|\bstop\s+crying\s+like\s+a\s+baby\b|\bshut\s+up[,\s]+(idiot|loser|ugly)\b", re.IGNORECASE),
    re.compile(r"\b(ang\s+luma\s+ng\s+sapatos\s+mo.*pambili|ang\s+probinsyano\s+ng\s+accent\s+mo.*loser)\b", re.IGNORECASE),
    re.compile(r"\b(wow,?\s+ang\s+talino\s+mo.*(zero|nakakahiya)|great\s+job\s+genius.*ruined)\b", re.IGNORECASE),
]

# Discomfort / stop-request markers (critical for multi-turn harassment confirmation)
DISCOMFORT_STOP_PATTERNS: List[re.Pattern] = [
    re.compile(r"\bhindi\s+na\s+nakakatuwa\b", re.IGNORECASE),
    re.compile(r"\b(tama\s+na|tigilan\s+mo\s+na|itigil\s+mo\s+na|pwede\s+ba\s+tumigil)\b", re.IGNORECASE),
    re.compile(r"\b(stop\s+it|leave\s+me\s+alone|please\s+stop)\b", re.IGNORECASE),
]

# Identity / potentially sensitive banter terms that MUST NOT auto-escalate without hostile context
IDENTITY_SENSITIVE_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(bakla|bak\s+la|accla|tomboy|bisaya)\b", re.IGNORECASE),
]

# Explicit hostile corroboration / social exclusion markers alongside teasing or identity terms
HOSTILE_CORROBORATION_RE = re.compile(
    r"\b(lumayo|lumayas|alis|wag\s+niyo\s+isali|wag\s+ka\s+lumapit|nakakahiya|nakakadiri|kadiri|salot|walang\s+kwenta|pabigat|arte\s+mo|get\s+out|freak|loser)\b",
    re.IGNORECASE,
)

# Isolated / context-insufficient ambiguous phrases needing human review
AMBIGUOUS_PHRASE_PATTERNS: List[Tuple[re.Pattern, str]] = [
    (re.compile(r"\b(tignan|tingnan)\s+natin\s+mamaya\b", re.IGNORECASE), "Ambiguous 'tignan natin mamaya' lacking surrounding context"),
    (re.compile(r"\bmag-?usap\s+tayo\s+sa\s+labas\s+mamaya\b", re.IGNORECASE), "Ambiguous request to talk outside without explicit threat"),
    (re.compile(r"\byou\s+better\s+watch\s+yourself\b", re.IGNORECASE), "Ambiguous warning ('watch yourself') lacking situational context"),
    (re.compile(r"\bwe\s*(?:are|'re)\s+not\s+done\s+yet\b", re.IGNORECASE), "Ambiguous unresolved conflict ('not done yet')"),
    (re.compile(r"\b(lagot|yari)\s+ka\s+(?:kay\s+\w+\s+)?mamaya\b", re.IGNORECASE), "Ambiguous 'lagot/yari ka mamaya' without clear aggressor intent"),
    (re.compile(r"\babangan\s+mo\s+(?:na\s+lang\s+)?mamaya\b", re.IGNORECASE), "Ambiguous 'abangan mo mamaya' (awaiting announcement vs. intimidation)"),
    (re.compile(r"\bpatay\s+ka\s+na\s+naman\s+sa\s+(?:nanay|tatay|teacher|sir|ma'?am)\s+mo\b", re.IGNORECASE), "Colloquial 'patay ka sa nanay/teacher' idiom requiring context"),
    (re.compile(r"\byou'?re\s+dead\s+when\s+(?:she|he)\s+finds\s+out\b", re.IGNORECASE), "Ambiguous 'you're dead when she finds out'"),
    (re.compile(r"\bbigyan\s+mo\s+(?:na\s+)?ako\s+ng\s+\w+\s*(?:pesos|piso)\s*(?:ngayon)?\b", re.IGNORECASE), "Ambiguous money request (repayment vs. coercion)"),
    (re.compile(r"\b(ibigay\s+mo\s+na\s+sa'?kin\s+yan|akin\s+na\s+nga\s+yan(?:\s*,\s*bilis)?)\b", re.IGNORECASE), "Ambiguous demand for item without clear intimidation"),
    (re.compile(r"\bhuwag\s+kang\s+maingay[,\s]+wag\s+ka\s+magsabi\b", re.IGNORECASE), "Ambiguous silencing statement lacking threat context"),
    (re.compile(r"\b(tama\s+na[,\s]+wag\s+na\s+nga|hey[,\s]+stop\s+it\s+already|hindi\s+na\s+nakakatuwa\s+yan)\b", re.IGNORECASE), "Discomfort / stop-request cue without perpetrator utterance"),
    (re.compile(r"\b(umalis\s+ka\s+nga\s+dito|wag\s+ka\s+ngang\s+lumapit\s+sa'?kin)\b", re.IGNORECASE), "Ambiguous exclusion / boundary statement"),
    (re.compile(r"\boh\s+shut\s+up[,\s]+you\s+don'?t\s+know\s+anything\b", re.IGNORECASE), "Ambiguous 'shut up' (playful disbelief vs. hostility)"),
    (re.compile(r"\b(ang\s+weird\s+mo\s+talaga\s+minsan|literally\s+nobody\s+asked\s+you|ang\s+galing\s+mo\s+naman\s+talaga)\b", re.IGNORECASE), "Ambiguous sarcastic/teasing remark requiring tone"),
    (re.compile(r"\b(ang\s+taba\s+mo\s+na\s+uy|hoy\s+ang\s+baho\s+mo\s+na|ang\s+pangit\s+mo\.?|ang\s+bobo\s+naman\.?|ang\s+loser\s+mo\s+naman\.?|gago\s+ka\s+talaga\.?|tanga\s+ka\s+pala\s+eh\.?|siraulo\s+ka\s+talaga\s+eh\.?)\s*$", re.IGNORECASE), "Standalone colloquial teasing/insult fragment lacking context"),
    (re.compile(r"\bsa\s+gate\.+\s*mamaya\.+\s*ikaw", re.IGNORECASE), "Fragmented ASR transcript with unclear threat context"),
]

# Friendly banter, gaming, sports, and positive peer cues
BANTER_LAUGHTER_RE = re.compile(r"\b(ha(?:ha)+|he(?:he)+|hi(?:hi)+|lol|lmao)\b", re.IGNORECASE)
BANTER_PEER_RE = re.compile(r"\b(pre|pare|bro|tol|tropa|bes|besh|bestie|mare|mars|lodi|idol|accla)\b", re.IGNORECASE)
BANTER_GAMING_SPORTS_RE = re.compile(
    r"\b(ml|em\s+el|mobile\s+legends|valo|valorant|tekken|dota|cod|rank|ulti|tank|carry|clutch|1v1|"
    r"sa\s+laro|free\s+throw|next\s+quarter|rematch|next\s+game|basketball|intrams)\b",
    re.IGNORECASE,
)
BANTER_POSITIVE_CUE_RE = re.compile(
    r"\b(bawi\s+next|ang\s+taas\s+ng\s+score|perfect\s+ka|paturo|carry\s+na\s+lang\s+kita|"
    r"ang\s+lupit|ikaw\s+na\s+lodi|bili\s+kita|binilhan\s+kita|libre\s+mo\s+ko)\b",
    re.IGNORECASE,
)

# Untargeted profanities / general frustration venting
UNTARGETED_PROFANITY_PATTERNS: List[re.Pattern] = [
    re.compile(r"\b(bwisit|leche|bwiset|lintik|puta|anak\s+ng\s+tokwa|pakshet|badtrip)\b", re.IGNORECASE),
    re.compile(r"\b(damn\s+it|shit|crap|fuck)\b", re.IGNORECASE),
]

TARGET_PRONOUNS = {"ka", "mo", "ikaw", "kita", "sayo", "sa'yo", "kayo", "ninyo", "niyo", "you", "your", "u"}

IMMEDIATE_TIME_MARKERS = [r"\bngayon\s+na\b", r"\bdito\s+mismo\b", r"\bright\s+now\b", r"\bthis\s+instant\b", r"\bngayon\b"]
FUTURE_SPECIFIC_MARKERS = [r"\bmamaya\b", r"\bpagkatapos\s+ng\s+klase\b", r"\bsa\s+labas\b", r"\bsa\s+gate\b", r"\blater\b", r"\bafter\s+school\b", r"\bafter\s+class\b"]
CONDITIONAL_TIME_MARKERS = [r"\bsa\s+susunod\b", r"\bpag\s+nagkita\b", r"\bnext\s+time\b", r"\bwhenever\b"]

LOCATION_RE = re.compile(r"\b(gate|labas|classroom|canteen|banyo|hallway|school|locker)\b", re.IGNORECASE)
WEAPON_RE = re.compile(r"\b(kutsilyo|baril|patalim|bote|knife|gun)\b", re.IGNORECASE)

# BERT label mapping aligned with securelinkdb/dataset.csv and securelink_final_model
BERT_LABEL_TO_INTENT: Dict[int, Tuple[ThreatIntent, ThreatType, str]] = {
    0: (ThreatIntent.ORDINARY_CONVERSATION, ThreatType.NONE, "Conversational"),
    1: (ThreatIntent.VERBAL_HARASSMENT, ThreatType.VERBAL_HARASSMENT, "Verbal Harassment"),
    2: (ThreatIntent.EXTORTION, ThreatType.EXTORTION, "Extortion / Demand"),
    3: (ThreatIntent.DIRECT_THREAT, ThreatType.SOCIAL_INTIMIDATION, "Semantic Threat Alert"),
}

# Conservative ASR-slip rescue tables (high-severity Tagalog threat roots only,
# strictly gated behind hostile second-person framing and capped to WARNING review).
ASR_SLIP_THREAT_STEMS: Dict[str, Tuple[str, ...]] = {
    "bugbog": ("bugbog", "bugbugin", "bubugbugin", "binugbog"),
    "suntok": ("suntok", "suntukin", "susuntukin", "sinuntok"),
    "sapak": ("sapak", "sapakin", "sasapakin", "sinapak"),
    "patay": ("patay", "patayin", "papatayin"),
    "saksak": ("saksak", "saksakin", "sasaksakin", "sinaksak"),
    "abangan": ("abangan", "aabangan"),
}
ASR_SLIP_ALL_STEMS = {stem for stems in ASR_SLIP_THREAT_STEMS.values() for stem in stems}
ASR_SLIP_BENIGN_EXCLUSIONS = {
    "abala", "babae", "bagay", "bago", "balay", "bantay", "batay", "buhay",
    "dapat", "ibang", "kabataan", "kapatid", "laban", "palay", "panay",
    "papasok", "pasko", "pasok", "patag", "patak", "patas", "pataw",
    "sabak", "sabay", "sabi", "sabon", "sakay", "sakit", "sakop", "saksi",
    "sakto", "sama", "sanay", "santa", "santo", "sapagkat", "sapat",
    "sapatos", "subay", "subok", "sunod", "tapat", "tatay", "tawag",
}
ASR_SLIP_SECOND_PERSON_RE = re.compile(
    r"\b(kita|ka|mo|mong|kang|sayo|sa\s*yo|inyo)\b",
    re.IGNORECASE,
)
ASR_SLIP_HOSTILE_FRAME_RE = re.compile(
    r"\b(subukan|sige|tignan|tingnan|lagot|yari|humanda|mamaya|paglabas|"
    r"uwian|sa\s+labas|sa\s+gate|ngayon|tropa|barkada|diyan|dyan|mukha|pag\s+nakita)\b",
    re.IGNORECASE,
)


def _bounded_levenshtein_1(a: str, b: str) -> bool:
    """Return True iff Damerau-free Levenshtein edit distance between a and b is <= 1."""
    if a == b:
        return True
    la, lb = len(a), len(b)
    if abs(la - lb) > 1:
        return False
    if la == lb:
        return sum(1 for x, y in zip(a, b) if x != y) <= 1
    if la > lb:
        a, b = b, a
        la, lb = lb, la
    i = j = diffs = 0
    while i < la and j < lb:
        if a[i] == b[j]:
            i += 1
            j += 1
        else:
            diffs += 1
            if diffs > 1:
                return False
            j += 1
    return True


def _phonetic_norm_tagalog(tok: str) -> str:
    """Collapse common Filipino ASR stop/vowel confusions (b/p, d/t, g/k, u/o, i/e)."""
    norm = tok.lower()
    norm = norm.translate(str.maketrans({"b": "p", "d": "t", "g": "k", "u": "o", "i": "e", "v": "b", "f": "p"}))
    return re.sub(r"(.)\1+", r"\1", norm)


def _detect_asr_slip_threat(normalized_text: str) -> Optional[Tuple[str, str]]:
    """
    Detect a single-token Tagalog ASR slip close to a severe physical threat root,
    strictly requiring hostile second-person framing and excluding common benign words.
    """
    if not normalized_text:
        return None
    if not ASR_SLIP_SECOND_PERSON_RE.search(normalized_text):
        return None
    if not ASR_SLIP_HOSTILE_FRAME_RE.search(normalized_text):
        return None

    tokens = re.findall(r"[a-z]+", normalized_text.lower())
    for tok in tokens:
        if len(tok) < 5 or tok in ASR_SLIP_BENIGN_EXCLUSIONS or tok in ASR_SLIP_ALL_STEMS:
            continue
        tok_phon = _phonetic_norm_tagalog(tok)
        for root, stems in ASR_SLIP_THREAT_STEMS.items():
            for stem in stems:
                if abs(len(tok) - len(stem)) > 1:
                    continue
                stem_phon = _phonetic_norm_tagalog(stem)
                if not tok_phon or not stem_phon or tok_phon[0] != stem_phon[0]:
                    continue
                if _bounded_levenshtein_1(tok, stem) or (tok_phon == stem_phon):
                    return tok, root
    return None


# =============================================================================
# STAGE 6: EPISODE-AWARE INCIDENT TRACKER (PER-DEVICE / THREAD-SAFE)
# =============================================================================

class HistoricalStatement(BaseModel):
    timestamp: float
    text: str
    intent: ThreatIntent
    threat_type: ThreatType
    score: float
    category: str
    episode_id: int = 1
    is_split_chunk: bool = False
    discomfort_signal: bool = False


class DeviceIncidentTracker:
    """
    Tracks sequential conversational context for a single physical device.
    Separates rapid ~8s firmware split-stream chunks belonging to a single
    utterance/episode from genuine repeated bullying episodes across time.
    """
    def __init__(
        self,
        device_id: str,
        window_seconds: float = 600.0,
        max_history: int = 20,
        episode_gap_seconds: float = 20.0,
        chunk_continuation_window_seconds: float = 9.5,
    ):
        self.device_id = device_id
        self.window_seconds = window_seconds
        self.max_history = max_history
        self.episode_gap_seconds = episode_gap_seconds
        self.chunk_continuation_window_seconds = chunk_continuation_window_seconds
        self.history: deque[HistoricalStatement] = deque(maxlen=max_history)
        self.last_activity: float = time.time()

    def _classify_timing(
        self, timestamp: float, stream_continuation: bool = False
    ) -> Tuple[int, bool]:
        """Return (episode_id, is_split_chunk) for an incoming timestamp."""
        self.prune_expired(timestamp)
        if not self.history:
            return 1, bool(stream_continuation)
        prev = self.history[-1]
        gap = max(0.0, timestamp - prev.timestamp)
        is_split = bool(stream_continuation) or (0.5 <= gap <= self.chunk_continuation_window_seconds)
        if is_split or gap <= self.episode_gap_seconds:
            return prev.episode_id, is_split
        return prev.episode_id + 1, False

    def add_statement(
        self,
        text: str,
        intent: ThreatIntent,
        threat_type: ThreatType,
        score: float,
        category: str,
        timestamp: Optional[float] = None,
        stream_continuation: bool = False,
        discomfort_signal: bool = False,
    ) -> None:
        ts = timestamp if timestamp is not None else time.time()
        episode_id, is_split = self._classify_timing(ts, stream_continuation=stream_continuation)
        self.last_activity = ts
        self.history.append(HistoricalStatement(
            timestamp=ts,
            text=text,
            intent=intent,
            threat_type=threat_type,
            score=score,
            category=category,
            episode_id=episode_id,
            is_split_chunk=is_split,
            discomfort_signal=discomfort_signal,
        ))

    def prune_expired(self, current_time: Optional[float] = None) -> None:
        now = current_time if current_time is not None else time.time()
        cutoff = now - self.window_seconds
        while self.history and self.history[0].timestamp < cutoff:
            self.history.popleft()

    def get_escalation_metrics(
        self,
        current_time: Optional[float] = None,
        stream_continuation: bool = False,
    ) -> Dict[str, Any]:
        """
        Compute episode-aware escalation signals inside the sliding window:
        - statement counts & distinct episode counts per category
        - incoming split-stream detection so 8s chunks don't falsely escalate
        - recent discomfort/stop-request state for multi-turn banter -> harassment transitions
        """
        now = current_time if current_time is not None else time.time()
        self.prune_expired(now)
        next_episode_id, incoming_split = self._classify_timing(now, stream_continuation=stream_continuation)

        harassment_count = 0
        extortion_count = 0
        intimidation_count = 0
        hostile_count = 0
        recent_discomfort = False

        harassment_episodes: set[int] = set()
        extortion_episodes: set[int] = set()
        intimidation_episodes: set[int] = set()

        # Count non-split statements so synchronous distinct turns still escalate
        # while 0.5s–9.5s firmware split chunks stay grouped in one episode.
        harassment_non_split = 0
        extortion_non_split = 0
        intimidation_non_split = 0

        for stmt in self.history:
            if stmt.discomfort_signal:
                recent_discomfort = True
            if stmt.score >= 4.0:
                hostile_count += 1
            if stmt.intent in (ThreatIntent.VERBAL_HARASSMENT, ThreatIntent.BULLYING):
                harassment_count += 1
                if not stmt.is_split_chunk:
                    harassment_non_split += 1
                harassment_episodes.add(stmt.episode_id)
            elif stmt.intent in (ThreatIntent.EXTORTION, ThreatIntent.COERCION):
                extortion_count += 1
                if not stmt.is_split_chunk:
                    extortion_non_split += 1
                extortion_episodes.add(stmt.episode_id)
            elif stmt.intent == ThreatIntent.DIRECT_THREAT and stmt.threat_type == ThreatType.SOCIAL_INTIMIDATION:
                intimidation_count += 1
                if not stmt.is_split_chunk:
                    intimidation_non_split += 1
                intimidation_episodes.add(stmt.episode_id)

        distinct_episodes = len({stmt.episode_id for stmt in self.history})
        return {
            "total_recent": len(self.history),
            "hostile_count": hostile_count,
            "harassment_count": harassment_count,
            "extortion_count": extortion_count,
            "intimidation_count": intimidation_count,
            "harassment_non_split_count": harassment_non_split,
            "extortion_non_split_count": extortion_non_split,
            "intimidation_non_split_count": intimidation_non_split,
            "harassment_episode_count": len(harassment_episodes),
            "extortion_episode_count": len(extortion_episodes),
            "intimidation_episode_count": len(intimidation_episodes),
            "next_episode_id": next_episode_id,
            "distinct_episodes": max(distinct_episodes, next_episode_id),
            "incoming_is_split_chunk": incoming_split,
            "recent_discomfort": recent_discomfort,
        }


class DeviceEscalationManager:
    """Thread-safe manager for device-specific incident histories."""
    def __init__(
        self,
        window_seconds: float = 600.0,
        cleanup_interval_seconds: float = 3600.0,
        episode_gap_seconds: float = 20.0,
        chunk_continuation_window_seconds: float = 9.5,
    ):
        self.window_seconds = window_seconds
        self.cleanup_interval = cleanup_interval_seconds
        self.episode_gap_seconds = episode_gap_seconds
        self.chunk_continuation_window_seconds = chunk_continuation_window_seconds
        self.trackers: Dict[str, DeviceIncidentTracker] = {}
        self.lock = threading.Lock()
        self.last_cleanup = time.time()

    def get_tracker(self, device_id: str) -> DeviceIncidentTracker:
        with self.lock:
            self._maybe_cleanup()
            if device_id not in self.trackers:
                self.trackers[device_id] = DeviceIncidentTracker(
                    device_id=device_id,
                    window_seconds=self.window_seconds,
                    episode_gap_seconds=self.episode_gap_seconds,
                    chunk_continuation_window_seconds=self.chunk_continuation_window_seconds,
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


@dataclass
class _RuleSignals:
    intent: ThreatIntent
    threat_type: ThreatType
    risk_flags: List[str] = field(default_factory=list)
    humor_marker: bool = False
    quoted_speech: bool = False
    reported_speech: bool = False
    negated: bool = False
    past_reference: bool = False
    hypothetical: bool = False
    friendly_banter: bool = False
    discomfort_signal: bool = False
    has_modifier: bool = False
    ambiguity_reason: Optional[str] = None
    review_hint: bool = False
    asr_slip_rescue: bool = False


# =============================================================================
# CONTEXT ENGINE V4 IMPLEMENTATION
# =============================================================================

class ContextEngine:
    """
    SecureLink ContextEngine (V4).
    Combines compositional linguistic signal analysis, active TagalogBERT semantic
    probabilities (with graceful confidence-gated fallback), and episode-aware
    per-device escalation tracking.
    """

    def __init__(
        self,
        bert_model: Any = None,
        tokenizer: Any = None,
        escalation_window_seconds: float = 600.0,
        episode_gap_seconds: float = 20.0,
        chunk_continuation_window_seconds: float = 9.5,
        bert_confidence_threshold: float = 0.65,
        bert_max_length: int = 128,
    ):
        self.bert_model = bert_model
        self.tokenizer = tokenizer
        self.bert_confidence_threshold = float(bert_confidence_threshold)
        self.bert_max_length = int(bert_max_length)
        self.escalation_manager = DeviceEscalationManager(
            window_seconds=escalation_window_seconds,
            episode_gap_seconds=episode_gap_seconds,
            chunk_continuation_window_seconds=chunk_continuation_window_seconds,
        )

    def load_local_checkpoint(self, model_path: str) -> bool:
        """Load local TagalogBERT checkpoint (`securelink_final_model` or HF repo) onto Engine."""
        try:
            import torch
            from transformers import AutoModelForSequenceClassification, AutoTokenizer

            local_only = os.path.isdir(model_path)
            self.tokenizer = AutoTokenizer.from_pretrained(model_path, local_files_only=local_only)
            self.bert_model = AutoModelForSequenceClassification.from_pretrained(
                model_path, local_files_only=local_only
            )
            if torch.cuda.is_available():
                self.bert_model = self.bert_model.to("cuda")
            self.bert_model.eval()
            return True
        except Exception as exc:
            logger.warning("Failed to load TagalogBERT checkpoint '%s': %s", model_path, exc)
            self.tokenizer = None
            self.bert_model = None
            return False

    # -------------------------------------------------------------------------
    # STAGE 1: TRANSCRIPT VALIDATION
    # -------------------------------------------------------------------------
    def validate_transcript(
        self,
        text: str,
        transcription_result: Optional[Any] = None,
    ) -> Tuple[bool, EvidenceReliability, str]:
        """Validates transcript text & ASR status and returns (is_valid, reliability, reason)."""
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
    # STAGE 2A: COMPOSITIONAL LINGUISTIC SIGNAL EXTRACTION
    # -------------------------------------------------------------------------
    @staticmethod
    def _clause_has_any(clause: str, patterns: List[re.Pattern]) -> bool:
        return any(p.search(clause) for p in patterns)

    def _detect_banter_context(self, text_lower: str) -> bool:
        has_laugh = bool(BANTER_LAUGHTER_RE.search(text_lower))
        has_peer = bool(BANTER_PEER_RE.search(text_lower))
        has_game_sport = bool(BANTER_GAMING_SPORTS_RE.search(text_lower))
        has_positive = bool(BANTER_POSITIVE_CUE_RE.search(text_lower))
        return bool(
            (has_laugh and (has_peer or has_game_sport or has_positive))
            or (has_peer and (has_game_sport or has_positive))
            or has_game_sport
        )

    def _extract_rule_signals(
        self,
        text: str,
        recent_discomfort: bool = False,
    ) -> _RuleSignals:
        text_lower = text.lower().strip()
        clauses = [c.strip() for c in CONTRASTIVE_CLAUSE_SPLIT_RE.split(text_lower) if c.strip()]
        if not clauses:
            clauses = [text_lower]

        flags: List[str] = []

        # Collect non-exclusive modifier flags across the utterance
        humor_hits = [desc for pat, desc in HUMOR_DISCLAIMER_PATTERNS if pat.search(text_lower)]
        idiom_hits = [desc for pat, desc in IDIOMATIC_NON_THREATS if pat.search(text_lower)]
        has_humor = bool(humor_hits)
        has_idiom = bool(idiom_hits)
        has_reported = self._clause_has_any(text_lower, REPORTED_SPEECH_PATTERNS)
        has_quoted = bool(QUOTED_SPAN_RE.search(text))
        has_negation = self._clause_has_any(text_lower, NEGATION_PATTERNS)
        has_hypothetical = self._clause_has_any(text_lower, HYPOTHETICAL_PATTERNS)
        has_past_harm = self._clause_has_any(text_lower, PAST_INCIDENT_PATTERNS)
        has_discomfort = self._clause_has_any(text_lower, DISCOMFORT_STOP_PATTERNS)
        is_banter = (not recent_discomfort) and self._detect_banter_context(text_lower)
        has_identity = self._clause_has_any(text_lower, IDENTITY_SENSITIVE_PATTERNS)
        has_hostile_corr = bool(HOSTILE_CORROBORATION_RE.search(text_lower))

        # Inspect each clause independently so modifiers in clause 1 cannot hide threats in clause 2
        clause_phys = False
        clause_extort = False
        clause_coerce = False
        clause_indirect = False
        clause_harass = False
        unmodified_phys_clause = False

        for cl in clauses:
            cl_neg = self._clause_has_any(cl, NEGATION_PATTERNS)
            cl_rep = self._clause_has_any(cl, REPORTED_SPEECH_PATTERNS) or bool(QUOTED_SPAN_RE.search(cl))
            cl_hyp = self._clause_has_any(cl, HYPOTHETICAL_PATTERNS)

            c_phys = (not cl_neg) and self._clause_has_any(cl, DIRECT_PHYSICAL_THREAT_PATTERNS)
            c_ext = (not cl_neg) and self._clause_has_any(cl, EXTORTION_PATTERNS)
            c_coer = (not cl_neg) and self._clause_has_any(cl, COERCION_PATTERNS)
            c_ind = (not cl_neg) and self._clause_has_any(cl, INDIRECT_INTIMIDATION_PATTERNS)
            c_har = (not cl_neg) and self._clause_has_any(cl, VERBAL_HARASSMENT_PATTERNS)

            # Handle comma-attached additive speaker threat after reported speech (e.g. "Sabi niya ..., at sasapakin din kita ngayon!")
            if c_phys and "din kita" in cl and cl_rep:
                parts_at = re.split(r",?\s*\bat\s+", cl, maxsplit=1)
                if len(parts_at) == 2 and self._clause_has_any(parts_at[1], DIRECT_PHYSICAL_THREAT_PATTERNS):
                    unmodified_phys_clause = True

            clause_phys = clause_phys or c_phys
            clause_extort = clause_extort or c_ext
            clause_coerce = clause_coerce or c_coer
            clause_indirect = clause_indirect or c_ind
            clause_harass = clause_harass or c_har
            if c_phys and not (cl_rep or cl_hyp):
                unmodified_phys_clause = True

        # Handle rhetorical immediate hypothetical threats ("Paano kung sapakin kita ngayon?")
        rhetorical_immediate_threat = bool(
            has_hypothetical
            and RHETORICAL_ASSAULT_RE.search(text_lower)
            and any(re.search(m, text_lower) for m in IMMEDIATE_TIME_MARKERS)
        )

        # Priority 1: Active threat inside reported/quoted frame stays REPORTED_THREAT
        if (has_reported or has_quoted) and not unmodified_phys_clause and not clause_extort and not clause_coerce:
            if (
                clause_phys
                or clause_indirect
                or clause_harass
                or has_identity
                or has_past_harm
                or bool(REPORTED_HARM_VERB_RE.search(text_lower))
            ):
                flags.append("Reported or quoted statement: speaker relaying third-party utterance")
                if has_past_harm or PAST_TIME_RE.search(text_lower) or FICTION_OR_MEDIA_RE.search(text_lower):
                    flags.append("Past or fictional/media framing lowers operational urgency")
                return _RuleSignals(
                    intent=ThreatIntent.REPORTED_THREAT,
                    threat_type=ThreatType.SOCIAL_INTIMIDATION,
                    risk_flags=flags,
                    humor_marker=has_humor,
                    quoted_speech=has_quoted,
                    reported_speech=True,
                    negated=has_negation,
                    past_reference=has_past_harm or bool(PAST_TIME_RE.search(text_lower)),
                    hypothetical=has_hypothetical,
                    has_modifier=True,
                    review_hint=True,
                )

        # Priority 2: Direct physical threat (active or humor-masked)
        if clause_phys and (not has_hypothetical or rhetorical_immediate_threat):
            flags.append("Explicit direct physical violence threat detected")
            if has_humor:
                flags.append("Humor disclaimer paired with serious threat — retained for human review")
            if has_negation:
                flags.append("Contrastive negation did not cancel active threat clause")
            if has_past_harm or PAST_TIME_RE.search(text_lower):
                flags.append("Temporal past marker present alongside active threat")
            return _RuleSignals(
                intent=ThreatIntent.DIRECT_THREAT,
                threat_type=ThreatType.PHYSICAL_VIOLENCE,
                risk_flags=flags,
                humor_marker=has_humor,
                quoted_speech=has_quoted,
                reported_speech=has_reported,
                negated=has_negation,
                past_reference=has_past_harm,
                has_modifier=has_humor,
                review_hint=has_humor or has_negation,
            )

        # Priority 3: Rhetorical immediate threat framed as "what if / paano kung ... right now"
        if rhetorical_immediate_threat:
            flags.append("Immediate violent rhetorical question requires safety escalation")
            return _RuleSignals(
                intent=ThreatIntent.DIRECT_THREAT,
                threat_type=ThreatType.SOCIAL_INTIMIDATION,
                risk_flags=flags,
                hypothetical=True,
                review_hint=True,
            )

        # Priority 4: Extortion (never suppressed by "joke lang")
        if clause_extort and not has_hypothetical:
            flags.append("Extortion / demand for money or property detected")
            if has_humor:
                flags.append("Humor disclaimer paired with extortion — retained for human review")
            return _RuleSignals(
                intent=ThreatIntent.EXTORTION,
                threat_type=ThreatType.EXTORTION,
                risk_flags=flags,
                humor_marker=has_humor,
                has_modifier=has_humor,
                review_hint=True,
            )

        # Priority 5: Coercion / secrecy enforcement
        if clause_coerce and not has_hypothetical:
            flags.append("Coercion / secrecy enforcement pattern detected")
            if has_humor:
                flags.append("Humor disclaimer paired with coercion — retained for human review")
            return _RuleSignals(
                intent=ThreatIntent.COERCION,
                threat_type=ThreatType.COERCION,
                risk_flags=flags,
                humor_marker=has_humor,
                has_modifier=has_humor,
                review_hint=True,
            )

        # Priority 6: Indirect / veiled school intimidation
        if clause_indirect and not has_hypothetical:
            flags.append("Indirect or veiled intimidation pattern detected")
            if has_humor:
                flags.append("Humor disclaimer paired with indirect intimidation — retained for human review")
            return _RuleSignals(
                intent=ThreatIntent.DIRECT_THREAT,
                threat_type=ThreatType.SOCIAL_INTIMIDATION,
                risk_flags=flags,
                humor_marker=has_humor,
                has_modifier=has_humor,
                review_hint=True,
            )

        # Priority 7: Hypothetical & Dream statements (with no active immediate threat)
        if has_hypothetical:
            flags.append("Hypothetical, dream, or speculative phrasing detected")
            return _RuleSignals(
                intent=ThreatIntent.HYPOTHETICAL_THREAT,
                threat_type=ThreatType.NONE,
                risk_flags=flags,
                hypothetical=True,
                has_modifier=True,
            )

        # Priority 8: Explicit negation (with no active threat/extortion/coercion clause)
        if has_negation:
            flags.append("Threat action explicitly negated / disclaimed")
            return _RuleSignals(
                intent=ThreatIntent.NEGATED_THREAT,
                threat_type=ThreatType.NONE,
                risk_flags=flags,
                negated=True,
                has_modifier=True,
            )

        # Priority 9: Past confrontation (requires harm verb + past timeframe, and NO active threat)
        if has_past_harm:
            flags.append("Past incident reference: altercation occurred in prior timeframe")
            return _RuleSignals(
                intent=ThreatIntent.PAST_INCIDENT,
                threat_type=ThreatType.PHYSICAL_VIOLENCE,
                risk_flags=flags,
                past_reference=True,
                has_modifier=True,
                review_hint=True,
            )

        # Priority 10: Targeted verbal harassment (respecting mutual banter unless discomfort signaled)
        if clause_harass:
            if is_banter and not has_hostile_corr:
                flags.append("Friendly peer/gaming banter cues detected alongside colloquial teasing")
                return _RuleSignals(
                    intent=ThreatIntent.ORDINARY_CONVERSATION,
                    threat_type=ThreatType.NONE,
                    risk_flags=flags,
                    humor_marker=has_humor or bool(BANTER_LAUGHTER_RE.search(text_lower)),
                    friendly_banter=True,
                    has_modifier=True,
                )
            flags.append("Targeted derogatory insult, exclusion, or verbal harassment detected")
            return _RuleSignals(
                intent=ThreatIntent.VERBAL_HARASSMENT,
                threat_type=ThreatType.VERBAL_HARASSMENT,
                risk_flags=flags,
                discomfort_signal=has_discomfort,
                review_hint=bool(has_humor),
            )

        # Priority 11: Identity-sensitive expression ("Hoy, bakla ka!") — NEVER auto-escalate without hostile context
        if has_identity:
            if is_banter and not has_hostile_corr and not recent_discomfort:
                flags.append("Identity term used in friendly banter / peer context")
                return _RuleSignals(
                    intent=ThreatIntent.ORDINARY_CONVERSATION,
                    threat_type=ThreatType.NONE,
                    risk_flags=flags,
                    humor_marker=True,
                    friendly_banter=True,
                    has_modifier=True,
                )
            if has_hostile_corr or recent_discomfort:
                flags.append("Identity term paired with hostile exclusion or post-discomfort repetition")
                return _RuleSignals(
                    intent=ThreatIntent.VERBAL_HARASSMENT,
                    threat_type=ThreatType.VERBAL_HARASSMENT,
                    risk_flags=flags,
                    discomfort_signal=has_discomfort,
                    review_hint=True,
                )
            flags.append("Identity-sensitive expression without corroborating tone or context -> human review")
            return _RuleSignals(
                intent=ThreatIntent.AMBIGUOUS_CONTEXT,
                threat_type=ThreatType.SOCIAL_INTIMIDATION,
                risk_flags=flags,
                ambiguity_reason="Identity-sensitive expression lacks corroborating threat or tone.",
                review_hint=True,
            )

        # Priority 12: Genuine friendly banter without harassment
        if is_banter:
            flags.append("Friendly peer or gaming/sports banter")
            return _RuleSignals(
                intent=ThreatIntent.ORDINARY_CONVERSATION,
                threat_type=ThreatType.NONE,
                risk_flags=flags,
                humor_marker=has_humor or bool(BANTER_LAUGHTER_RE.search(text_lower)),
                friendly_banter=True,
                has_modifier=True,
            )

        # Priority 13: Benign idioms / pure humor disclaimers without harm
        if has_idiom or has_humor:
            for desc in idiom_hits + humor_hits:
                flags.append(f"Recognized benign idiom/humor: {desc}")
            return _RuleSignals(
                intent=ThreatIntent.ORDINARY_CONVERSATION,
                threat_type=ThreatType.NONE,
                risk_flags=flags,
                humor_marker=has_humor,
                has_modifier=True,
            )

        # Priority 14: Explicitly ambiguous / context-insufficient utterances -> AMBIGUOUS_CONTEXT + review
        for pat, desc in AMBIGUOUS_PHRASE_PATTERNS:
            if pat.search(text_lower):
                flags.append(desc)
                return _RuleSignals(
                    intent=ThreatIntent.AMBIGUOUS_CONTEXT,
                    threat_type=ThreatType.SOCIAL_INTIMIDATION,
                    risk_flags=flags,
                    discomfort_signal=has_discomfort,
                    ambiguity_reason=desc,
                    review_hint=True,
                )

        # Priority 14B: Conservative ASR-slip rescue on normalized copy -> WARNING review (NEVER DANGER)
        if not (has_negation or has_hypothetical or has_reported or has_quoted or is_banter or has_idiom or has_humor):
            normalized_copy = re.sub(r"[^a-z0-9ñ'\s-]", " ", text_lower).replace("-", " ")
            normalized_copy = re.sub(r"\s+", " ", normalized_copy).strip()
            slip_match = _detect_asr_slip_threat(normalized_copy)
            if slip_match is not None:
                slip_tok, slip_root = slip_match
                flags.append(
                    f"ASR-slip threat rescue: token '{slip_tok}' resembles '{slip_root}' "
                    "in hostile second-person framing -> human review"
                )
                return _RuleSignals(
                    intent=ThreatIntent.AMBIGUOUS_CONTEXT,
                    threat_type=ThreatType.SOCIAL_INTIMIDATION,
                    risk_flags=flags,
                    discomfort_signal=has_discomfort,
                    ambiguity_reason=(
                        f"Possible ASR slip ('{slip_tok}' resembling '{slip_root}') in hostile framing."
                    ),
                    review_hint=True,
                    asr_slip_rescue=True,
                )

        # Priority 15: Untargeted profanity / venting
        if self._clause_has_any(text_lower, UNTARGETED_PROFANITY_PATTERNS):
            flags.append("Untargeted profanity / conversational venting")
            return _RuleSignals(
                intent=ThreatIntent.ORDINARY_CONVERSATION,
                threat_type=ThreatType.NONE,
                risk_flags=flags,
            )

        return _RuleSignals(
            intent=ThreatIntent.ORDINARY_CONVERSATION,
            threat_type=ThreatType.NONE,
            risk_flags=flags,
            discomfort_signal=has_discomfort,
        )

    def analyze_intent(
        self,
        text: str,
        recent_discomfort: bool = False,
    ) -> Tuple[ThreatIntent, ThreatType, List[str]]:
        """Public intent analysis method (compatible with V3 signature)."""
        sig = self._extract_rule_signals(text, recent_discomfort=recent_discomfort)
        return sig.intent, sig.threat_type, sig.risk_flags

    # -------------------------------------------------------------------------
    # STAGE 2B: TRANSFORMER SEMANTIC INFERENCE + CONFIDENCE GATING
    # -------------------------------------------------------------------------
    def predict_transformer(self, text: str) -> Dict[str, Any]:
        """
        Run local TagalogBERT / RoBERTa classifier if weights & tokenizer are attached.
        Gracefully degrades to rules whenever weights are missing or inference fails.
        """
        if self.bert_model is None or self.tokenizer is None:
            return {
                "used": False,
                "label": None,
                "confidence": 0.0,
                "probabilities": None,
                "reason": "Transformer weights unavailable",
            }
        try:
            import torch

            inputs = self.tokenizer(
                text,
                return_tensors="pt",
                truncation=True,
                max_length=self.bert_max_length,
            )
            device = None
            if hasattr(self.bert_model, "parameters"):
                try:
                    device = next(self.bert_model.parameters()).device
                except StopIteration:
                    device = None
            if device is not None and hasattr(inputs, "items"):
                inputs = {k: (v.to(device) if hasattr(v, "to") else v) for k, v in inputs.items()}

            with torch.no_grad():
                outputs = self.bert_model(**inputs)
                logits = outputs.logits if hasattr(outputs, "logits") else outputs[0]
                probs_t = torch.softmax(logits, dim=-1)[0]
                probs = [float(x) for x in probs_t.tolist()]

            pred_label = int(max(range(len(probs)), key=lambda i: probs[i]))
            conf = float(probs[pred_label])
            prob_map = {str(i): round(p, 4) for i, p in enumerate(probs)}
            return {
                "used": True,
                "label": pred_label,
                "confidence": round(conf, 4),
                "probabilities": prob_map,
                "reason": "OK",
            }
        except Exception as exc:
            logger.warning("TagalogBERT inference failed; falling back to rules: %s", exc)
            return {
                "used": False,
                "label": None,
                "confidence": 0.0,
                "probabilities": None,
                "reason": f"Transformer fallback: {exc}",
            }

    def _fuse_with_transformer(
        self,
        sig: _RuleSignals,
        bert_res: Dict[str, Any],
    ) -> Tuple[_RuleSignals, float, bool]:
        """
        Fuse rule signals with TagalogBERT output.
        Returns (updated_signals, model_confidence, semantic_cap_below_danger).
        """
        if not bert_res.get("used"):
            return sig, 0.0 if self.bert_model is not None else 1.0, False

        conf = float(bert_res.get("confidence", 0.0))
        label = bert_res.get("label")

        if conf < self.bert_confidence_threshold or label is None:
            sig.risk_flags.append(
                f"Transformer confidence {conf:.2f} < {self.bert_confidence_threshold:.2f} -> rules fallback"
            )
            return sig, conf, False

        # Never allow transformer to escalate conservative ASR-slip rescue above WARNING review
        if sig.asr_slip_rescue:
            sig.risk_flags.append("ASR-slip rescue locked below DANGER for human review")
            return sig, conf, True

        # Never allow transformer to override explicit protective contexts or verified friendly banter
        if sig.has_modifier and sig.intent in (
            ThreatIntent.ORDINARY_CONVERSATION,
            ThreatIntent.NEGATED_THREAT,
            ThreatIntent.HYPOTHETICAL_THREAT,
            ThreatIntent.REPORTED_THREAT,
            ThreatIntent.PAST_INCIDENT,
        ):
            sig.risk_flags.append(f"Protective linguistic modifier retained alongside TagalogBERT label={label}")
            return sig, conf, False

        # Upgrade unpatterned ordinary utterances when BERT has high semantic confidence
        if sig.intent == ThreatIntent.ORDINARY_CONVERSATION and label in (1, 2, 3):
            mapped_intent, mapped_type, _ = BERT_LABEL_TO_INTENT[int(label)]
            sig.intent = mapped_intent
            sig.threat_type = mapped_type
            sig.review_hint = True
            sig.risk_flags.append(
                f"TagalogBERT semantic classification (label={label}, conf={conf:.2f})"
            )
            # Without explicit physical-threat rule corroboration, cap semantics < DANGER
            return sig, conf, (int(label) == 3)

        # Corroborate or flag disagreement with rules
        if sig.intent in (
            ThreatIntent.VERBAL_HARASSMENT,
            ThreatIntent.EXTORTION,
            ThreatIntent.COERCION,
            ThreatIntent.DIRECT_THREAT,
        ):
            if label in (1, 2, 3):
                sig.risk_flags.append(f"TagalogBERT semantic corroboration (label={label}, conf={conf:.2f})")
            elif label == 0 and conf >= 0.80:
                sig.review_hint = True
                sig.risk_flags.append(f"TagalogBERT predicted benign (conf={conf:.2f}); flagged for review")

        return sig, conf, False

    # -------------------------------------------------------------------------
    # STAGE 3: CONTEXT EXTRACTION
    # -------------------------------------------------------------------------
    def extract_context(
        self,
        text: str,
        intent: ThreatIntent,
        threat_type: ThreatType,
        evidence_reliability: EvidenceReliability,
        signals: Optional[_RuleSignals] = None,
        bert_res: Optional[Dict[str, Any]] = None,
        model_confidence: float = 1.0,
        escalation_metrics: Optional[Dict[str, Any]] = None,
    ) -> ContextExtraction:
        """Extracts structured contextual dimensions with word-boundary checks."""
        text_lower = text.lower()
        words = set(re.findall(r"\b\w+\b", text_lower))

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

        imminence = Imminence.NONE
        time_ref = None
        if intent == ThreatIntent.PAST_INCIDENT:
            imminence = Imminence.PAST
            time_ref = "past"
        elif intent == ThreatIntent.HYPOTHETICAL_THREAT:
            imminence = Imminence.HYPOTHETICAL
            time_ref = "hypothetical"
        else:
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

        has_specific_location = bool(LOCATION_RE.search(text_lower))
        has_specific_weapon = bool(WEAPON_RE.search(text_lower))
        if has_specific_weapon or (has_specific_location and imminence in (Imminence.IMMEDIATE, Imminence.FUTURE_SPECIFIC)):
            specificity = "HIGH"
        elif has_specific_location or imminence not in (Imminence.NONE, Imminence.PAST):
            specificity = "MEDIUM"
        else:
            specificity = "LOW"

        esc = escalation_metrics or {}
        br = bert_res or {}
        sig = signals or _RuleSignals(intent=intent, threat_type=threat_type)
        ep_count = int(esc.get("distinct_episodes", 1))

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
            repetition=int(esc.get("total_recent", 0)) >= 1 and not bool(esc.get("incoming_is_split_chunk", False)),
            persistence=ep_count >= 2,
            evidence_reliability=evidence_reliability,
            reported_speech=(intent == ThreatIntent.REPORTED_THREAT or sig.reported_speech),
            negated=(intent == ThreatIntent.NEGATED_THREAT or sig.negated),
            model_confidence=float(model_confidence),
            model_used=bool(br.get("used", False)),
            model_label=br.get("label"),
            model_probabilities=br.get("probabilities"),
            humor_marker=sig.humor_marker,
            quoted_speech=sig.quoted_speech,
            past_reference=sig.past_reference,
            episode_id=int(esc.get("next_episode_id", 1)),
            distinct_episodes=ep_count,
            is_split_chunk=bool(esc.get("incoming_is_split_chunk", False)),
        )

    # -------------------------------------------------------------------------
    # STAGE 4 & 5: SITUATIONAL RISK ASSESSMENT & SEVERITY SCORING
    # -------------------------------------------------------------------------
    def score_threat(
        self,
        text: str,
        context: ContextExtraction,
        risk_flags: List[str],
        escalation_metrics: Dict[str, Any],
        semantic_cap_below_danger: bool = False,
        review_hint: bool = False,
    ) -> Tuple[float, str, str, str, str, bool]:
        """Calculates severity score (0-10), level, category, explanation, response, and review flag."""
        intent = context.intent
        threat_type = context.threat_type
        human_review = bool(review_hint)

        if intent == ThreatIntent.ORDINARY_CONVERSATION:
            base_score = 1.0
            category = "Conversational"
            explanation = "Ordinary conversational speech, friendly banter, or benign idiom without threat indicators."
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

        elif intent == ThreatIntent.AMBIGUOUS_CONTEXT:
            is_asr_slip = any(rf.startswith("ASR-slip threat rescue:") for rf in risk_flags)
            if is_asr_slip:
                base_score = 3.5
                category = "ASR-Slip Threat Review"
                explanation = (
                    "Possible ASR transcription slip resembling a physical threat in hostile "
                    "second-person framing; routed for human review."
                )
            else:
                base_score = 3.0
                category = "Ambiguous Context (Needs Review)"
                explanation = "Context-dependent or ambiguous expression without corroborating threat; flagged for human review."
            response = "Queue for trusted adult / counselor review without emergency escalation."
            human_review = True

        elif intent == ThreatIntent.PAST_INCIDENT:
            base_score = 3.5
            category = "Warning / Incident Report"
            explanation = "Speaker described a past confrontation or historic altercation. Not an active emergency."
            response = "Flag for student counselor or prefect review during normal hours."
            human_review = True

        elif intent == ThreatIntent.REPORTED_THREAT:
            text_lower = text.lower()
            is_low_urgency_report = bool(
                FICTION_OR_MEDIA_RE.search(text_lower)
                or PAST_TIME_RE.search(text_lower)
                or context.past_reference
            )
            base_score = 3.5 if is_low_urgency_report else 5.0
            category = "Reported Threat"
            explanation = "Speaker reported or quoted a threat attributed to someone else. Administrative review required; not an active physical emergency."
            response = "Notify designated guidance counselor/prefect to review the reported context."
            human_review = True

        elif intent == ThreatIntent.VERBAL_HARASSMENT:
            text_lower = text.lower()
            is_sarcastic_mild = bool(
                re.search(r"\b(wow,?\s+ang\s+talino|great\s+job\s+genius)\b", text_lower)
            )
            if is_sarcastic_mild:
                base_score = 3.5
                category = "Verbal Harassment (Mild / Sarcasm)"
                explanation = "Sarcastic put-down / academic mockery flagged as low-to-moderate warning."
                response = "Log warning and monitor for repeated harassment."
                human_review = True
            elif context.targetedness == Targetedness.DIRECT_SECOND_PERSON:
                base_score = 6.0
                category = "Verbal Harassment"
                explanation = "Direct personal insults, exclusion, or derogatory slurs targeting another individual."
                response = "Notify educator/prefect of verbal bullying for behavioral intervention."
            else:
                base_score = 5.5 if HOSTILE_CORROBORATION_RE.search(text_lower) else 2.8
                category = "Verbal Harassment" if base_score >= 4.0 else "Conversational"
                explanation = (
                    "Third-person or group exclusion / derogatory remark."
                    if base_score >= 4.0
                    else "Untargeted profanity or emotional venting without direct personal target."
                )
                response = "Log and monitor for escalation."

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
                is_lethal = bool(re.search(r"\b(pa\s*patayin|kill|sa\s*saksakin|stab|ba\s*barilin|shoot|i\s*tutumba|ka\s*katayin)\b", text_lower))
                if context.humor_marker:
                    base_score = 7.4 if is_lethal else 7.0
                    category = "Physical Threat (Humor-Masked)"
                    explanation = "Serious physical threat paired with a joke disclaimer; never suppressed and routed for review."
                    response = "Immediate counselor/prefect review required (humor disclaimer on physical threat)."
                    human_review = True
                elif is_lethal:
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
                base_score = 6.2
                category = "Social Intimidation"
                explanation = "Veiled, semantic, or indirect school intimidation forecasting potential harm."
                response = "Elevated safety alert: check on targeted student and investigate aggressor."
                human_review = True
        else:
            base_score = 1.0
            category = "Conversational"
            explanation = "Indeterminate intent; classified as conversational."
            response = "Normal monitoring."

        # Contextual Time / Location Adjustments
        score = base_score
        if category != "Conversational" and intent not in (ThreatIntent.PAST_INCIDENT, ThreatIntent.AMBIGUOUS_CONTEXT):
            if context.imminence == Imminence.IMMEDIATE:
                score += 0.5
                risk_flags.append("Immediate temporal proximity (+0.5)")
            elif context.imminence == Imminence.FUTURE_SPECIFIC:
                score += 0.3
                risk_flags.append("Specific scheduled timeframe (+0.3)")

            if context.location_reference:
                score += 0.3
                risk_flags.append("Specific campus location referenced (+0.3)")

        # Episode-Aware Stage 6 Escalation Adjustments
        incoming_is_split = bool(escalation_metrics.get("incoming_is_split_chunk", False))
        harass_trigger_count = max(
            int(escalation_metrics.get("harassment_episode_count", 0)),
            int(escalation_metrics.get("harassment_non_split_count", 0)),
        )
        extort_trigger_count = max(
            int(escalation_metrics.get("extortion_episode_count", 0)),
            int(escalation_metrics.get("extortion_non_split_count", 0)),
        )
        intim_trigger_count = max(
            int(escalation_metrics.get("intimidation_episode_count", 0)),
            int(escalation_metrics.get("intimidation_non_split_count", 0)),
        )

        if incoming_is_split and intent in (
            ThreatIntent.VERBAL_HARASSMENT,
            ThreatIntent.EXTORTION,
            ThreatIntent.COERCION,
        ):
            risk_flags.append("Grouped within active conversation episode (split-stream protection)")
        elif incoming_is_split and intent == ThreatIntent.DIRECT_THREAT and threat_type == ThreatType.SOCIAL_INTIMIDATION:
            risk_flags.append("Grouped within active conversation episode (split-stream protection)")
        else:
            if intent == ThreatIntent.VERBAL_HARASSMENT:
                if harass_trigger_count >= 2:
                    score = max(score, 7.2)
                    category = "Escalated Harassment"
                    risk_flags.append(f"Repeated verbal harassment across {harass_trigger_count + 1} episodes")
                elif harass_trigger_count == 1:
                    score = max(score, 6.5)
                    risk_flags.append("Repeated verbal harassment episode in window")
            elif intent == ThreatIntent.EXTORTION:
                if extort_trigger_count >= 1:
                    score = max(score, 7.5)
                    risk_flags.append(f"Repeated extortion across {extort_trigger_count + 1} episodes")
            elif intent == ThreatIntent.DIRECT_THREAT and threat_type == ThreatType.SOCIAL_INTIMIDATION:
                if intim_trigger_count >= 1:
                    score = max(score, 7.6)
                    category = "Escalated Intimidation"
                    risk_flags.append(f"Repeated indirect intimidation across {intim_trigger_count + 1} episodes")

        # Hard Safety Boundaries & Caps (NEVER weaken emergency safeguards)
        # 1. Non-physical, humor-masked, semantic-only, and ambiguous events CANNOT trigger DANGER (>= 8.0)
        if (
            intent != ThreatIntent.DIRECT_THREAT
            or threat_type != ThreatType.PHYSICAL_VIOLENCE
            or context.humor_marker
            or semantic_cap_below_danger
        ):
            score = min(score, 7.8)

        # 2. Uncertain transcription evidence CANNOT enter DANGER
        if context.evidence_reliability == EvidenceReliability.UNCERTAIN and score >= 8.0:
            score = 6.5
            risk_flags.append("Evidence uncertain: capped from DANGER to THREAT pending review")
            human_review = True

        # 3. Reported/Quoted/Past/Negated speech CANNOT enter DANGER
        if intent in (ThreatIntent.REPORTED_THREAT, ThreatIntent.QUOTED_THREAT, ThreatIntent.PAST_INCIDENT, ThreatIntent.NEGATED_THREAT):
            score = min(score, 6.0)

        # 4. Ambiguous Context stays within WARNING band pending human review
        if intent == ThreatIntent.AMBIGUOUS_CONTEXT:
            score = min(max(score, 2.0), 3.9)
            human_review = True

        final_score = round(max(0.0, min(10.0, score)), 1)

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
        transcription_result: Optional[Any] = None,
        stream_continuation: bool = False,
    ) -> SeverityAssessment:
        """
        Evaluates a transcript across validation, compositional rules, active
        TagalogBERT fusion, context extraction, and episode-aware escalation.
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
                context=None,
            )

        # Stage 6 Pre-Check: Episode & prior discomfort state for this device
        tracker = self.escalation_manager.get_tracker(dev_id)
        escalation_metrics = tracker.get_escalation_metrics(
            current_time=ts, stream_continuation=stream_continuation
        )
        recent_discomfort = bool(escalation_metrics.get("recent_discomfort", False))

        # Stage 2A: Compositional Rule Signal Extraction
        signals = self._extract_rule_signals(text, recent_discomfort=recent_discomfort)

        # Stage 2B: Active TagalogBERT Semantic Inference + Confidence-Gated Fusion
        bert_res = self.predict_transformer(text)
        signals, model_conf, semantic_cap = self._fuse_with_transformer(signals, bert_res)

        # Stage 3: Context Extraction
        context = self.extract_context(
            text=text,
            intent=signals.intent,
            threat_type=signals.threat_type,
            evidence_reliability=reliability,
            signals=signals,
            bert_res=bert_res,
            model_confidence=model_conf,
            escalation_metrics=escalation_metrics,
        )

        # Stage 4 & 5: Risk Assessment & Severity Scoring
        score, level, category, explanation, response, human_review = self.score_threat(
            text=text,
            context=context,
            risk_flags=signals.risk_flags,
            escalation_metrics=escalation_metrics,
            semantic_cap_below_danger=semantic_cap,
            review_hint=signals.review_hint,
        )

        # Record statement with episode tracking for future turns
        tracker.add_statement(
            text=text,
            intent=signals.intent,
            threat_type=signals.threat_type,
            score=score,
            category=category,
            timestamp=ts,
            stream_continuation=stream_continuation,
            discomfort_signal=signals.discomfort_signal,
        )

        ev_conf = model_conf if bert_res.get("used") else (1.0 if reliability == EvidenceReliability.HIGH else 0.5)
        if reliability == EvidenceReliability.UNCERTAIN:
            ev_conf = min(ev_conf, 0.5)

        return SeverityAssessment(
            score=score,
            level=level,
            category=category,
            intent=signals.intent,
            threat_type=signals.threat_type,
            targetedness=context.targetedness,
            imminence=context.imminence,
            risk_factors=signals.risk_flags,
            evidence_confidence=round(float(ev_conf), 4),
            explanation=explanation,
            recommended_response=response,
            human_review_required=human_review,
            context=context,
        )

    @property
    def history(self) -> List[float]:
        """Backward compatibility for legacy code checking context_engine.history."""
        tracker = self.escalation_manager.get_tracker("DEFAULT")
        return [stmt.score for stmt in tracker.history]


# Global singleton instance for server.py import
context_engine = ContextEngine()
