#!/usr/bin/env python3
"""Western astrology birth time rectification engine.

Interpretation-free, layered candidate evidence.
Five scoring layers: natal house+lord, transits, secondary progressions,
solar arc directions (Naibod), and annual profections.
ASC sign anchor eliminates mismatched candidates.

This module is read-only with respect to western_chart.py and app.py;
it only consumes core chart output via calculate_core_chart().
"""

from __future__ import annotations

import math
from datetime import datetime, timedelta, timezone
from itertools import product
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    PLANETS,
    SIGNS,
    CLASSICAL_RULERS,
    MODERN_RULERS,
    calculate_core_chart,
)

from .western_primary_directions import (
    calculate_primary_directions,
    PrimaryDirectionsCalculationError,
    PrimaryDirectionsInputError,
)

from .western_solar_return import (
    calculate_solar_return,
    SolarReturnError,
)

from .western_parans import (
    calculate_parans,
    ParansCalculationError,
    ParansInputError,
)

from .western_midpoints import (
    calculate_midpoints,
    MidpointsCalculationError,
    MidpointsInputError,
)

from .western_firdaria import (
    calculate_firdaria,
    FirdariaCalculationError,
    FirdariaInputError,
)


# ---------------------------------------------------------------------------
# Exceptions
# ---------------------------------------------------------------------------


class RectificationInputError(ValueError):
    """Raised when rectification input is invalid."""


class RectificationCalculationError(RuntimeError):
    """Raised when rectification computation fails."""

    def __init__(self, message: str, code: str = "rectification_error"):
        super().__init__(message)
        self.code = code


# ---------------------------------------------------------------------------
# Event rules (interpretation-free, house + ruler + karaka mapping)
# ---------------------------------------------------------------------------

# Houses are 1-indexed Western houses.
# classical_rulers reference: only Sun-Saturn (traditional 7 visible).
# modern_rulers add Uranus/Neptune/Pluto for the relevant signs.
# karaka_planets are natural significators independent of birth chart.

RECTIFICATION_EVENT_RULES = {
    "marriage": {
        "topic": "marriage",
        "houses": [7, 5, 11, 2],
        "karakas_classical": ["venus", "moon"],
        "karakas_modern": ["venus", "moon"],
        "primary_rulers": ["7", "5"],
    },
    "divorce": {
        "topic": "marriage",
        "houses": [7, 12, 8, 6],
        "karakas_classical": ["mars", "saturn"],
        "karakas_modern": ["mars", "saturn", "pluto", "uranus"],
        "primary_rulers": ["7", "8", "12"],
    },
    "childbirth": {
        "topic": "marriage",
        "houses": [5, 4, 11, 2],
        "karakas_classical": ["jupiter", "venus", "moon"],
        "karakas_modern": ["jupiter", "venus", "moon"],
        "primary_rulers": ["5", "4"],
    },
    "career": {
        "topic": "career",
        "houses": [10, 6, 2, 11],
        "karakas_classical": ["sun", "saturn", "mars", "mercury"],
        "karakas_modern": ["sun", "saturn", "mars", "mercury"],
        "primary_rulers": ["10", "6"],
    },
    "job_change": {
        "topic": "career",
        "houses": [10, 6, 2, 11],
        "karakas_classical": ["mercury", "saturn"],
        "karakas_modern": ["mercury", "saturn", "uranus"],
        "primary_rulers": ["10", "6"],
    },
    "education": {
        "topic": "career",
        "houses": [9, 3, 5, 4],
        "karakas_classical": ["mercury", "jupiter"],
        "karakas_modern": ["mercury", "jupiter"],
        "primary_rulers": ["9", "3"],
    },
    "relocation": {
        "topic": "career",
        "houses": [4, 3, 9, 12],
        "karakas_classical": ["moon", "saturn"],
        "karakas_modern": ["moon", "uranus", "saturn"],
        "primary_rulers": ["4", "9"],
    },
    "health": {
        "topic": "health",
        "houses": [1, 6, 8, 12],
        "karakas_classical": ["sun", "moon", "mars", "saturn"],
        "karakas_modern": ["sun", "moon", "mars", "saturn"],
        "primary_rulers": ["1", "6"],
    },
    "accident": {
        "topic": "health",
        "houses": [1, 8, 12, 6],
        "karakas_classical": ["mars", "saturn"],
        "karakas_modern": ["mars", "uranus", "saturn"],
        "primary_rulers": ["1", "8"],
    },
    "surgery": {
        "topic": "health",
        "houses": [8, 6, 1, 12],
        "karakas_classical": ["mars", "saturn"],
        "karakas_modern": ["mars", "pluto", "saturn"],
        "primary_rulers": ["6", "8"],
    },
    "death_family": {
        "topic": "health",
        "houses": [4, 10, 8, 12],
        "karakas_classical": ["saturn", "mars"],
        "karakas_modern": ["saturn", "pluto", "mars"],
        "primary_rulers": ["4", "10", "8"],
    },
    "wealth": {
        "topic": "wealth",
        "houses": [2, 8, 11, 5],
        "karakas_classical": ["jupiter", "venus", "mercury"],
        "karakas_modern": ["jupiter", "venus", "mercury"],
        "primary_rulers": ["2", "11"],
    },
    "property": {
        "topic": "wealth",
        "houses": [4, 2, 11],
        "karakas_classical": ["saturn", "moon", "mars"],
        "karakas_modern": ["saturn", "moon", "mars"],
        "primary_rulers": ["4", "2"],
    },
    "business": {
        "topic": "wealth",
        "houses": [10, 7, 2, 11, 6],
        "karakas_classical": ["mercury", "jupiter", "mars"],
        "karakas_modern": ["mercury", "jupiter", "mars"],
        "primary_rulers": ["10", "2"],
    },
    "legal": {
        "topic": "legal",
        "houses": [9, 7, 12, 6, 8],
        "karakas_classical": ["jupiter", "saturn", "mars"],
        "karakas_modern": ["jupiter", "saturn", "mars", "pluto"],
        "primary_rulers": ["9", "7"],
    },
    "family": {
        "topic": "family",
        "houses": [4, 10, 3, 2],
        "karakas_classical": ["moon", "saturn", "sun"],
        "karakas_modern": ["moon", "saturn", "sun"],
        "primary_rulers": ["4", "10"],
    },
    "spiritual_shift": {
        "topic": "spiritual",
        "houses": [9, 12, 8],
        "karakas_classical": ["jupiter", "saturn"],
        "karakas_modern": ["jupiter", "neptune", "pluto", "saturn"],
        "primary_rulers": ["9", "12"],
    },
}

RECTIFICATION_EVENT_TOPIC_ALIASES = {
    # English aliases
    "relationship": "marriage",
    "partner": "marriage",
    "separation": "divorce",
    "children": "childbirth",
    "birth_child": "childbirth",
    "job": "career",
    "work": "career",
    "promotion": "career",
    "graduation": "education",
    "exam": "education",
    "school": "education",
    "migration": "relocation",
    "move": "relocation",
    "finance": "wealth",
    "money": "wealth",
    "inheritance": "wealth",
    "real_estate": "property",
    "court": "legal",
    "imprisonment": "legal",
    "lawsuit": "legal",
    "illness": "health",
    "disease": "health",
    "crisis": "spiritual_shift",
    "awakening": "spiritual_shift",
    "home": "family",
    "parents": "family",
    # Turkish aliases
    "evlilik": "marriage",
    "ilişki": "marriage",
    "iliski": "marriage",
    "boşanma": "divorce",
    "bosanma": "divorce",
    "çocuk": "childbirth",
    "cocuk": "childbirth",
    "kariyer": "career",
    "iş": "career",
    "is": "career",
    "iş_değişikliği": "job_change",
    "is_degisikligi": "job_change",
    "eğitim": "education",
    "egitim": "education",
    "okul": "education",
    "taşınma": "relocation",
    "tasinma": "relocation",
    "ev_değiştirme": "relocation",
    "sağlık": "health",
    "saglik": "health",
    "hastalık": "health",
    "hastalik": "health",
    "kaza": "accident",
    "ameliyat": "surgery",
    "aile_kaybı": "death_family",
    "aile_kaybi": "death_family",
    "vefat": "death_family",
    "servet": "wealth",
    "para": "wealth",
    "miras": "wealth",
    "emlak": "property",
    "iş_yeri": "business",
    "is_yeri": "business",
    "ticaret": "business",
    "hukuk": "legal",
    "mahkeme": "legal",
    "aile": "family",
    "anne": "family",
    "baba": "family",
    "ebeveyn": "family",
    "manevi_değişim": "spiritual_shift",
    "manevi_degisim": "spiritual_shift",
}

RECTIFICATION_EVENT_CONFIDENCE_WEIGHTS = {
    "high": 1.0,
    "medium": 0.65,
    "low": 0.35,
}

RECTIFICATION_EVENT_CERTAINTY_WEIGHTS = {
    "time_exact": 1.25,
    "time_known": 1.15,
    "day_exact": 1.0,
    "exact_day": 1.0,
    "date_exact": 1.0,
    "month_exact": 0.75,
    "month_known": 0.75,
    "year_exact": 0.45,
    "year_known": 0.45,
    "approximate": 0.5,
    "unknown": 0.35,
}

LAYER_BASE_WEIGHTS = {
    "natal": 1.0,
    "transit": 1.0,
    "progression": 1.0,
    "solar_arc": 1.0,
    "profection": 1.0,
    "firdaria": 1.0,
    "fixed_stars": 1.0,
    "syzygy": 1.0,
    "parans": 1.0,
    "midpoints": 1.0,
    "primary_directions": 1.0,
    "solar_return": 1.0,
}

# Scoring scale tuned to be comparable to Vedik dasha weights (12/10/7/4).
NATAL_PRIMARY_RULER_WEIGHT = 6.0
NATAL_SECONDARY_RULER_WEIGHT = 3.0
NATAL_KARAKA_IN_HOUSE_WEIGHT = 3.0
NATAL_RULER_IN_RELEVANT_HOUSE_WEIGHT = 4.0

TRANSIT_PLANET_IN_RELEVANT_HOUSE_WEIGHT = 4.0
TRANSIT_HARD_ASPECT_TO_NATAL_WEIGHT = 3.0
TRANSIT_SOFT_ASPECT_TO_NATAL_WEIGHT = 2.0
TRANSIT_TO_RELEVANT_RULER_BONUS = 2.0

PROGRESSION_ANGLE_HIT_WEIGHT = 8.0
PROGRESSION_PLANET_ASPECT_WEIGHT = 6.0
PROGRESSION_MOON_HIT_WEIGHT = 5.0

SOLAR_ARC_ANGLE_HIT_WEIGHT = 10.0
SOLAR_ARC_PLANET_ASPECT_WEIGHT = 7.0

PROFECTION_LORD_TRANSIT_HIT_WEIGHT = 4.0
PROFECTION_HOUSE_OVERLAP_WEIGHT = 3.0

# Firdaria: olay-bağımlı layer (profection'a paralel). Olay tarihinde aktif
# major/sub time-lord, konu evinin karaka/yöneticisiyse bonus alır.
FIRDARIA_MAJOR_LORD_RELEVANT_BONUS = 4.0
FIRDARIA_SUB_LORD_RELEVANT_BONUS = 3.0

# Olay tipine göre layer ağırlıkları (6 olay-bağımlı layer; her tip için toplam ~6.0)
# Klasik öğretiye dayanır: ölüm → PD/SA, evlilik → Prog/Tr, kariyer → SA/Tr, sağlık → Tr/PD
# Fixed_stars ve syzygy olay-bağımsız; bu ayarlardan etkilenmez.
EVENT_TYPE_LAYER_WEIGHTS = {
    "marriage":        {"natal": 1.1, "transit": 1.2, "progression": 1.2, "solar_arc": 1.0, "profection": 0.7, "primary_directions": 0.8, "solar_return": 1.0},
    "divorce":         {"natal": 1.0, "transit": 1.2, "progression": 1.1, "solar_arc": 1.1, "profection": 0.7, "primary_directions": 0.9, "solar_return": 1.0},
    "childbirth":      {"natal": 0.9, "transit": 1.1, "progression": 1.3, "solar_arc": 0.9, "profection": 1.1, "primary_directions": 0.7, "solar_return": 1.0},
    "career":          {"natal": 0.9, "transit": 1.2, "progression": 1.0, "solar_arc": 1.3, "profection": 0.7, "primary_directions": 0.9, "solar_return": 1.0},
    "job_change":      {"natal": 0.9, "transit": 1.2, "progression": 1.0, "solar_arc": 1.3, "profection": 0.7, "primary_directions": 0.9, "solar_return": 1.0},
    "education":       {"natal": 1.0, "transit": 1.0, "progression": 1.2, "solar_arc": 1.0, "profection": 1.1, "primary_directions": 0.7, "solar_return": 1.0},
    "relocation":      {"natal": 0.9, "transit": 1.3, "progression": 1.1, "solar_arc": 0.9, "profection": 1.0, "primary_directions": 0.8, "solar_return": 1.0},
    "health":          {"natal": 0.9, "transit": 1.3, "progression": 1.0, "solar_arc": 0.9, "profection": 0.8, "primary_directions": 1.1, "solar_return": 1.0},
    "accident":        {"natal": 0.9, "transit": 1.4, "progression": 0.9, "solar_arc": 1.0, "profection": 0.8, "primary_directions": 1.0, "solar_return": 1.0},
    "surgery":         {"natal": 0.9, "transit": 1.3, "progression": 0.8, "solar_arc": 1.0, "profection": 0.9, "primary_directions": 1.1, "solar_return": 1.0},
    "death_family":    {"natal": 1.0, "transit": 1.0, "progression": 0.9, "solar_arc": 1.2, "profection": 0.6, "primary_directions": 1.3, "solar_return": 1.0},
    "wealth":          {"natal": 1.0, "transit": 1.1, "progression": 0.9, "solar_arc": 1.1, "profection": 1.2, "primary_directions": 0.7, "solar_return": 1.0},
    "property":        {"natal": 1.0, "transit": 1.2, "progression": 1.1, "solar_arc": 1.0, "profection": 1.0, "primary_directions": 0.7, "solar_return": 1.0},
    "business":        {"natal": 1.0, "transit": 1.2, "progression": 0.9, "solar_arc": 1.2, "profection": 1.0, "primary_directions": 0.7, "solar_return": 1.0},
    "legal":           {"natal": 1.0, "transit": 1.2, "progression": 1.0, "solar_arc": 1.0, "profection": 0.7, "primary_directions": 1.1, "solar_return": 1.0},
    "family":          {"natal": 1.0, "transit": 1.1, "progression": 1.2, "solar_arc": 1.0, "profection": 1.0, "primary_directions": 0.7, "solar_return": 1.0},
    "spiritual_shift": {"natal": 1.0, "transit": 1.2, "progression": 1.2, "solar_arc": 1.0, "profection": 0.7, "primary_directions": 0.9, "solar_return": 1.0},
}

DEFAULT_EVENT_LAYER_WEIGHTS = {
    "natal": 1.0,
    "transit": 1.0,
    "progression": 1.0,
    "solar_arc": 1.0,
    "profection": 1.0,
    "primary_directions": 1.0,
    "solar_return": 1.0,
}


def _event_layer_weights(event_type):
    """Olay tipine göre layer ağırlıklarını döndür (tanımlı değilse default 1.0)."""
    return EVENT_TYPE_LAYER_WEIGHTS.get(event_type, DEFAULT_EVENT_LAYER_WEIGHTS)

# Fixed star tier-based bonus (ASC/MC kavuşumları, orb 1°)
# Olay-bağımsız: aday başına bir kez hesaplanır, toplam skora eklenir.
FIXED_STAR_TIER_BONUS = {
    "royal": 10.0,
    "primary": 5.0,
    "secondary": 2.0,
    "tertiary": 1.0,
}
FIXED_STAR_ANGLE_IDS = ("ascendant", "midheaven")

RECTIFICATION_MAX_CANDIDATES = 121
ASC_ANCHOR_MISMATCH_PENALTY = -10000.0
MC_ANCHOR_MISMATCH_PENALTY = -5000.0

# Sub-minute refinement: top N adayın ±60sn etrafında 10sn step ile yeniden tarama
REFINEMENT_TOP_N = 3
REFINEMENT_RADIUS_SECONDS = 60
REFINEMENT_STEP_SECONDS = 10

# Cross-validation (leave-one-out): top adayın olaylara bağımlılığı
CROSS_VAL_MIN_EVENTS = 2

# Pre-natal Syzygy (Ptolemaios anchor): doğum öncesi son Yeni Ay veya Dolunay
SYZYGY_LOOKBACK_DAYS = 35
SYZYGY_COARSE_STEP_DAYS = 0.25  # 6 saat
SYZYGY_BISECTION_ITERATIONS = 25
SYZYGY_ORB_TIGHT = 1.0
SYZYGY_ORB_WIDE = 2.0
SYZYGY_ASPECT_BONUS = {
    "conjunction": 8.0,
    "opposition": 6.0,
    "square": 5.0,
    "trine": 3.0,
    "sextile": 2.0,
}

# Parans (Brady Visual Astrology): olay-bağımsız, aday bağımlı layer.
# Doğum anına yakın gerçek paran (gezegen/yıldız açısal eşzamanlılığı) doğum
# saatinin astronomik olarak işaretli olduğunu destekleyen klasik bir
# göstergedir; aday başına bir kez hesaplanır (mevcut chart yeniden kullanılır).
PARAN_OFFSET_TIGHT_MINUTES = 5.0
PARAN_OFFSET_WIDE_MINUTES = 15.0
PARAN_TIGHT_BONUS = 8.0
PARAN_WIDE_BONUS = 4.0
PARAN_EXTRA_PER_ADDITIONAL_TIGHT = 2.0
PARAN_MAX_EXTRA_COUNT = 3

# Midpoints (Cosmobiology): olay-bağımsız, aday bağımlı layer.
# ASC veya MC'nin başka bir gezegen çiftinin midpoint'ine (direct veya 180°
# karşıtı) sıkı orb'da denk gelmesi, doğru doğum saatinin klasik bir
# göstergesidir; aday başına bir kez hesaplanır (mevcut chart yeniden kullanılır).
MIDPOINT_RECTIFICATION_ORB = 1.0
MIDPOINT_ANGLE_HIT_BASE_BONUS = 5.0
MIDPOINT_LUMINARY_BONUS = 2.0
MIDPOINT_MAX_HITS_COUNTED = 6

# Primary Directions: olay-bağımlı layer; aday başına bir kez PD compute
PD_DEFAULT_KEY = "ptolemaic"  # 1°/yıl
PD_EVENT_MATCH_TOLERANCE_YEARS = 0.16  # ~60 gün
PD_HARD_ASPECTS = {"conjunction", "opposition", "square"}
PD_SOFT_ASPECTS = {"trine", "sextile"}
PD_HARD_ASPECT_BASE = 5.0
PD_SOFT_ASPECT_BASE = 2.5
PD_PROMISSOR_RELEVANCE_BONUS = 3.0
PD_SIGNIFICATOR_RELEVANCE_BONUS = 2.0
PD_HOUSE_RELEVANCE_BONUS = 2.0
PD_WINDOW_BUFFER_YEARS = 0.5

# Solar Return layer sabitleri
SR_ASC_NATAL_HOUSE_HIT_BONUS = 10.0
SR_MC_NATAL_HOUSE_HIT_BONUS = 8.0
SR_THEME_PLANET_RELEVANT_BONUS = 5.0
SR_NATAL_HARD_ASPECT_BONUS = 4.0
SR_NATAL_SOFT_ASPECT_BONUS = 2.0
SR_HARD_ASPECTS = {"conjunction", "opposition", "square"}

# Aspect set used by transit/progression/solar-arc layers.
HARD_ASPECTS = {
    "conjunction": 0.0,
    "opposition": 180.0,
    "square": 90.0,
}
SOFT_ASPECTS = {
    "trine": 120.0,
    "sextile": 60.0,
}
ALL_ASPECTS = {**HARD_ASPECTS, **SOFT_ASPECTS}

TRANSIT_ORB_NATAL = 1.5  # degrees (tight for rectification)
PROGRESSION_ORB = 1.0
SOLAR_ARC_ORB = 1.0
PROFECTION_TRANSIT_ORB = 2.0

NAIBOD_ARC_DEG_PER_YEAR = 59.0 / 60.0 + 8.33 / 3600.0  # ≈ 0.985647 degrees


# ---------------------------------------------------------------------------
# Helper sets
# ---------------------------------------------------------------------------

PLANET_IDS = [body_id for _swe_id, body_id, _name, _name_tr in PLANETS]
PLANET_SWE_BY_ID = {body_id: swe_id for swe_id, body_id, _n, _ntr in PLANETS}
PLANET_NAME_TR = {body_id: name_tr for _s, body_id, _n, name_tr in PLANETS}
CLASSICAL_PLANET_SET = {"sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn"}
MODERN_OUTER_SET = {"uranus", "neptune", "pluto"}


# ---------------------------------------------------------------------------
# Time / input helpers
# ---------------------------------------------------------------------------


def _parse_iso_date(value, field_name):
    if value is None:
        raise RectificationInputError(f"{field_name} boş olamaz")
    text = str(value).strip()
    if not text:
        raise RectificationInputError(f"{field_name} boş olamaz")
    formats = ("%Y-%m-%d", "%d.%m.%Y", "%d/%m/%Y")
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    raise RectificationInputError(f"{field_name} YYYY-MM-DD formatında olmalı: {value}")


def _parse_hhmmss(text, field_name, allow_empty=False):
    raw = str(text or "").strip()
    if not raw:
        if allow_empty:
            return None
        raise RectificationInputError(f"{field_name} boş olamaz")
    parts = raw.split(":")
    if len(parts) == 2:
        parts.append("0")
    if len(parts) != 3:
        raise RectificationInputError(f"{field_name} HH:MM[:SS] formatında olmalı")
    try:
        hour, minute, second = (int(part) for part in parts)
    except ValueError as exc:
        raise RectificationInputError(f"{field_name} sayısal olmalı") from exc
    if not (0 <= hour <= 23 and 0 <= minute <= 59 and 0 <= second <= 59):
        raise RectificationInputError(f"{field_name} geçerli aralıkta olmalı")
    return hour, minute, second


def _time_label_from_seconds(total_seconds):
    total_seconds = int(total_seconds) % (24 * 3600)
    hour, remainder = divmod(total_seconds, 3600)
    minute, second = divmod(remainder, 60)
    return f"{hour:02d}:{minute:02d}:{second:02d}"


def _hms_from_seconds(total_seconds):
    total_seconds = int(total_seconds) % (24 * 3600)
    hour, remainder = divmod(total_seconds, 3600)
    minute, second = divmod(remainder, 60)
    return hour, minute, second


def _resolve_timezone(birth_base, year, month, day, hour, minute, second):
    timezone_id = birth_base.get("timezone_id")
    if timezone_id:
        try:
            zone = ZoneInfo(str(timezone_id))
        except ZoneInfoNotFoundError as exc:
            raise RectificationInputError(
                f"Geçersiz birth_base.timezone_id: {timezone_id}"
            ) from exc
        naive = datetime(year, month, day, hour, minute, second)
        local_dt = naive.replace(tzinfo=zone)
        offset = local_dt.utcoffset()
        if offset is None:
            raise RectificationInputError("timezone_id için UTC farkı çözülemedi")
        return offset.total_seconds() / 3600.0, str(timezone_id)
    if "tz_offset" not in birth_base:
        raise RectificationInputError(
            "birth_base.timezone_id veya birth_base.tz_offset zorunludur"
        )
    try:
        tz_offset = float(birth_base["tz_offset"])
    except (TypeError, ValueError) as exc:
        raise RectificationInputError("birth_base.tz_offset sayı olmalı") from exc
    if not -14.0 <= tz_offset <= 14.0:
        raise RectificationInputError("birth_base.tz_offset -14 ile +14 arasında olmalı")
    return tz_offset, None


def _julian_day_ut(year, month, day, hour, minute, second, tz_offset):
    decimal_hour = hour + minute / 60.0 + second / 3600.0 - tz_offset
    return swe.julday(year, month, day, decimal_hour)


def _signed_delta(a, b):
    return ((a - b + 180.0) % 360.0) - 180.0


def _shortest_separation(a, b):
    return abs(_signed_delta(a, b))


def _house_number_from_cusps(longitude, cusps):
    longitude %= 360.0
    for index, cusp in enumerate(cusps):
        next_cusp = cusps[(index + 1) % 12]
        span = (next_cusp - cusp) % 360.0
        offset = (longitude - cusp) % 360.0
        if offset < span or math.isclose(offset, 0.0, abs_tol=1e-9):
            return index + 1
    return 1


def _sign_index_from_longitude(longitude):
    return int(longitude % 360.0 // 30.0)


# ---------------------------------------------------------------------------
# Event normalization
# ---------------------------------------------------------------------------


def _normalize_event_type(value):
    key = str(value or "").strip().lower()
    if not key:
        return ""
    if key in RECTIFICATION_EVENT_RULES:
        return key
    return RECTIFICATION_EVENT_TOPIC_ALIASES.get(key, key)


def _event_rule(event_type):
    rule_key = _normalize_event_type(event_type)
    rule = RECTIFICATION_EVENT_RULES.get(rule_key)
    return rule_key, rule


def _event_certainty_weight(certainty):
    key = str(certainty or "day_exact").strip().lower()
    return RECTIFICATION_EVENT_CERTAINTY_WEIGHTS.get(key, 0.5)


def _event_confidence_weight(confidence):
    key = str(confidence or "medium").strip().lower()
    return RECTIFICATION_EVENT_CONFIDENCE_WEIGHTS.get(key, 0.5)


def _weight_for_event(event):
    confidence = _event_confidence_weight(event.get("confidence"))
    certainty = _event_certainty_weight(event.get("certainty"))
    combined = round(max(0.1, confidence * certainty), 4)
    return {
        "confidence": event.get("confidence", "medium"),
        "certainty": event.get("certainty", "day_exact"),
        "confidence_weight": round(confidence, 4),
        "certainty_weight": round(certainty, 4),
        "combined_weight": combined,
    }


def _normalize_source_quality(value):
    key = str(value or "").strip().lower()
    aliases = {
        "official": "gold",
        "resmi": "gold",
        "hospital": "gold",
        "hastane": "gold",
        "birth_certificate": "gold",
        "nüfus": "gold",
        "nufus": "gold",
        "high": "silver",
        "yüksek": "silver",
        "yuksek": "silver",
        "family": "weak",
        "aile": "weak",
        "memory": "weak",
        "low": "weak",
        "düşük": "weak",
        "dusuk": "weak",
    }
    key = aliases.get(key, key)
    return key if key in {"gold", "silver", "weak", "unknown"} else "unknown"


def _normalize_bool(value, default=False):
    if value is None:
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "evet", "var", "documented"}


def _normalize_source_doc(doc, index):
    doc_type = str(
        doc.get("type") or doc.get("source_type") or f"source_{index + 1}"
    ).strip().lower()
    normalized = {
        "type": doc_type,
        "exists": _normalize_bool(doc.get("exists"), default=True),
        "quality": _normalize_source_quality(
            doc.get("quality") or doc.get("source_quality")
        ),
    }
    if doc.get("uncertainty_min") not in {None, ""}:
        try:
            normalized["uncertainty_min"] = int(doc["uncertainty_min"])
        except (TypeError, ValueError) as exc:
            raise RectificationInputError(
                f"source_docs[{index}].uncertainty_min tam sayı olmalı"
            ) from exc
    if doc.get("documented") is not None:
        normalized["documented"] = _normalize_bool(doc.get("documented"))
    if doc.get("note"):
        normalized["note"] = str(doc["note"]).strip()
    return normalized


def _normalize_source_docs(value):
    docs = value or []
    if isinstance(docs, dict):
        docs = [docs]
    if not isinstance(docs, list):
        raise RectificationInputError("source_docs liste olmalı")
    return [
        _normalize_source_doc(doc, index)
        for index, doc in enumerate(docs)
        if isinstance(doc, dict)
    ]


def _derive_source_quality(source_docs, time_confidence):
    existing_docs = [doc for doc in source_docs if doc.get("exists")]
    if any(doc.get("quality") == "gold" for doc in existing_docs):
        return "gold"
    if len(existing_docs) >= 2 or str(time_confidence or "").lower() in {
        "high",
        "rectified",
    }:
        return "silver"
    if existing_docs:
        return "weak"
    return "unknown"


def _normalize_event(event, index, default_timezone_id=None):
    if not isinstance(event, dict):
        raise RectificationInputError(f"events[{index}] nesne olmalı")

    date_value = event.get("date")
    if not date_value:
        for key in ("time_start_local", "start_local", "time_end_local", "end_local"):
            raw = str(event.get(key) or "").strip()
            if raw:
                date_value = raw[:10]
                break
    event_date = _parse_iso_date(date_value, f"events[{index}].date")

    raw_type = event.get("type") or event.get("event_type") or event.get("topic")
    event_type = _normalize_event_type(raw_type)
    if not event_type:
        raise RectificationInputError(f"events[{index}].type boş olamaz")

    event_time = str(event.get("time") or "").strip()
    if event_time:
        _parse_hhmmss(event_time, f"events[{index}].time")

    start_local = event.get("time_start_local") or event.get("start_local")
    end_local = event.get("time_end_local") or event.get("end_local")
    if not start_local:
        start_local = f"{event_date.isoformat()}T{event_time or '00:00'}"
    if not end_local:
        end_local = f"{event_date.isoformat()}T{event_time or '23:59'}"

    rule_key, rule = _event_rule(event_type)
    normalized = {
        "date": event_date.isoformat(),
        "type": event_type,
        "event_type": event_type,
        "rule_key": rule_key,
        "topic": rule["topic"] if rule else None,
        "supported": bool(rule),
        "label": event.get("label") or event.get("title") or event_type,
        "confidence": str(event.get("confidence") or "medium").strip().lower(),
        "certainty": str(
            event.get("certainty") or event.get("date_certainty") or "day_exact"
        ).strip().lower(),
        "time_start_local": str(start_local),
        "time_end_local": str(end_local),
        "timezone_id": event.get("timezone_id") or default_timezone_id,
        "documented": _normalize_bool(event.get("documented"), default=False),
        "source_type": str(event.get("source_type") or "unspecified").strip().lower(),
        "importance": str(event.get("importance") or "medium").strip().lower(),
    }
    if event_time:
        normalized["time"] = event_time
        # Otomatik certainty yükseltme: saat girilmiş ama certainty hâlâ day_exact ise time_known'a çek
        if normalized["certainty"] in {"day_exact", "exact_day", "date_exact"}:
            normalized["certainty"] = "time_known"
    if event.get("tz_offset") not in {None, ""}:
        try:
            normalized["tz_offset"] = float(event["tz_offset"])
        except (TypeError, ValueError) as exc:
            raise RectificationInputError(
                f"events[{index}].tz_offset sayı olmalı"
            ) from exc
    if event.get("note"):
        normalized["note"] = str(event["note"]).strip()
    return normalized


def _event_timezone_offset(event, fallback_tz_offset):
    if event.get("tz_offset") not in {None, ""}:
        try:
            return float(event["tz_offset"])
        except (TypeError, ValueError):
            pass
    timezone_id = event.get("timezone_id")
    if timezone_id:
        try:
            zone = ZoneInfo(str(timezone_id))
            event_date = datetime.fromisoformat(event["date"])
            offset = event_date.replace(tzinfo=zone).utcoffset()
            if offset is not None:
                return offset.total_seconds() / 3600.0
        except (ZoneInfoNotFoundError, ValueError):
            pass
    return float(fallback_tz_offset)


def _parse_event_jd(event, event_tz_offset):
    event_date = datetime.fromisoformat(event["date"])
    time_text = event.get("time") or "12:00:00"
    hour, minute, second = _parse_hhmmss(time_text, "event.time")
    return _julian_day_ut(
        event_date.year,
        event_date.month,
        event_date.day,
        hour,
        minute,
        second,
        event_tz_offset,
    )


# ---------------------------------------------------------------------------
# Search window / candidate generator
# ---------------------------------------------------------------------------


def _normalize_search_window(search_window):
    window = dict(search_window or {})
    start = _parse_hhmmss(window.get("start_time", "00:00:00"), "search_window.start_time")
    end = _parse_hhmmss(window.get("end_time", "23:59:00"), "search_window.end_time")
    step_minutes = int(window.get("step_minutes", 5) or 0)
    step_seconds = int(window.get("step_seconds", 0) or 0)
    if step_minutes <= 0 and step_seconds <= 0:
        raise RectificationInputError(
            "search_window.step_minutes veya step_seconds pozitif olmalı"
        )
    start_total = start[0] * 3600 + start[1] * 60 + start[2]
    end_total = end[0] * 3600 + end[1] * 60 + end[2]
    if end_total < start_total:
        raise RectificationInputError(
            "search_window.end_time start_time'dan önce olamaz"
        )
    return {
        "start_time": _time_label_from_seconds(start_total),
        "end_time": _time_label_from_seconds(end_total),
        "step_minutes": step_minutes,
        "step_seconds": step_seconds,
        "_start_seconds": start_total,
        "_end_seconds": end_total,
        "_step_seconds": step_minutes * 60 + step_seconds,
    }


def _candidate_seconds(search_window):
    start = search_window["_start_seconds"]
    end = search_window["_end_seconds"]
    step = search_window["_step_seconds"]
    candidates = []
    current = start
    while current <= end:
        candidates.append(current)
        current += step
        if len(candidates) > RECTIFICATION_MAX_CANDIDATES:
            raise RectificationInputError(
                f"Aday sayısı sınırı aşıldı (>{RECTIFICATION_MAX_CANDIDATES}). "
                "Arama penceresini daralt veya adım büyüklüğünü artır."
            )
    if not candidates:
        raise RectificationInputError("Arama penceresinden aday üretilemedi")
    return candidates


def _birth_dict_for_seconds(birth_base, candidate_second):
    hour, minute, second = _hms_from_seconds(candidate_second)
    return {
        **birth_base,
        "hour": hour,
        "minute": minute,
        "second": second,
    }


# ---------------------------------------------------------------------------
# Birth window normalization
# ---------------------------------------------------------------------------


def _normalize_birth_window(data, birth_base, search_window, source_docs):
    window = dict(data.get("birth_window") or {})
    timezone_id = window.get("timezone_id") or birth_base.get("timezone_id")
    birth_date = (
        f"{birth_base['year']:04d}-{birth_base['month']:02d}-{birth_base['day']:02d}"
    )
    start_local = str(
        window.get("start_local")
        or f"{birth_date}T{search_window['start_time']}"
    )
    end_local = str(
        window.get("end_local")
        or f"{birth_date}T{search_window['end_time']}"
    )
    source_quality = window.get("source_quality") or _derive_source_quality(
        source_docs,
        birth_base.get("time_confidence"),
    )
    return {
        "start_local": start_local,
        "end_local": end_local,
        "timezone_id": timezone_id,
        "source_quality": source_quality,
        "calendar": window.get("calendar") or "gregorian",
        "uncertainty_min": window.get("uncertainty_min"),
    }


# ---------------------------------------------------------------------------
# Core chart adapter (uses existing western_chart engine)
# ---------------------------------------------------------------------------


def _normalize_time_confidence_for_engine(value):
    """Map rectification-domain time_confidence values to western engine values."""
    raw = str(value or "low").strip().lower()
    mapped = {"rectified": "high", "known": "high"}.get(raw, raw)
    if mapped not in {"high", "medium", "low", "unknown"}:
        return "low"
    return mapped


def _build_chart_for_candidate(birth_base, candidate_second, options):
    hour, minute, second = _hms_from_seconds(candidate_second)
    payload = {
        "birth": {
            "year": birth_base["year"],
            "month": birth_base["month"],
            "day": birth_base["day"],
            "hour": hour,
            "minute": minute,
            "second": second,
            "lat": birth_base["lat"],
            "lon": birth_base["lon"],
            "place": birth_base.get("place"),
            "time_confidence": _normalize_time_confidence_for_engine(
                birth_base.get("time_confidence")
            ),
        },
        "options": {
            "zodiac": "tropical",
            "house_system": options.get("house_system", "placidus"),
            "node_type": options.get("node_type", "true"),
            "orb_profile": options.get("orb_profile", "modern_standard_v1"),
        },
    }
    if birth_base.get("timezone_id"):
        payload["birth"]["timezone_id"] = birth_base["timezone_id"]
    elif "tz_offset" in birth_base:
        payload["birth"]["tz_offset"] = birth_base["tz_offset"]
    try:
        return calculate_core_chart(payload)
    except (ChartInputError, ChartCalculationError) as exc:
        raise RectificationCalculationError(
            f"Aday için harita hesaplanamadı: {exc}",
            code="candidate_chart_failed",
        ) from exc


def _planet_index_by_id(chart):
    return {planet["id"]: planet for planet in chart["planets"]["items"]}


def _house_cusps(chart):
    return [item["longitude"] for item in chart["houses"]["items"]]


def _house_ruler_for_chart(chart, house_number, ruler_table):
    house_item = chart["houses"]["items"][house_number - 1]
    sign_index = house_item["sign_index"]
    return ruler_table[sign_index]


def _relevant_rulers(chart, rule, ruler_table):
    rulers = []
    for house_key in rule.get("houses", []):
        try:
            house_number = int(house_key)
        except (TypeError, ValueError):
            continue
        if 1 <= house_number <= 12:
            rulers.append(_house_ruler_for_chart(chart, house_number, ruler_table))
    return rulers


def _primary_relevant_rulers(chart, rule, ruler_table):
    rulers = []
    for house_key in rule.get("primary_rulers", []):
        try:
            house_number = int(house_key)
        except (TypeError, ValueError):
            continue
        if 1 <= house_number <= 12:
            rulers.append(_house_ruler_for_chart(chart, house_number, ruler_table))
    return rulers


def _expected_ascendant_from_birth_base(birth_base, options):
    raw_index = birth_base.get("expected_asc_sign_index")
    if raw_index not in {None, ""}:
        try:
            sign_index = int(raw_index)
            if 0 <= sign_index <= 11:
                return {
                    "status": "provided",
                    "source": "birth_base.expected_asc_sign_index",
                    "sign_index": sign_index,
                    "sign": SIGNS[sign_index][0],
                    "sign_tr": SIGNS[sign_index][1],
                }
        except (TypeError, ValueError):
            pass

    raw_text = birth_base.get("expected_asc") or birth_base.get("expected_asc_sign")
    if raw_text:
        sign_text = str(raw_text).strip().lower()
        for index, (en, tr) in enumerate(SIGNS):
            if sign_text in {en.lower(), tr.lower()}:
                return {
                    "status": "provided",
                    "source": "birth_base.expected_asc",
                    "sign_index": index,
                    "sign": en,
                    "sign_tr": tr,
                }

    explicit_confidence = str(birth_base.get("time_confidence") or "").strip().lower()
    if explicit_confidence not in {"high", "rectified", "known"}:
        return {
            "status": "not_provided",
            "reason": "birth_time_confidence_not_strong_enough_for_asc_anchor",
        }

    if "hour" not in birth_base or "minute" not in birth_base:
        return {"status": "not_provided", "reason": "birth_hour_minute_missing"}

    hour = int(birth_base["hour"])
    minute = int(birth_base["minute"])
    second = int(birth_base.get("second", 0))
    if hour == 0 and minute == 0 and second == 0:
        return {"status": "not_provided", "reason": "midnight_treated_as_unknown"}

    chart = _build_chart_for_candidate(
        birth_base,
        hour * 3600 + minute * 60 + second,
        options,
    )
    asc = chart["angles"]["ascendant"]
    return {
        "status": "derived",
        "source": "birth_base.hour_minute_second",
        "time": f"{hour:02d}:{minute:02d}:{second:02d}",
        "sign_index": asc["sign_index"],
        "sign": asc["sign"],
        "sign_tr": asc["sign_tr"],
    }


def _expected_midheaven_from_birth_base(birth_base):
    raw_index = birth_base.get("expected_mc_sign_index")
    if raw_index not in {None, ""}:
        try:
            sign_index = int(raw_index)
            if 0 <= sign_index <= 11:
                return {
                    "status": "provided",
                    "source": "birth_base.expected_mc_sign_index",
                    "sign_index": sign_index,
                    "sign": SIGNS[sign_index][0],
                    "sign_tr": SIGNS[sign_index][1],
                }
        except (TypeError, ValueError):
            pass
    raw_text = birth_base.get("expected_mc") or birth_base.get("expected_mc_sign")
    if raw_text:
        sign_text = str(raw_text).strip().lower()
        for index, (en, tr) in enumerate(SIGNS):
            if sign_text in {en.lower(), tr.lower()}:
                return {
                    "status": "provided",
                    "source": "birth_base.expected_mc",
                    "sign_index": index,
                    "sign": en,
                    "sign_tr": tr,
                }
    return {"status": "not_provided", "reason": "expected_mc_not_supplied"}


def _ascendant_anchor_for_candidate(candidate, expected_asc):
    if not expected_asc or expected_asc.get("status") not in {"provided", "derived"}:
        return {
            "status": "not_applied",
            "rankable": True,
            "score_adjustment": 0.0,
            "reason": expected_asc.get("reason") if expected_asc else "expected_asc_missing",
        }
    expected_index = expected_asc["sign_index"]
    actual_index = candidate["ascendant"]["sign_index"]
    matched = actual_index == expected_index
    return {
        "status": "matched" if matched else "mismatch",
        "rankable": matched,
        "score_adjustment": 0.0 if matched else ASC_ANCHOR_MISMATCH_PENALTY,
        "expected_sign_index": expected_index,
        "expected_sign": expected_asc["sign"],
        "expected_sign_tr": expected_asc["sign_tr"],
        "actual_sign_index": actual_index,
        "actual_sign": candidate["ascendant"]["sign"],
        "actual_sign_tr": candidate["ascendant"]["sign_tr"],
        "source": expected_asc.get("source"),
    }


def _midheaven_anchor_for_candidate(candidate, expected_mc):
    if not expected_mc or expected_mc.get("status") != "provided":
        return {
            "status": "not_applied",
            "rankable": True,
            "score_adjustment": 0.0,
            "reason": expected_mc.get("reason") if expected_mc else "expected_mc_missing",
        }
    expected_index = expected_mc["sign_index"]
    actual_index = candidate["midheaven"]["sign_index"]
    matched = actual_index == expected_index
    return {
        "status": "matched" if matched else "mismatch",
        "rankable": matched,
        "score_adjustment": 0.0 if matched else MC_ANCHOR_MISMATCH_PENALTY,
        "expected_sign_index": expected_index,
        "expected_sign": expected_mc["sign"],
        "expected_sign_tr": expected_mc["sign_tr"],
        "actual_sign_index": actual_index,
        "actual_sign": candidate["midheaven"]["sign"],
        "actual_sign_tr": candidate["midheaven"]["sign_tr"],
        "source": expected_mc.get("source"),
    }


# ---------------------------------------------------------------------------
# Astronomy helpers (transit, progression, solar arc, profection)
# ---------------------------------------------------------------------------


def _planet_longitudes_at_jd(jd_ut, planet_ids=None):
    targets = planet_ids if planet_ids is not None else PLANET_IDS
    flags = swe.FLG_SWIEPH | swe.FLG_SPEED
    result = {}
    for body_id in targets:
        swe_id = PLANET_SWE_BY_ID[body_id]
        try:
            values, _retflags = swe.calc_ut(jd_ut, swe_id, flags)
        except swe.Error as exc:
            if body_id == "chiron":
                continue
            raise RectificationCalculationError(
                f"{body_id} pozisyonu hesaplanamadı: {exc}",
                code="ephemeris_error",
            ) from exc
        longitude = values[0] % 360.0
        speed = values[3]
        result[body_id] = {
            "longitude": longitude,
            "sign_index": _sign_index_from_longitude(longitude),
            "speed_longitude": speed,
            "retrograde": speed < 0.0,
        }
    return result


def _calculate_transit_positions(event_jd):
    return _planet_longitudes_at_jd(event_jd)


def _calculate_secondary_progressions(birth_jd, event_jd):
    days_elapsed = event_jd - birth_jd
    years_elapsed = days_elapsed / 365.2422
    progressed_jd = birth_jd + years_elapsed
    return {
        "progressed_jd": progressed_jd,
        "years_elapsed": years_elapsed,
        "positions": _planet_longitudes_at_jd(progressed_jd),
    }


def _calculate_solar_arc(birth_jd, event_jd, natal_chart):
    natal_planets = _planet_index_by_id(natal_chart)
    natal_sun = natal_planets["sun"]["longitude"]
    natal_asc = natal_chart["angles"]["ascendant"]["longitude"]
    natal_mc = natal_chart["angles"]["midheaven"]["longitude"]
    progressed_sun = _planet_longitudes_at_jd(
        birth_jd + (event_jd - birth_jd) / 365.2422,
        planet_ids=["sun"],
    )["sun"]["longitude"]
    arc = _signed_delta(progressed_sun, natal_sun) % 360.0
    if arc > 180.0:
        arc -= 360.0
    arc = arc if arc >= 0 else arc + 360.0  # keep forward arc
    directed = {}
    for body_id, item in natal_planets.items():
        directed[body_id] = {
            "longitude": (item["longitude"] + arc) % 360.0,
            "natal_longitude": item["longitude"],
        }
    directed["ascendant"] = {
        "longitude": (natal_asc + arc) % 360.0,
        "natal_longitude": natal_asc,
    }
    directed["midheaven"] = {
        "longitude": (natal_mc + arc) % 360.0,
        "natal_longitude": natal_mc,
    }
    return {
        "arc_degrees": arc,
        "directed": directed,
    }


def _calculate_profection(birth_jd, event_jd, natal_chart):
    age_years = (event_jd - birth_jd) / 365.2422
    age_int = int(age_years)
    profected_house = (age_int % 12) + 1
    house_item = natal_chart["houses"]["items"][profected_house - 1]
    sign_index = house_item["sign_index"]
    classical_lord = CLASSICAL_RULERS[sign_index]
    modern_lord = MODERN_RULERS[sign_index]
    return {
        "age_years": age_years,
        "age_integer": age_int,
        "profected_house": profected_house,
        "profected_sign_index": sign_index,
        "profected_sign": house_item["sign"],
        "profected_sign_tr": house_item["sign_tr"],
        "year_lord_classical": classical_lord,
        "year_lord_modern": modern_lord,
    }


def _aspect_within_orb(longitude_a, longitude_b, orb, aspect_set=ALL_ASPECTS):
    separation = _shortest_separation(longitude_a, longitude_b)
    best = None
    for name, angle in aspect_set.items():
        deviation = abs(separation - angle)
        if deviation <= orb and (best is None or deviation < best["deviation"]):
            best = {
                "type": name,
                "exact_angle": angle,
                "actual_angle": separation,
                "deviation": deviation,
                "hard": name in HARD_ASPECTS,
            }
    return best


# ---------------------------------------------------------------------------
# Scoring layers
# ---------------------------------------------------------------------------


def _score_natal_layer(chart, rule):
    score = 0.0
    factors = []
    planets_by_id = _planet_index_by_id(chart)
    relevant_houses = {int(h) for h in rule.get("houses", []) if str(h).isdigit()}
    primary_rulers_classical = _primary_relevant_rulers(chart, rule, CLASSICAL_RULERS)
    primary_rulers_modern = _primary_relevant_rulers(chart, rule, MODERN_RULERS)
    secondary_rulers_classical = _relevant_rulers(chart, rule, CLASSICAL_RULERS)
    secondary_rulers_modern = _relevant_rulers(chart, rule, MODERN_RULERS)

    karakas_classical = set(rule.get("karakas_classical", []))
    karakas_modern = set(rule.get("karakas_modern", []))

    # Karakas placed in relevant houses
    for karaka_set, track in (
        (karakas_classical, "classical"),
        (karakas_modern, "modern"),
    ):
        for planet_id in karaka_set:
            planet = planets_by_id.get(planet_id)
            if planet and planet.get("house") in relevant_houses:
                score += NATAL_KARAKA_IN_HOUSE_WEIGHT
                factors.append({
                    "type": "natal_karaka_in_relevant_house",
                    "track": track,
                    "planet": planet_id,
                    "house": planet["house"],
                    "weight": NATAL_KARAKA_IN_HOUSE_WEIGHT,
                })

    # Primary ruler placed in any relevant house
    for ruler_set, track in (
        (primary_rulers_classical, "classical"),
        (primary_rulers_modern, "modern"),
    ):
        for ruler_id in ruler_set:
            planet = planets_by_id.get(ruler_id)
            if planet and planet.get("house") in relevant_houses:
                score += NATAL_RULER_IN_RELEVANT_HOUSE_WEIGHT
                factors.append({
                    "type": "primary_ruler_in_relevant_house",
                    "track": track,
                    "ruler": ruler_id,
                    "house": planet["house"],
                    "weight": NATAL_RULER_IN_RELEVANT_HOUSE_WEIGHT,
                })

    # Secondary ruler placed in any relevant house
    for ruler_set, track in (
        (secondary_rulers_classical, "classical"),
        (secondary_rulers_modern, "modern"),
    ):
        for ruler_id in ruler_set:
            planet = planets_by_id.get(ruler_id)
            if planet and planet.get("house") in relevant_houses:
                score += NATAL_SECONDARY_RULER_WEIGHT
                factors.append({
                    "type": "secondary_ruler_in_relevant_house",
                    "track": track,
                    "ruler": ruler_id,
                    "house": planet["house"],
                    "weight": NATAL_SECONDARY_RULER_WEIGHT,
                })

    return {
        "score": round(score, 2),
        "factors": factors,
        "relevant_houses": sorted(relevant_houses),
        "primary_rulers_classical": primary_rulers_classical,
        "primary_rulers_modern": primary_rulers_modern,
        "karakas_classical": sorted(karakas_classical),
        "karakas_modern": sorted(karakas_modern),
    }


def _score_transit_layer(chart, rule, event_jd):
    score = 0.0
    factors = []
    relevant_houses = {int(h) for h in rule.get("houses", []) if str(h).isdigit()}
    karakas = set(rule.get("karakas_modern", []))
    primary_rulers_modern = set(_primary_relevant_rulers(chart, rule, MODERN_RULERS))
    primary_rulers_classical = set(_primary_relevant_rulers(chart, rule, CLASSICAL_RULERS))
    all_rulers = primary_rulers_modern | primary_rulers_classical
    cusps = _house_cusps(chart)
    natal_planets = _planet_index_by_id(chart)

    transit_positions = _calculate_transit_positions(event_jd)

    for body_id, info in transit_positions.items():
        if body_id == "moon":
            continue  # Moon moves too fast for rectification orb here
        transit_house = _house_number_from_cusps(info["longitude"], cusps)
        if body_id in karakas and transit_house in relevant_houses:
            score += TRANSIT_PLANET_IN_RELEVANT_HOUSE_WEIGHT
            factors.append({
                "type": "transit_karaka_in_relevant_house",
                "planet": body_id,
                "house": transit_house,
                "weight": TRANSIT_PLANET_IN_RELEVANT_HOUSE_WEIGHT,
            })
        if body_id in all_rulers and transit_house in relevant_houses:
            score += TRANSIT_PLANET_IN_RELEVANT_HOUSE_WEIGHT
            factors.append({
                "type": "transit_relevant_ruler_in_relevant_house",
                "planet": body_id,
                "house": transit_house,
                "weight": TRANSIT_PLANET_IN_RELEVANT_HOUSE_WEIGHT,
            })

        for natal_id, natal_planet in natal_planets.items():
            if natal_id == body_id:
                continue
            aspect = _aspect_within_orb(
                info["longitude"], natal_planet["longitude"], TRANSIT_ORB_NATAL
            )
            if not aspect:
                continue
            base = (
                TRANSIT_HARD_ASPECT_TO_NATAL_WEIGHT
                if aspect["hard"]
                else TRANSIT_SOFT_ASPECT_TO_NATAL_WEIGHT
            )
            relevance_bonus = 0.0
            if (
                body_id in all_rulers
                or natal_id in all_rulers
                or body_id in karakas
                or natal_id in karakas
            ):
                relevance_bonus = TRANSIT_TO_RELEVANT_RULER_BONUS
            total = base + relevance_bonus
            score += total
            factors.append({
                "type": "transit_to_natal_aspect",
                "transit_planet": body_id,
                "natal_planet": natal_id,
                "aspect": aspect["type"],
                "deviation": round(aspect["deviation"], 4),
                "weight": round(total, 2),
            })

    return {
        "score": round(score, 2),
        "factors": factors,
        "transit_planet_count": len(transit_positions),
    }


def _score_progression_layer(chart, rule, event_jd, birth_jd):
    score = 0.0
    factors = []
    progressions = _calculate_secondary_progressions(birth_jd, event_jd)
    natal_planets = _planet_index_by_id(chart)
    natal_asc = chart["angles"]["ascendant"]["longitude"]
    natal_mc = chart["angles"]["midheaven"]["longitude"]
    karakas = set(rule.get("karakas_modern", []))
    relevant_rulers = set(_primary_relevant_rulers(chart, rule, MODERN_RULERS)) | set(
        _primary_relevant_rulers(chart, rule, CLASSICAL_RULERS)
    )
    relevant_set = karakas | relevant_rulers

    for body_id, info in progressions["positions"].items():
        prog_long = info["longitude"]
        for angle_name, natal_angle_long in (
            ("ascendant", natal_asc),
            ("midheaven", natal_mc),
        ):
            aspect = _aspect_within_orb(prog_long, natal_angle_long, PROGRESSION_ORB)
            if aspect and (body_id in relevant_set or aspect["type"] == "conjunction"):
                weight = PROGRESSION_ANGLE_HIT_WEIGHT
                if body_id == "moon":
                    weight = PROGRESSION_MOON_HIT_WEIGHT
                score += weight
                factors.append({
                    "type": "progressed_planet_to_natal_angle",
                    "progressed_planet": body_id,
                    "natal_angle": angle_name,
                    "aspect": aspect["type"],
                    "deviation": round(aspect["deviation"], 4),
                    "weight": weight,
                })
        for natal_id, natal_planet in natal_planets.items():
            if natal_id == body_id and not (body_id == "moon"):
                continue
            aspect = _aspect_within_orb(
                prog_long, natal_planet["longitude"], PROGRESSION_ORB
            )
            if aspect and (body_id in relevant_set or natal_id in relevant_set):
                weight = PROGRESSION_PLANET_ASPECT_WEIGHT
                if body_id == "moon":
                    weight = PROGRESSION_MOON_HIT_WEIGHT
                score += weight
                factors.append({
                    "type": "progressed_to_natal_aspect",
                    "progressed_planet": body_id,
                    "natal_planet": natal_id,
                    "aspect": aspect["type"],
                    "deviation": round(aspect["deviation"], 4),
                    "weight": weight,
                })

    return {
        "score": round(score, 2),
        "factors": factors,
        "years_elapsed": round(progressions["years_elapsed"], 4),
    }


def _score_solar_arc_layer(chart, rule, event_jd, birth_jd):
    score = 0.0
    factors = []
    solar_arc = _calculate_solar_arc(birth_jd, event_jd, chart)
    natal_planets = _planet_index_by_id(chart)
    natal_asc = chart["angles"]["ascendant"]["longitude"]
    natal_mc = chart["angles"]["midheaven"]["longitude"]
    karakas = set(rule.get("karakas_modern", []))
    relevant_rulers = set(_primary_relevant_rulers(chart, rule, MODERN_RULERS)) | set(
        _primary_relevant_rulers(chart, rule, CLASSICAL_RULERS)
    )
    relevant_set = karakas | relevant_rulers

    for body_id, info in solar_arc["directed"].items():
        if body_id in {"ascendant", "midheaven"}:
            continue
        directed_long = info["longitude"]
        for angle_name, natal_angle_long in (
            ("ascendant", natal_asc),
            ("midheaven", natal_mc),
        ):
            aspect = _aspect_within_orb(directed_long, natal_angle_long, SOLAR_ARC_ORB)
            if aspect and (body_id in relevant_set or aspect["type"] == "conjunction"):
                score += SOLAR_ARC_ANGLE_HIT_WEIGHT
                factors.append({
                    "type": "solar_arc_planet_to_natal_angle",
                    "directed_planet": body_id,
                    "natal_angle": angle_name,
                    "aspect": aspect["type"],
                    "deviation": round(aspect["deviation"], 4),
                    "weight": SOLAR_ARC_ANGLE_HIT_WEIGHT,
                })
        for natal_id, natal_planet in natal_planets.items():
            if natal_id == body_id:
                continue
            aspect = _aspect_within_orb(
                directed_long, natal_planet["longitude"], SOLAR_ARC_ORB
            )
            if aspect and (body_id in relevant_set or natal_id in relevant_set):
                score += SOLAR_ARC_PLANET_ASPECT_WEIGHT
                factors.append({
                    "type": "solar_arc_to_natal_aspect",
                    "directed_planet": body_id,
                    "natal_planet": natal_id,
                    "aspect": aspect["type"],
                    "deviation": round(aspect["deviation"], 4),
                    "weight": SOLAR_ARC_PLANET_ASPECT_WEIGHT,
                })

    # Solar arc directed angles to natal planets
    for angle_name in ("ascendant", "midheaven"):
        directed_long = solar_arc["directed"][angle_name]["longitude"]
        for natal_id, natal_planet in natal_planets.items():
            aspect = _aspect_within_orb(
                directed_long, natal_planet["longitude"], SOLAR_ARC_ORB
            )
            if aspect and natal_id in relevant_set:
                score += SOLAR_ARC_ANGLE_HIT_WEIGHT
                factors.append({
                    "type": "solar_arc_angle_to_natal_planet",
                    "directed_angle": angle_name,
                    "natal_planet": natal_id,
                    "aspect": aspect["type"],
                    "deviation": round(aspect["deviation"], 4),
                    "weight": SOLAR_ARC_ANGLE_HIT_WEIGHT,
                })

    return {
        "score": round(score, 2),
        "factors": factors,
        "arc_degrees": round(solar_arc["arc_degrees"], 6),
    }


def _moon_sun_angle(jd):
    """Moon - Sun geosentrik açısı 0-360 aralığında."""
    positions = _planet_longitudes_at_jd(jd, ["sun", "moon"])
    return (positions["moon"]["longitude"] - positions["sun"]["longitude"]) % 360.0


def _bisect_syzygy(jd_low, jd_high, mode):
    """Yeni ay (mode=new_moon) veya dolunay (mode=full_moon) noktasını bisection ile sağla.

    jd_low < jd_high; jd_low syzygy'den önce, jd_high sonra.
    """
    for _ in range(SYZYGY_BISECTION_ITERATIONS):
        jd_mid = (jd_low + jd_high) / 2.0
        angle = _moon_sun_angle(jd_mid)
        if mode == "new_moon":
            # angle > 180 ise henuz yeni ay olmamis (360'a yakin), < 180 ise gecmis
            signed = angle - 360.0 if angle > 180.0 else angle
            if signed < 0:
                jd_low = jd_mid
            else:
                jd_high = jd_mid
        else:  # full_moon
            if angle < 180.0:
                jd_low = jd_mid
            else:
                jd_high = jd_mid
    return (jd_low + jd_high) / 2.0


def _find_pre_natal_syzygy(birth_jd):
    """Doğumdan önceki son Yeni Ay veya Dolunay'ı döndür.

    Returns: dict {jd, type, longitude, sign_index, sign, sign_tr, days_before_birth, ...} veya None.
    """
    n_steps = int(SYZYGY_LOOKBACK_DAYS / SYZYGY_COARSE_STEP_DAYS)
    # samples[0] = birth_jd, samples[-1] = en eski
    samples = []
    for i in range(n_steps + 1):
        jd = birth_jd - i * SYZYGY_COARSE_STEP_DAYS
        samples.append((jd, _moon_sun_angle(jd)))

    new_moon_jd = None
    full_moon_jd = None

    # samples[i] = daha yeni, samples[i+1] = daha eski (geriye gidiyor)
    # Forward time: i+1 -> i. Acidan i+1'deki acidan i'deki aciya gec.
    for i in range(len(samples) - 1):
        jd_later, a_later = samples[i]
        jd_earlier, a_earlier = samples[i + 1]

        # Yeni ay gecisi: forward zamanda 358 -> 2 (mod 360 sarma)
        if a_earlier > 350.0 and a_later < 10.0:
            if new_moon_jd is None:
                new_moon_jd = _bisect_syzygy(jd_earlier, jd_later, "new_moon")

        # Dolunay gecisi: forward zamanda 178 -> 182
        if a_earlier < 180.0 < a_later:
            if full_moon_jd is None:
                full_moon_jd = _bisect_syzygy(jd_earlier, jd_later, "full_moon")

        if new_moon_jd is not None and full_moon_jd is not None:
            break

    options = []
    if new_moon_jd is not None:
        options.append((new_moon_jd, "new_moon"))
    if full_moon_jd is not None:
        options.append((full_moon_jd, "full_moon"))
    if not options:
        return None

    # Doğuma en yakın olanı seç (en büyük jd = en yakın)
    syzygy_jd, syzygy_type = max(options, key=lambda item: item[0])

    positions = _planet_longitudes_at_jd(syzygy_jd, ["sun", "moon"])
    sun_long = positions["sun"]["longitude"]
    moon_long = positions["moon"]["longitude"]

    # Konjuksiyonda iki long ~aynı; oppozisyonda Ay'ın derecesini rapor et (klasik anchor)
    longitude = sun_long if syzygy_type == "new_moon" else moon_long
    sign_index = _sign_index_from_longitude(longitude)

    return {
        "jd": round(syzygy_jd, 6),
        "type": syzygy_type,
        "longitude": round(longitude, 4),
        "sign_index": sign_index,
        "sign": SIGNS[sign_index][0],
        "sign_tr": SIGNS[sign_index][1],
        "days_before_birth": round(birth_jd - syzygy_jd, 4),
        "sun_longitude": round(sun_long, 4),
        "moon_longitude": round(moon_long, 4),
    }


def _score_pre_natal_syzygy_layer(chart, syzygy):
    """Pre-natal syzygy derecesi ile adayın ASC/MC arası aspect skorlaması.

    Olay bağımsız, aday bağımlı (ASC/MC her dakikada değişir).
    """
    if not syzygy:
        return {"score": 0.0, "factors": [], "aspects": [], "available": False}

    score = 0.0
    factors = []
    aspects = []

    for angle_name, angle_long in (
        ("ascendant", chart["angles"]["ascendant"]["longitude"]),
        ("midheaven", chart["angles"]["midheaven"]["longitude"]),
    ):
        aspect = _aspect_within_orb(syzygy["longitude"], angle_long, SYZYGY_ORB_WIDE)
        if not aspect:
            continue
        aspect_type = aspect["type"]
        dev = aspect["deviation"]

        # Yumusak aspectler (trine/sextile) sadece tight orb'da
        if aspect_type in ("trine", "sextile") and dev > SYZYGY_ORB_TIGHT:
            continue

        base = SYZYGY_ASPECT_BONUS.get(aspect_type, 0.0)
        bonus = base if dev <= SYZYGY_ORB_TIGHT else base * 0.5
        bonus = round(bonus, 2)

        score += bonus
        factors.append({
            "type": "pre_natal_syzygy_to_angle",
            "angle": angle_name,
            "syzygy_type": syzygy["type"],
            "aspect": aspect_type,
            "deviation": round(dev, 4),
            "weight": bonus,
        })
        aspects.append({
            "angle": angle_name,
            "aspect": aspect_type,
            "deviation": round(dev, 4),
            "orb_tier": "tight" if dev <= SYZYGY_ORB_TIGHT else "wide",
            "bonus": bonus,
        })

    return {
        "score": round(score, 2),
        "factors": factors,
        "aspects": aspects,
        "available": True,
    }


def _score_parans_layer(chart):
    """Doğum anına yakın gerçek paranları puanla (Brady Visual Astrology).

    Olay bağımsız, aday bağımlı: adayin kendi doğum saniyesinde hangi
    gezegen/yıldız çiftleri açısal olarak (rise/set/culminate/anti-culminate)
    eşzamanlı geçiyor. Doğuma offset küçükse (birkaç dakika) bu, doğum
    saatinin astronomik olarak "işaretli" bir an olduğunu destekler.

    calculate_parans mevcut chart'ı yeniden kullanır (chart param); sadece
    ek rise_trans/fixstar hesapları yapılır, harita yeniden hesaplanmaz.
    """
    try:
        parans_data = calculate_parans({}, chart=chart)
    except (ParansInputError, ParansCalculationError):
        return {
            "score": 0.0,
            "factors": [],
            "tight_parans": [],
            "wide_parans": [],
            "nearest_to_birth": None,
            "available": False,
        }

    all_parans = parans_data.get("parans") or []
    tight = [
        p for p in all_parans
        if abs(p.get("offset_from_birth_minutes", 999.0)) <= PARAN_OFFSET_TIGHT_MINUTES
    ]
    wide = [
        p for p in all_parans
        if PARAN_OFFSET_TIGHT_MINUTES
        < abs(p.get("offset_from_birth_minutes", 999.0))
        <= PARAN_OFFSET_WIDE_MINUTES
    ]
    tight.sort(key=lambda p: abs(p.get("offset_from_birth_minutes", 0.0)))
    wide.sort(key=lambda p: abs(p.get("offset_from_birth_minutes", 0.0)))

    score = 0.0
    factors = []

    if tight:
        extra_count = min(len(tight) - 1, PARAN_MAX_EXTRA_COUNT)
        score += PARAN_TIGHT_BONUS + extra_count * PARAN_EXTRA_PER_ADDITIONAL_TIGHT
        for index, paran in enumerate(tight):
            weight = PARAN_TIGHT_BONUS if index == 0 else PARAN_EXTRA_PER_ADDITIONAL_TIGHT
            factors.append({
                "type": "paran_tight_to_birth",
                "body_a": paran.get("body_a"),
                "body_a_tr": paran.get("body_a_tr"),
                "body_a_angle": paran.get("body_a_angle"),
                "body_b": paran.get("body_b"),
                "body_b_tr": paran.get("body_b_tr"),
                "body_b_angle": paran.get("body_b_angle"),
                "offset_from_birth_minutes": paran.get("offset_from_birth_minutes"),
                "pair_kind": paran.get("pair_kind"),
                "weight": weight,
            })
    elif wide:
        score += PARAN_WIDE_BONUS
        paran = wide[0]
        factors.append({
            "type": "paran_wide_to_birth",
            "body_a": paran.get("body_a"),
            "body_a_tr": paran.get("body_a_tr"),
            "body_a_angle": paran.get("body_a_angle"),
            "body_b": paran.get("body_b"),
            "body_b_tr": paran.get("body_b_tr"),
            "body_b_angle": paran.get("body_b_angle"),
            "offset_from_birth_minutes": paran.get("offset_from_birth_minutes"),
            "pair_kind": paran.get("pair_kind"),
            "weight": PARAN_WIDE_BONUS,
        })

    return {
        "score": round(score, 2),
        "factors": factors,
        "tight_parans": tight,
        "wide_parans": wide,
        "nearest_to_birth": parans_data.get("nearest_to_birth"),
        "available": True,
    }


def _score_midpoints_layer(chart):
    """ASC/MC'nin başka gezegen çiftlerinin midpoint'ine düşmesini puanla.

    Olay bağımsız, aday bağımlı: ASC/MC her adayda değişir. Klasik
    Cosmobiology rektifikasyon tekniği: doğru saatte ASC veya MC, iki başka
    noktanın midpoint'inde (direct veya opposite, orb ≤1°) olmalı.

    calculate_midpoints mevcut chart'ı yeniden kullanır (chart param); ek
    ephemeris çağrısı yapılmaz, sadece mevcut natal pozisyonlar üzerinde
    hesap yapılır.
    """
    try:
        midpoints_data = calculate_midpoints(
            {"midpoints": {"occupied_orb": MIDPOINT_RECTIFICATION_ORB}},
            chart=chart,
        )
    except (MidpointsInputError, MidpointsCalculationError):
        return {
            "score": 0.0,
            "factors": [],
            "hits": [],
            "hit_count": 0,
            "top_hit": None,
            "available": False,
        }

    hits = []
    for midpoint in midpoints_data.get("midpoints") or []:
        for occ in midpoint.get("occupied_by") or []:
            if occ.get("point") not in {"ascendant", "midheaven"}:
                continue
            hits.append({
                "angle": occ["point"],
                "pair": midpoint.get("pair"),
                "from": midpoint.get("from"),
                "from_tr": midpoint.get("from_tr"),
                "to": midpoint.get("to"),
                "to_tr": midpoint.get("to_tr"),
                "side": occ.get("side"),
                "orb": occ.get("orb"),
            })

    hits.sort(key=lambda h: h.get("orb", 0.0))

    score = 0.0
    factors = []
    for hit in hits[:MIDPOINT_MAX_HITS_COUNTED]:
        bonus = MIDPOINT_ANGLE_HIT_BASE_BONUS
        if hit.get("from") in {"sun", "moon"} or hit.get("to") in {"sun", "moon"}:
            bonus += MIDPOINT_LUMINARY_BONUS
        bonus = round(bonus, 2)
        score += bonus
        factors.append({
            "type": "midpoint_angle_hit",
            "angle": hit["angle"],
            "pair": hit["pair"],
            "from": hit["from"],
            "from_tr": hit["from_tr"],
            "to": hit["to"],
            "to_tr": hit["to_tr"],
            "side": hit["side"],
            "orb": hit["orb"],
            "weight": bonus,
        })

    return {
        "score": round(score, 2),
        "factors": factors,
        "hits": hits,
        "hit_count": len(hits),
        "top_hit": hits[0] if hits else None,
        "available": True,
    }


def _compute_primary_directions_for_candidate(chart, event_inputs, birth_jd):
    """Aday için primary directions hesapla; olay yaşlarına uygun window.

    Returns: active_directions list veya boş liste.
    """
    if not event_inputs:
        return []

    # Olay yaşlarını hesapla (jd farkları / tropical yıl)
    event_ages = [
        (item["jd"] - birth_jd) / 365.2422
        for item in event_inputs
    ]
    min_age = min(event_ages)
    max_age = max(event_ages)
    center_age = (min_age + max_age) / 2.0
    half_window = max((max_age - min_age) / 2.0 + PD_WINDOW_BUFFER_YEARS, 1.0)

    # Target date olarak center_age'ı doğumdan ileri saymak yerine,
    # birth_jd + center_age * 365.25 gününü gregorian tarihe döüştür.
    # Daha temizi: chart["birth"]["utc_datetime"] + center_age yıl
    from datetime import datetime as _dt, timedelta as _td, timezone as _tz
    birth_utc = _dt.fromisoformat(
        chart["birth"]["utc_datetime"].replace("Z", "+00:00")
    )
    target_dt = birth_utc + _td(days=center_age * 365.2422)
    target_date_str = target_dt.date().isoformat()

    pd_payload = {
        "primary_directions": {
            "target_date": target_date_str,
            "key": PD_DEFAULT_KEY,
            "window_years": half_window,
        }
    }
    try:
        pd_result = calculate_primary_directions(pd_payload, chart=chart)
    except (PrimaryDirectionsInputError, PrimaryDirectionsCalculationError):
        return []
    return pd_result.get("active_directions") or []


def _score_primary_directions_layer(chart, rule, event, pd_directions, birth_jd):
    """Olayın yaşına denk gelen PD yönelimlerini puanla.

    event_age ± PD_EVENT_MATCH_TOLERANCE_YEARS içindeki direction'lar alınır.
    Her direction promissor/significator relevance + house relevance bonus alır.
    """
    if not pd_directions:
        return {"score": 0.0, "factors": [], "matched": []}

    # event_age
    from datetime import datetime as _dt
    event_date = _dt.fromisoformat(event["date"])
    # Olayın jd'si event_inputs'tan gelmeyebilir, _event_timezone_offset alıp hesapla
    # ama olayın yaşı sadece tarih-bazlı için yeterli (saat hassasiyeti PD'de zaten dakikalik)
    # Bu kontekste birth_jd candıdate'in birth_jd'sı. event_age = (event_jd - birth_jd) / year
    # Daha basit: chart birth_utc'den event_date'e kadar yıl farkı
    birth_utc = _dt.fromisoformat(
        chart["birth"]["utc_datetime"].replace("Z", "+00:00")
    )
    # event_date'e 12:00 UTC ekle
    from datetime import time as _time, timezone as _tz
    event_dt = _dt.combine(event_date, _time(12, 0, tzinfo=_tz.utc))
    event_age = (event_dt - birth_utc).total_seconds() / (365.2422 * 86400.0)

    relevant_houses = {int(h) for h in rule.get("houses", []) if str(h).isdigit()}
    karakas = set(rule.get("karakas_modern", [])) | set(rule.get("karakas_classical", []))
    primary_rulers = set()
    for ruler_table in (CLASSICAL_RULERS, MODERN_RULERS):
        for house_key in rule.get("primary_rulers", []):
            try:
                house_num = int(house_key)
                if 1 <= house_num <= 12:
                    primary_rulers.add(_house_ruler_for_chart(chart, house_num, ruler_table))
            except (TypeError, ValueError):
                continue
    relevant_planets = karakas | primary_rulers

    natal_planets = _planet_index_by_id(chart)

    score = 0.0
    factors = []
    matched = []

    for direction in pd_directions:
        dir_age = direction.get("event_age")
        if dir_age is None:
            continue
        if abs(dir_age - event_age) > PD_EVENT_MATCH_TOLERANCE_YEARS:
            continue

        aspect = direction.get("aspect")
        if aspect in PD_HARD_ASPECTS:
            base = PD_HARD_ASPECT_BASE
        elif aspect in PD_SOFT_ASPECTS:
            base = PD_SOFT_ASPECT_BASE
        else:
            continue

        bonus = 0.0
        promissor = direction.get("promissor")
        significator = direction.get("significator")

        if promissor in relevant_planets:
            bonus += PD_PROMISSOR_RELEVANCE_BONUS
        if significator in relevant_planets:
            bonus += PD_SIGNIFICATOR_RELEVANCE_BONUS

        # Natal house relevance
        promissor_natal = natal_planets.get(promissor)
        significator_natal = natal_planets.get(significator)
        if promissor_natal and promissor_natal.get("house") in relevant_houses:
            bonus += PD_HOUSE_RELEVANCE_BONUS
        if significator_natal and significator_natal.get("house") in relevant_houses:
            bonus += PD_HOUSE_RELEVANCE_BONUS

        # Significator zaten ASC/MC olabilir, onun natal evi yok
        if direction.get("significator_natal_house") in relevant_houses:
            bonus += PD_HOUSE_RELEVANCE_BONUS
        if direction.get("promissor_natal_house") in relevant_houses:
            bonus += PD_HOUSE_RELEVANCE_BONUS

        total = base + bonus
        score += total
        factor = {
            "type": "primary_direction_match",
            "promissor": promissor,
            "significator": significator,
            "aspect": aspect,
            "direction_age": round(dir_age, 4),
            "event_age": round(event_age, 4),
            "age_delta": round(dir_age - event_age, 4),
            "estimated_date": direction.get("estimated_date_utc"),
            "weight": round(total, 2),
        }
        factors.append(factor)
        matched.append(factor)

    return {
        "score": round(score, 2),
        "factors": factors,
        "matched": matched,
    }


def _compute_solar_return_for_event(birth_base, chart, event, sr_cache):
    """Olay yılına ait Solar Return'u hesapla (cache ile).

    Olayın düştüğü SR yılı: doğum gününden ÖNCE ise event_year - 1, sonra ise event_year.
    Returns: sr_data dict veya None.
    """
    from datetime import datetime as _dt
    event_date = _dt.fromisoformat(event["date"]).date()
    birth_month = int(birth_base["month"])
    birth_day = int(birth_base["day"])

    # Olayın doğum gününe göre hangi SR yılına düştüğünü belirle
    try:
        birthday_this_year = event_date.replace(month=birth_month, day=birth_day)
    except ValueError:
        # 29 Şubat
        birthday_this_year = event_date.replace(month=birth_month, day=28)
    if event_date >= birthday_this_year:
        sr_year = event_date.year
    else:
        sr_year = event_date.year - 1

    if sr_year in sr_cache:
        return sr_cache[sr_year]

    timezone_id = birth_base.get("timezone_id")
    if not timezone_id:
        sr_cache[sr_year] = None
        return None

    sr_payload = {
        "birth": {
            "year": int(birth_base["year"]),
            "month": int(birth_base["month"]),
            "day": int(birth_base["day"]),
            "hour": chart["birth"]["hour"] if isinstance(chart["birth"].get("hour"), int) else int(chart["birth"]["local_datetime"][11:13]),
            "minute": chart["birth"]["minute"] if isinstance(chart["birth"].get("minute"), int) else int(chart["birth"]["local_datetime"][14:16]),
            "second": chart["birth"].get("second", 0),
            "lat": float(birth_base["lat"]),
            "lon": float(birth_base["lon"]),
            "timezone_id": timezone_id,
            "place": birth_base.get("place"),
            "time_confidence": "low",
        },
        "options": {
            "zodiac": "tropical",
            "house_system": chart["meta"]["house_system"],
            "node_type": chart["meta"]["node_type"],
        },
        "return_year": sr_year,
    }
    try:
        sr_data = calculate_solar_return(sr_payload, natal_chart=chart)
        sr_cache[sr_year] = sr_data
        return sr_data
    except (SolarReturnError, Exception):
        sr_cache[sr_year] = None
        return None


def _score_solar_return_layer(chart, rule, event, sr_data):
    """SR ASC/MC natal evi + tema gezegenleri + SR-natal aspect'leri ile skor."""
    if not sr_data:
        return {"score": 0.0, "factors": [], "sr_year": None}

    score = 0.0
    factors = []
    relevant_houses = {int(h) for h in rule.get("houses", []) if str(h).isdigit()}
    karakas = set(rule.get("karakas_modern", [])) | set(rule.get("karakas_classical", []))
    primary_rulers = set()
    for ruler_table in (CLASSICAL_RULERS, MODERN_RULERS):
        for house_key in rule.get("primary_rulers", []):
            try:
                house_num = int(house_key)
                if 1 <= house_num <= 12:
                    primary_rulers.add(_house_ruler_for_chart(chart, house_num, ruler_table))
            except (TypeError, ValueError):
                continue
    relevant_planets = karakas | primary_rulers

    # SR ASC natal evi olayın relevant_houses'ında mı?
    sr_asc_natal_house = sr_data.get("sr_asc_in_natal_house")
    if sr_asc_natal_house and sr_asc_natal_house in relevant_houses:
        score += SR_ASC_NATAL_HOUSE_HIT_BONUS
        factors.append({
            "type": "sr_asc_in_relevant_natal_house",
            "sr_asc_natal_house": sr_asc_natal_house,
            "weight": SR_ASC_NATAL_HOUSE_HIT_BONUS,
        })

    # SR MC natal evi
    sr_mc_natal_house = sr_data.get("sr_mc_in_natal_house")
    if sr_mc_natal_house and sr_mc_natal_house in relevant_houses:
        score += SR_MC_NATAL_HOUSE_HIT_BONUS
        factors.append({
            "type": "sr_mc_in_relevant_natal_house",
            "sr_mc_natal_house": sr_mc_natal_house,
            "weight": SR_MC_NATAL_HOUSE_HIT_BONUS,
        })

    # SR tema gezegenleri (ASC/MC üzerindeki SR gezegenleri) relevant mı?
    yearly_themes = sr_data.get("yearly_themes") or {}
    for angle_key in ("ascendant", "midheaven"):
        for theme in yearly_themes.get(angle_key, []):
            planet_id = theme.get("planet")
            if planet_id in relevant_planets:
                score += SR_THEME_PLANET_RELEVANT_BONUS
                factors.append({
                    "type": "sr_theme_planet_relevant",
                    "angle": angle_key,
                    "planet": planet_id,
                    "orb": theme.get("orb"),
                    "weight": SR_THEME_PLANET_RELEVANT_BONUS,
                })

    # SR-natal major aspect'ler: SR veya natal taraf relevant planet ise bonus
    for asp in sr_data.get("sr_natal_aspects", []):
        sr_body = asp.get("sr")
        natal_body = asp.get("natal")
        if sr_body not in relevant_planets and natal_body not in relevant_planets:
            continue
        aspect_type = asp.get("type")
        if aspect_type in SR_HARD_ASPECTS:
            bonus = SR_NATAL_HARD_ASPECT_BONUS
        else:
            bonus = SR_NATAL_SOFT_ASPECT_BONUS
        score += bonus
        factors.append({
            "type": "sr_natal_relevant_aspect",
            "sr_body": sr_body,
            "natal_body": natal_body,
            "aspect": aspect_type,
            "orb": asp.get("orb"),
            "weight": bonus,
        })

    return {
        "score": round(score, 2),
        "factors": factors,
        "sr_year": sr_data.get("return_year"),
        "sr_asc_natal_house": sr_asc_natal_house,
        "sr_mc_natal_house": sr_mc_natal_house,
    }


def _score_fixed_stars_layer(chart):
    """Aday natal chart'ının ASC/MC üzerindeki sabit yıldız kavuşumlarından skor.

    Tier-based bonus (royal=10, primary=5, secondary=2, tertiary=1).
    Orb factor: 0° tam bonus, 1° yarı bonus (lineer).
    Olay bağımsızdır; aday başına bir kez hesaplanır.

    sefstars.txt eksikse score=0 döner.
    """
    score = 0.0
    factors = []
    profile = []
    fixed_stars = chart.get("fixed_stars") or {}
    contacts = fixed_stars.get("contacts") or []

    for contact in contacts:
        if contact.get("body_id") not in FIXED_STAR_ANGLE_IDS:
            continue
        tier = contact.get("star_tier", "tertiary")
        base = FIXED_STAR_TIER_BONUS.get(tier, 1.0)
        orb = float(contact.get("orb", 0.0))
        # 0° → 1.0, 1° → 0.5 (lineer), alt sınır 0.5
        orb_factor = max(0.5, 1.0 - (orb / 2.0))
        bonus = round(base * orb_factor, 2)
        score += bonus
        factors.append({
            "type": "fixed_star_angle_conjunction",
            "angle": contact.get("body_id"),
            "star_id": contact.get("star_id"),
            "star_name_tr": contact.get("star_name_tr"),
            "tier": tier,
            "orb": orb,
            "weight": bonus,
        })
        profile.append({
            "angle": contact.get("body_id"),
            "star_id": contact.get("star_id"),
            "star_name_tr": contact.get("star_name_tr"),
            "tier": tier,
            "orb": orb,
            "nature_tr": contact.get("star_nature_tr"),
            "bonus": bonus,
        })

    return {
        "score": round(score, 2),
        "factors": factors,
        "angle_star_profile": profile,
        "available": fixed_stars.get("status") == "available",
    }


def _score_profection_layer(chart, rule, event_jd, birth_jd):
    score = 0.0
    factors = []
    profection = _calculate_profection(birth_jd, event_jd, chart)
    profected_house = profection["profected_house"]
    relevant_houses = {int(h) for h in rule.get("houses", []) if str(h).isdigit()}

    if profected_house in relevant_houses:
        score += PROFECTION_HOUSE_OVERLAP_WEIGHT
        factors.append({
            "type": "profected_house_matches_topic",
            "profected_house": profected_house,
            "weight": PROFECTION_HOUSE_OVERLAP_WEIGHT,
        })

    transit_positions = _calculate_transit_positions(event_jd)
    natal_planets = _planet_index_by_id(chart)

    for track_name, lord_id in (
        ("classical", profection["year_lord_classical"]),
        ("modern", profection["year_lord_modern"]),
    ):
        if lord_id not in transit_positions:
            continue
        lord_transit_long = transit_positions[lord_id]["longitude"]
        natal_lord = natal_planets.get(lord_id)
        if natal_lord:
            aspect = _aspect_within_orb(
                lord_transit_long,
                natal_lord["longitude"],
                PROFECTION_TRANSIT_ORB,
            )
            if aspect:
                score += PROFECTION_LORD_TRANSIT_HIT_WEIGHT
                factors.append({
                    "type": "year_lord_transit_to_natal_lord",
                    "track": track_name,
                    "lord": lord_id,
                    "aspect": aspect["type"],
                    "deviation": round(aspect["deviation"], 4),
                    "weight": PROFECTION_LORD_TRANSIT_HIT_WEIGHT,
                })
        cusps = _house_cusps(chart)
        lord_transit_house = _house_number_from_cusps(lord_transit_long, cusps)
        if lord_transit_house in relevant_houses:
            score += PROFECTION_LORD_TRANSIT_HIT_WEIGHT
            factors.append({
                "type": "year_lord_transit_in_relevant_house",
                "track": track_name,
                "lord": lord_id,
                "house": lord_transit_house,
                "weight": PROFECTION_LORD_TRANSIT_HIT_WEIGHT,
            })

    return {
        "score": round(score, 2),
        "factors": factors,
        "profection": profection,
    }


def _score_firdaria_layer(chart, rule, event, birth_jd):
    """Firdaria major/sub lordunun olay konusuyla örtüşmesini puanla.

    Olay bağımlı (profection'a paralel): olay tarihinde aktif olan klasik
    Pers time-lord (major + var ise sub) konunun karaka/yöneticisiyse bonus alır.

    calculate_firdaria mevcut chart'ı yeniden kullanır (chart param).
    """
    try:
        firdaria_data = calculate_firdaria(
            {"firdaria": {"target_date": event["date"]}},
            chart=chart,
        )
    except (FirdariaInputError, FirdariaCalculationError):
        return {"score": 0.0, "factors": []}

    relevant = (
        set(rule.get("karakas_classical", []))
        | set(rule.get("karakas_modern", []))
        | set(_primary_relevant_rulers(chart, rule, CLASSICAL_RULERS))
        | set(_primary_relevant_rulers(chart, rule, MODERN_RULERS))
    )

    score = 0.0
    factors = []

    current_major = firdaria_data.get("current_major") or {}
    major_lord = current_major.get("lord")
    if major_lord in relevant:
        score += FIRDARIA_MAJOR_LORD_RELEVANT_BONUS
        factors.append({
            "type": "firdaria_major_lord_relevant",
            "lord": major_lord,
            "lord_tr": current_major.get("lord_tr"),
            "weight": FIRDARIA_MAJOR_LORD_RELEVANT_BONUS,
        })

    current_sub = firdaria_data.get("current_sub")
    sub_lord = None
    if current_sub:
        sub_lord = current_sub.get("lord")
        if sub_lord in relevant:
            score += FIRDARIA_SUB_LORD_RELEVANT_BONUS
            factors.append({
                "type": "firdaria_sub_lord_relevant",
                "lord": sub_lord,
                "lord_tr": current_sub.get("lord_tr"),
                "weight": FIRDARIA_SUB_LORD_RELEVANT_BONUS,
            })

    return {
        "score": round(score, 2),
        "factors": factors,
        "major_lord": major_lord,
        "sub_lord": sub_lord,
        "chart_sect": firdaria_data.get("chart_sect"),
    }


def _score_event(chart, event, event_jd, birth_jd, options, pd_directions=None, sr_data=None):
    rule_key, rule = _event_rule(event.get("type"))
    if not rule:
        return {
            "event_type": event.get("type"),
            "date": event.get("date"),
            "topic": None,
            "supported": False,
            "score": 0.0,
            "raw_score": 0.0,
            "weighted_score": 0.0,
            "confidence": "none",
            "reason": "unsupported_event_type",
            "layer_scores": {key: 0.0 for key in LAYER_BASE_WEIGHTS},
            "factors": [],
        }

    weight = _weight_for_event(event)
    layer_results = {
        "natal": _score_natal_layer(chart, rule),
        "transit": _score_transit_layer(chart, rule, event_jd),
        "progression": _score_progression_layer(chart, rule, event_jd, birth_jd),
        "solar_arc": _score_solar_arc_layer(chart, rule, event_jd, birth_jd),
        "profection": _score_profection_layer(chart, rule, event_jd, birth_jd),
        "firdaria": _score_firdaria_layer(chart, rule, event, birth_jd),
        "primary_directions": _score_primary_directions_layer(
            chart, rule, event, pd_directions or [], birth_jd,
        ),
        "solar_return": _score_solar_return_layer(chart, rule, event, sr_data),
    }

    # Olay tipine göre layer ağırlıklarını uygula
    event_layer_w = _event_layer_weights(rule_key)
    weighted_layer_scores = {
        key: round(layer["score"] * event_layer_w.get(key, 1.0), 2)
        for key, layer in layer_results.items()
    }
    raw_score = sum(layer["score"] for layer in layer_results.values())
    layer_adjusted_score = sum(weighted_layer_scores.values())
    weighted_score = round(layer_adjusted_score * weight["combined_weight"], 2)
    factors = []
    for layer_name, layer in layer_results.items():
        for factor in layer["factors"]:
            factors.append({"layer": layer_name, **factor})

    confidence = "medium" if factors else "low"
    return {
        "event_type": event.get("type"),
        "rule_key": rule_key,
        "date": event.get("date"),
        "time": event.get("time") or "12:00",
        "topic": rule["topic"],
        "supported": True,
        "score": weighted_score,
        "raw_score": round(raw_score, 2),
        "weighted_score": weighted_score,
        "event_weight": weight,
        "confidence": confidence,
        "certainty": weight["certainty"],
        "relevant_houses": layer_results["natal"]["relevant_houses"],
        "primary_rulers_classical": layer_results["natal"]["primary_rulers_classical"],
        "primary_rulers_modern": layer_results["natal"]["primary_rulers_modern"],
        "karakas_classical": layer_results["natal"]["karakas_classical"],
        "karakas_modern": layer_results["natal"]["karakas_modern"],
        "layer_scores": {
            key: round(value["score"], 2) for key, value in layer_results.items()
        },
        "weighted_layer_scores": weighted_layer_scores,
        "event_layer_weights": event_layer_w,
        "layer_adjusted_score": round(layer_adjusted_score, 2),
        "factor_count": len(factors),
        "factors": factors,
    }


# ---------------------------------------------------------------------------
# Data quality / missing requirements
# ---------------------------------------------------------------------------


def _rectification_data_quality(events, source_docs, birth_window):
    return {
        "status": "available",
        "event_count": len(events),
        "supported_event_count": sum(1 for event in events if event.get("supported")),
        "source_doc_count": len(source_docs),
        "source_quality": birth_window.get("source_quality", "unknown"),
        "birth_window_provided": bool(
            birth_window.get("start_local") and birth_window.get("end_local")
        ),
    }


def _rectification_missing_requirements(events, source_docs, birth_window):
    missing = []
    if len(events) < 3:
        missing.append({
            "key": "events",
            "reason": "at_least_three_events_recommended",
            "minimum_recommended": 8,
        })
    if not source_docs:
        missing.append({
            "key": "source_docs",
            "reason": "no_birth_record_documents_supplied",
        })
    if not birth_window.get("start_local") or not birth_window.get("end_local"):
        missing.append({
            "key": "birth_window",
            "reason": "birth_window_not_supplied",
        })
    return missing


# ---------------------------------------------------------------------------
# Candidate window helpers (post-ranking)
# ---------------------------------------------------------------------------


def _build_candidate_windows(ranked):
    if not ranked:
        return []
    sorted_by_time = sorted(ranked, key=lambda item: item["time"])
    top_score = max(item["ranking_score"] for item in ranked)
    threshold = top_score * 0.8 if top_score > 0 else float("-inf")
    windows = []
    current = None
    for candidate in sorted_by_time:
        if candidate["ranking_score"] >= threshold:
            if current is None:
                current = {
                    "start_time": candidate["time"],
                    "end_time": candidate["time"],
                    "best_score": candidate["ranking_score"],
                    "best_time": candidate["time"],
                    "candidate_count": 1,
                }
            else:
                current["end_time"] = candidate["time"]
                current["candidate_count"] += 1
                if candidate["ranking_score"] > current["best_score"]:
                    current["best_score"] = candidate["ranking_score"]
                    current["best_time"] = candidate["time"]
        elif current is not None:
            windows.append(current)
            current = None
    if current is not None:
        windows.append(current)
    return windows


def _cross_validate_ranking(candidates, ranked):
    """Leave-one-out cross-validation: orijinal top adayın olaylara bağımlılığı.

    Her olayı sırayla dışarıda bırakıp sıralamayı yeniden hesaplar.
    Chart yeniden hesaplanmaz; sadece skor toplamları.
    """
    if not candidates or not ranked:
        return {"enabled": False, "reason": "no_candidates", "runs": []}

    n_events = len(candidates[0].get("event_scores") or [])
    if n_events < CROSS_VAL_MIN_EVENTS:
        return {
            "enabled": False,
            "reason": "insufficient_events",
            "min_events": CROSS_VAL_MIN_EVENTS,
            "event_count": n_events,
            "runs": [],
        }

    original_top = ranked[0]
    original_top_time = original_top["time"]
    original_top_ranking_score = original_top["ranking_score"]

    runs = []
    top_times_per_run = []
    original_top_scores_in_loo = []

    for excluded_index in range(n_events):
        excluded_event_meta = candidates[0]["event_scores"][excluded_index]

        recomputed = []
        for c in candidates:
            new_event_total = sum(
                s["weighted_score"]
                for i, s in enumerate(c["event_scores"])
                if i != excluded_index
            )
            new_total = (
                new_event_total
                + c.get("fixed_stars_score", 0.0)
                + c.get("syzygy_score", 0.0)
                + c.get("parans_score", 0.0)
                + c.get("midpoints_score", 0.0)
            )
            new_ranking = (
                new_total
                + c["asc_anchor"]["score_adjustment"]
                + c["mc_anchor"]["score_adjustment"]
            )
            recomputed.append({
                "time": c["time"],
                "total_score": round(new_total, 2),
                "ranking_score": round(new_ranking, 2),
                "rankable": c["asc_anchor"].get("rankable", True),
            })

        rankable = [r for r in recomputed if r["rankable"]]
        pool = rankable or recomputed
        pool.sort(key=lambda r: (-r["ranking_score"], -r["total_score"], r["time"]))
        new_top = pool[0]

        orig_in_loo = next(
            (r for r in recomputed if r["time"] == original_top_time),
            None,
        )
        if orig_in_loo:
            original_top_scores_in_loo.append(orig_in_loo["ranking_score"])

        runs.append({
            "removed_event_index": excluded_index,
            "removed_event_date": excluded_event_meta.get("date"),
            "removed_event_type": excluded_event_meta.get("event_type"),
            "removed_event_topic": excluded_event_meta.get("topic"),
            "new_top_time": new_top["time"],
            "new_top_ranking_score": new_top["ranking_score"],
            "original_top_score_in_run": orig_in_loo["ranking_score"] if orig_in_loo else None,
            "matches_original": new_top["time"] == original_top_time,
        })
        top_times_per_run.append(new_top["time"])

    matches = sum(1 for r in runs if r["matches_original"])
    stability = round(matches / len(runs), 4) if runs else 0.0
    unique_tops = len(set(top_times_per_run))

    if unique_tops == 1:
        consistency = "stable"
    elif unique_tops <= 2:
        consistency = "moderate"
    else:
        consistency = "unstable"

    if original_top_scores_in_loo:
        volatility = round(
            max(original_top_scores_in_loo) - min(original_top_scores_in_loo),
            2,
        )
    else:
        volatility = 0.0

    return {
        "enabled": True,
        "method": "leave_one_out",
        "event_count": n_events,
        "runs_count": len(runs),
        "original_top_time": original_top_time,
        "original_top_ranking_score": original_top_ranking_score,
        "stability_score": stability,
        "unique_top_candidates": unique_tops,
        "top_consistency": consistency,
        "score_volatility": volatility,
        "runs": runs,
    }


def _build_event_evidence_matrix(ranked, events):
    if not ranked:
        return []
    top = ranked[0]
    matrix = []
    for event_index, event_score in enumerate(top["event_scores"]):
        event = events[event_index] if event_index < len(events) else {}
        matrix.append({
            "event_date": event.get("date"),
            "time_start_local": event.get("time_start_local"),
            "time_end_local": event.get("time_end_local"),
            "event_type": event.get("type"),
            "topic": event_score.get("topic"),
            "weighted_score": event_score.get("weighted_score"),
            "layer_scores": event_score.get("layer_scores"),
            "weighted_layer_scores": event_score.get("weighted_layer_scores"),
            "event_layer_weights": event_score.get("event_layer_weights"),
            "factor_count": event_score.get("factor_count"),
        })
    return matrix


def _score_candidate_at_seconds(
    birth_base,
    candidate_second,
    options,
    event_inputs,
    expected_asc,
    expected_mc,
    year,
    month,
    day,
    tz_offset,
    syzygy,
):
    """Tek bir candidate için tam scoring + anchor. Ana loop ve refinement paylaşır."""
    chart = _build_chart_for_candidate(birth_base, candidate_second, options)
    hour, minute, second = _hms_from_seconds(candidate_second)
    birth_jd = _julian_day_ut(year, month, day, hour, minute, second, tz_offset)

    fixed_stars_layer = _score_fixed_stars_layer(chart)
    fixed_stars_score = fixed_stars_layer["score"]

    syzygy_layer = _score_pre_natal_syzygy_layer(chart, syzygy)
    syzygy_score = syzygy_layer["score"]

    parans_layer = _score_parans_layer(chart)
    parans_score = parans_layer["score"]

    midpoints_layer = _score_midpoints_layer(chart)
    midpoints_score = midpoints_layer["score"]

    # Primary directions: aday başına bir kez compute, tüm olaylar paylaşır
    pd_directions = _compute_primary_directions_for_candidate(
        chart, event_inputs, birth_jd,
    )

    # Solar Return: aday başına yıl-bazlı cache; her olayın SR'si ayrı
    sr_cache = {}

    event_scores = []
    for item in event_inputs:
        sr_data = _compute_solar_return_for_event(
            birth_base, chart, item["event"], sr_cache,
        )
        event_scores.append(
            _score_event(chart, item["event"], item["jd"], birth_jd, options, pd_directions, sr_data)
        )
    event_total = round(sum(score["weighted_score"] for score in event_scores), 2)
    average = round(event_total / len(event_scores), 2) if event_scores else 0.0
    total_score = round(event_total + fixed_stars_score + syzygy_score + parans_score + midpoints_score, 2)
    layer_scores_total = {
        key: round(
            sum(score["layer_scores"].get(key, 0.0) for score in event_scores),
            2,
        )
        for key in LAYER_BASE_WEIGHTS
    }
    layer_scores_total["fixed_stars"] = round(fixed_stars_score, 2)
    layer_scores_total["syzygy"] = round(syzygy_score, 2)
    layer_scores_total["parans"] = round(parans_score, 2)
    layer_scores_total["midpoints"] = round(midpoints_score, 2)

    candidate = {
        "time": _time_label_from_seconds(candidate_second),
        "hour": hour,
        "minute": minute,
        "second": second,
        "birth_jd": round(birth_jd, 6),
        "event_total_score": event_total,
        "average_event_score": average,
        "fixed_stars_score": round(fixed_stars_score, 2),
        "fixed_stars_factors": fixed_stars_layer["factors"],
        "angle_star_profile": fixed_stars_layer["angle_star_profile"],
        "fixed_stars_available": fixed_stars_layer["available"],
        "syzygy_score": round(syzygy_score, 2),
        "syzygy_factors": syzygy_layer["factors"],
        "syzygy_aspects": syzygy_layer["aspects"],
        "parans_score": round(parans_score, 2),
        "parans_factors": parans_layer["factors"],
        "nearest_paran": parans_layer.get("nearest_to_birth"),
        "parans_available": parans_layer["available"],
        "midpoints_score": round(midpoints_score, 2),
        "midpoints_factors": midpoints_layer["factors"],
        "top_midpoint_hit": midpoints_layer.get("top_hit"),
        "midpoints_hit_count": midpoints_layer.get("hit_count", 0),
        "midpoints_available": midpoints_layer["available"],
        "pd_directions_count": len(pd_directions),
        "pd_directions": pd_directions,
        "total_score": total_score,
        "ranking_score": total_score,
        "rank": None,
        "confidence": "medium" if average >= 20 else "low",
        "ascendant": chart["angles"]["ascendant"],
        "midheaven": chart["angles"]["midheaven"],
        "event_scores": event_scores,
        "layer_scores_total": layer_scores_total,
    }
    candidate["asc_anchor"] = _ascendant_anchor_for_candidate(candidate, expected_asc)
    candidate["mc_anchor"] = _midheaven_anchor_for_candidate(candidate, expected_mc)
    candidate["ranking_score"] = round(
        candidate["total_score"]
        + candidate["asc_anchor"]["score_adjustment"]
        + candidate["mc_anchor"]["score_adjustment"],
        2,
    )
    return candidate


def _refine_top_candidates(
    ranked,
    birth_base,
    options,
    event_inputs,
    expected_asc,
    expected_mc,
    year,
    month,
    day,
    tz_offset,
    search_window,
    syzygy,
):
    """Top N adayın ±REFINEMENT_RADIUS etrafında REFINEMENT_STEP ile hassas tarama."""
    if not ranked:
        return {
            "enabled": False,
            "reason": "no_candidates",
            "groups": [],
        }

    rankable = [c for c in ranked if c["asc_anchor"].get("rankable", True)]
    pool = rankable or ranked
    top = pool[:REFINEMENT_TOP_N]

    sw_start = search_window["_start_seconds"]
    sw_end = search_window["_end_seconds"]

    refined_groups = []
    seen_seconds = set()

    for parent in top:
        parent_seconds = parent["hour"] * 3600 + parent["minute"] * 60 + parent["second"]
        sub_candidates = []
        sec = parent_seconds - REFINEMENT_RADIUS_SECONDS
        while sec <= parent_seconds + REFINEMENT_RADIUS_SECONDS:
            if sw_start <= sec <= sw_end and sec not in seen_seconds:
                seen_seconds.add(sec)
                sub = _score_candidate_at_seconds(
                    birth_base,
                    sec,
                    options,
                    event_inputs,
                    expected_asc,
                    expected_mc,
                    year,
                    month,
                    day,
                    tz_offset,
                    syzygy,
                )
                sub_candidates.append(sub)
            sec += REFINEMENT_STEP_SECONDS

        sub_candidates.sort(
            key=lambda c: (-c["ranking_score"], -c["total_score"], c["time"])
        )

        best_sub = sub_candidates[0] if sub_candidates else None
        refined_groups.append({
            "parent_rank": parent["rank"],
            "parent_time": parent["time"],
            "parent_score": parent["ranking_score"],
            "best_time": best_sub["time"] if best_sub else parent["time"],
            "best_score": best_sub["ranking_score"] if best_sub else parent["ranking_score"],
            "delta": round(
                (best_sub["ranking_score"] - parent["ranking_score"]), 2
            ) if best_sub else 0.0,
            "sub_candidate_count": len(sub_candidates),
            "sub_candidates": [
                {
                    "time": c["time"],
                    "total_score": c["total_score"],
                    "ranking_score": c["ranking_score"],
                    "asc_status": c["asc_anchor"].get("status"),
                    "mc_status": c["mc_anchor"].get("status"),
                }
                for c in sub_candidates[:5]
            ],
        })

    best_overall = max(refined_groups, key=lambda g: g["best_score"]) if refined_groups else None
    return {
        "enabled": True,
        "radius_seconds": REFINEMENT_RADIUS_SECONDS,
        "step_seconds": REFINEMENT_STEP_SECONDS,
        "top_n_refined": REFINEMENT_TOP_N,
        "best_overall_time": best_overall["best_time"] if best_overall else None,
        "best_overall_score": best_overall["best_score"] if best_overall else None,
        "groups": refined_groups,
    }


# ---------------------------------------------------------------------------
# Main entry point
# ---------------------------------------------------------------------------


def calculate_rectification_analysis(data):
    """Rectify a birth time given dated life events and search window.

    Returns layered candidate evidence without selecting a final time.
    """

    if not isinstance(data, dict):
        raise RectificationInputError("İstek gövdesi nesne olmalı")

    birth_base = dict(data.get("birth_base") or {})
    if not birth_base:
        raise RectificationInputError("birth_base zorunludur")

    raw_events = data.get("events") or []
    if not raw_events:
        raise RectificationInputError("events listesi boş olamaz")

    options = dict(data.get("options") or {})

    try:
        year = int(birth_base["year"])
        month = int(birth_base["month"])
        day = int(birth_base["day"])
        lat = float(birth_base["lat"])
        lon = float(birth_base["lon"])
    except (KeyError, TypeError, ValueError) as exc:
        raise RectificationInputError(f"birth_base eksik veya hatalı: {exc}") from exc
    if not -90.0 <= lat <= 90.0:
        raise RectificationInputError("birth_base.lat -90 ile +90 arasında olmalı")
    if not -180.0 <= lon <= 180.0:
        raise RectificationInputError("birth_base.lon -180 ile +180 arasında olmalı")

    search_window = _normalize_search_window(data.get("search_window"))
    candidate_seconds = _candidate_seconds(search_window)

    # Resolve timezone using a noon reference (offsets stable across the day in TZDB)
    tz_offset, timezone_id = _resolve_timezone(birth_base, year, month, day, 12, 0, 0)
    birth_base["year"] = year
    birth_base["month"] = month
    birth_base["day"] = day
    birth_base["lat"] = lat
    birth_base["lon"] = lon
    birth_base["tz_offset"] = tz_offset
    if timezone_id:
        birth_base["timezone_id"] = timezone_id

    source_docs = _normalize_source_docs(data.get("source_docs"))
    birth_window = _normalize_birth_window(data, birth_base, search_window, source_docs)
    events = [
        _normalize_event(event, index, birth_window.get("timezone_id"))
        for index, event in enumerate(raw_events)
    ]

    data_quality = _rectification_data_quality(events, source_docs, birth_window)
    missing = _rectification_missing_requirements(events, source_docs, birth_window)
    expected_asc = _expected_ascendant_from_birth_base(birth_base, options)
    expected_mc = _expected_midheaven_from_birth_base(birth_base)

    event_inputs = []
    for event in events:
        event_tz_offset = _event_timezone_offset(event, tz_offset)
        event_jd = _parse_event_jd(event, event_tz_offset)
        event_inputs.append({"event": event, "jd": event_jd, "tz_offset": event_tz_offset})

    # Pre-natal syzygy: doğum günü noon referansıyla bir kez hesapla, tüm adaylar paylaşır
    reference_jd = _julian_day_ut(year, month, day, 12, 0, 0, tz_offset)
    syzygy = _find_pre_natal_syzygy(reference_jd)

    candidates = [
        _score_candidate_at_seconds(
            birth_base,
            candidate_second,
            options,
            event_inputs,
            expected_asc,
            expected_mc,
            year,
            month,
            day,
            tz_offset,
            syzygy,
        )
        for candidate_second in candidate_seconds
    ]

    ranked = sorted(
        candidates,
        key=lambda item: (-item["ranking_score"], -item["total_score"], item["time"]),
    )
    for index, candidate in enumerate(ranked, start=1):
        candidate["rank"] = index

    rankable = [c for c in ranked if c["asc_anchor"].get("rankable", True)]
    ranking_pool = rankable or ranked
    top_score = ranking_pool[0]["ranking_score"] if ranking_pool else 0.0
    top_candidates = [
        c for c in ranking_pool if c["ranking_score"] == top_score
    ][:5]
    candidate_windows = _build_candidate_windows(ranking_pool)
    event_evidence_matrix = _build_event_evidence_matrix(ranked, events)
    cross_validation = _cross_validate_ranking(candidates, ranked)

    refinement = _refine_top_candidates(
        ranked,
        birth_base,
        options,
        event_inputs,
        expected_asc,
        expected_mc,
        year,
        month,
        day,
        tz_offset,
        search_window,
        syzygy,
    )

    return {
        "status": "implemented_layered_rectification_evidence",
        "method": "natal_house_lord_plus_transit_progression_solar_arc_profection_with_asc_anchor",
        "version": "1.0.0",
        "engine": "western-rectification",
        "engine_version": "0.2.0",
        "confidence": "low" if len(events) < 3 else "medium",
        "assumptions": [
            "technical_evidence_only_no_selected_time_claim",
            "events_use_noon_when_time_is_missing",
            "candidate_search_uses_fixed_minute_step",
            "tropical_zodiac",
            "placidus_or_whole_sign_via_options",
            "naibod_solar_arc_per_year",
            "secondary_progressions_one_day_per_year",
            "annual_profections_twelve_year_cycle",
            "asc_anchor_eliminates_sign_mismatch_candidates",
            "mc_anchor_optional_secondary_filter",
            "modern_and_classical_rulers_evaluated_in_parallel",
            "parans_use_default_36_star_brady_list_and_30_minute_orb",
            "midpoints_occupied_orb_1_degree_default",
            "firdaria_uses_default_reference_timezone_europe_istanbul",
        ],
        "excluded_rules": [
            "tertiary_or_minor_progressions",
            "lunar_returns",
            "harmonics",
            "machine_learning_probability_model",
        ],
        "layer_definitions": {
            "natal": "Natal house lords and karakas placed in topic houses (classical and modern in parallel)",
            "transit": "Event-time transits in topic houses and to natal planets",
            "progression": "Secondary progressions to natal angles and planets",
            "solar_arc": "Naibod solar arc directed planets and angles",
            "profection": "Annual profected house and year lord transits",
            "firdaria": "Klasik Pers time-lord (Firdaria): olay tarihinde aktif major/sub lord konu evinin karaka/yöneticisiyse bonus",
            "fixed_stars": "Klasik sabit yıldız kavuşumları natal ASC/MC ile (60 yıldız, orb 1°, tier-based bonus: royal=10, primary=5, secondary=2, tertiary=1)",
            "syzygy": "Pre-natal syzygy (Ptolemaios): doğum öncesi son Yeni Ay/Dolunay derecesi ile natal ASC/MC arası aspect (orb 1° tight + 2° wide hard aspect)",
            "parans": "Brady Visual Astrology paranları: doğum anına ≤5dk (tight) veya ≤15dk (wide) mesafede gezegen/sabit yıldız açısal eşzamanlılığı (rise/set/culminate/anti-culminate); doğum saatinin astronomik işaretini destekler",
            "midpoints": "Cosmobiology midpoints: ASC/MC'nin başka gezegen çiftlerinin midpoint'ine (direct/opposite, orb ≤1°) denk gelmesi; luminer (Güneş/Ay) içeren midpoint'ler ekstra ağırlık alır",
            "primary_directions": "Placidus semi-arc mundane direct primary directions; olay yaşına denk gelen yönelimler (±60 gün tolerans, klasik 7 ışık + ASC/MC significator)",
            "solar_return": "Solar Return: olay yılına ait SR ASC/MC natal evi, tema gezegenleri ve SR-natal major aspect eşleşmesi (yıl-bazlı cache, doğum yeri SR)",
        },
        "input": {
            "birth_base": {
                "year": year,
                "month": month,
                "day": day,
                "lat": lat,
                "lon": lon,
                "timezone_id": timezone_id,
                "tz_offset": tz_offset,
                "place": birth_base.get("place"),
                "time_confidence": birth_base.get("time_confidence"),
                "expected_asc": expected_asc,
                "expected_mc": expected_mc,
            },
            "birth_window": birth_window,
            "source_docs": source_docs,
            "search_window": {
                "start_time": search_window["start_time"],
                "end_time": search_window["end_time"],
                "step_minutes": search_window["step_minutes"],
                "step_seconds": search_window["step_seconds"],
            },
            "options": {
                "house_system": options.get("house_system", "placidus"),
                "node_type": options.get("node_type", "true"),
                "orb_profile": options.get("orb_profile", "modern_standard_v1"),
            },
            "event_count": len(events),
            "minimum_recommended_events": 8,
            "professional_recommended_events": "8-20",
        },
        "data_quality": data_quality,
        "missing_requirements": missing,
        "candidate_count": len(candidates),
        "asc_anchor": expected_asc,
        "mc_anchor": expected_mc,
        "pre_natal_syzygy": syzygy,
        "candidate_windows": candidate_windows,
        "candidate_rankings": [
            {
                "rank": candidate["rank"],
                "time": candidate["time"],
                "total_score": candidate["total_score"],
                "ranking_score": candidate["ranking_score"],
                "asc_anchor": candidate["asc_anchor"],
                "mc_anchor": candidate["mc_anchor"],
                "layer_scores_total": candidate["layer_scores_total"],
                "fixed_stars_score": candidate["fixed_stars_score"],
                "angle_star_profile": candidate["angle_star_profile"],
                "syzygy_score": candidate["syzygy_score"],
                "syzygy_aspects": candidate["syzygy_aspects"],
                "parans_score": candidate["parans_score"],
                "nearest_paran": candidate["nearest_paran"],
                "midpoints_score": candidate["midpoints_score"],
                "top_midpoint_hit": candidate["top_midpoint_hit"],
                "pd_directions_count": candidate["pd_directions_count"],
            }
            for candidate in ranked
        ],
        "event_evidence_matrix": event_evidence_matrix,
        "cross_validation": cross_validation,
        "refinement": refinement,
        "top_candidates": top_candidates,
        "candidates": ranked,
    }


# ---------------------------------------------------------------------------
# Markdown report
# ---------------------------------------------------------------------------


def _md_value(value):
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(headers, rows):
    if not rows:
        return "Veri yok."
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_md_value(cell) for cell in row) + " |" for row in rows
    )
    return "\n".join(lines)


def build_rectification_report_markdown(analysis, person=None):
    person = person or {}
    person_name = person.get("name") or "—"
    group_name = person.get("group") or "Grup-01"
    birth_base = analysis["input"]["birth_base"]
    birth_window = analysis["input"]["birth_window"]
    search_window = analysis["input"]["search_window"]
    asc_anchor = analysis["asc_anchor"]
    mc_anchor = analysis["mc_anchor"]

    rankings = analysis["candidate_rankings"]
    windows = analysis["candidate_windows"]
    evidence = analysis["event_evidence_matrix"]
    refinement = analysis.get("refinement") or {}
    syzygy = analysis.get("pre_natal_syzygy")
    cross_val = analysis.get("cross_validation") or {}
    top_candidate_full = (analysis.get("candidates") or [{}])[0]
    all_top_paran_factors = top_candidate_full.get("parans_factors") or []
    top_parans_tight = [f for f in all_top_paran_factors if f.get("type") == "paran_tight_to_birth"]
    top_parans_wide = [f for f in all_top_paran_factors if f.get("type") == "paran_wide_to_birth"]
    top_midpoint_factors = top_candidate_full.get("midpoints_factors") or []

    sections = [
        "---",
        f'title: "{person_name} Western Rectification"',
        'type: "western_rectification_report"',
        'source: "western-astrology-api"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'birth_date: "{birth_base["year"]:04d}-{birth_base["month"]:02d}-{birth_base["day"]:02d}"',
        f'timezone: "{birth_base.get("timezone_id") or birth_base.get("tz_offset")}"',
        f'event_count: {analysis["input"]["event_count"]}',
        f'candidate_count: {analysis["candidate_count"]}',
        f'engine_version: "{analysis["engine_version"]}"',
        "---",
        "",
        f"# {person_name} — Batı Astrolojisi Rektifikasyon Raporu",
        "",
        "## Doğum Bilgisi",
        "",
        _md_table(
            ["Alan", "Değer"],
            [
                ("Tarih", f'{birth_base["year"]:04d}-{birth_base["month"]:02d}-{birth_base["day"]:02d}'),
                ("Saat dilimi", birth_base.get("timezone_id") or birth_base.get("tz_offset")),
                ("Enlem", birth_base["lat"]),
                ("Boylam", birth_base["lon"]),
                ("Yer", birth_base.get("place")),
                ("Saat güveni", birth_base.get("time_confidence")),
            ],
        ),
        "",
        "## Doğum Penceresi",
        "",
        _md_table(
            ["Alan", "Değer"],
            [
                ("Başlangıç (yerel)", birth_window.get("start_local")),
                ("Bitiş (yerel)", birth_window.get("end_local")),
                ("Saat dilimi", birth_window.get("timezone_id")),
                ("Kaynak kalitesi", birth_window.get("source_quality")),
            ],
        ),
        "",
        "## Arama Penceresi",
        "",
        _md_table(
            ["Alan", "Değer"],
            [
                ("Başlangıç", search_window.get("start_time")),
                ("Bitiş", search_window.get("end_time")),
                ("Adım (dk)", search_window.get("step_minutes")),
                ("Adım (sn)", search_window.get("step_seconds")),
            ],
        ),
        "",
        "## ASC Anchor",
        "",
        _md_table(
            ["Alan", "Değer"],
            [
                ("Durum", asc_anchor.get("status")),
                ("Beklenen burç", asc_anchor.get("sign_tr") or asc_anchor.get("sign")),
                ("Kaynak", asc_anchor.get("source")),
                ("Sebep", asc_anchor.get("reason")),
            ],
        ),
        "",
        "## MC Anchor",
        "",
        _md_table(
            ["Alan", "Değer"],
            [
                ("Durum", mc_anchor.get("status")),
                ("Beklenen burç", mc_anchor.get("sign_tr") or mc_anchor.get("sign")),
                ("Sebep", mc_anchor.get("reason")),
            ],
        ),
        "",
        "## Pre-Natal Syzygy",
        "",
        _md_table(
            ["Alan", "Değer"],
            [
                ("Tip", "Yeni Ay" if syzygy and syzygy.get("type") == "new_moon" else ("Dolunay" if syzygy and syzygy.get("type") == "full_moon" else "-")),
                ("Burc", syzygy.get("sign_tr") if syzygy else "-"),
                ("Derece", f"{syzygy['longitude']:.2f}°" if syzygy else "-"),
                ("Doğumdan gün önce", syzygy.get("days_before_birth") if syzygy else "-"),
            ],
        ),
        "",
        "## Parans (En İyi Aday)",
        "",
        (
            _md_table(
                ["Cisim A", "Açı", "Cisim B", "Açı", "Doğum Offset (dk)", "Tip"],
                [
                    (
                        p.get("body_a_tr") or p.get("body_a"),
                        p.get("body_a_angle"),
                        p.get("body_b_tr") or p.get("body_b"),
                        p.get("body_b_angle"),
                        f"{p.get('offset_from_birth_minutes', 0):+.2f}",
                        p.get("pair_kind"),
                    )
                    for p in (top_parans_tight or top_parans_wide)
                ],
            )
            if (top_parans_tight or top_parans_wide)
            else "_Doğum anına ±15 dakika içinde paran tespit edilmedi._"
        ),
        "",
        "## Midpoints (En İyi Aday)",
        "",
        (
            _md_table(
                ["Açı", "Çift", "Taraf", "Orb"],
                [
                    (
                        "Yükselen" if f.get("angle") == "ascendant" else "MC",
                        f"{f.get('from_tr') or f.get('from')} / {f.get('to_tr') or f.get('to')}",
                        "Direct" if f.get("side") == "direct" else "Opposite",
                        f"{f.get('orb', 0):.2f}°",
                    )
                    for f in top_midpoint_factors
                ],
            )
            if top_midpoint_factors
            else "_ASC/MC, orb ≤1° içinde herhangi bir midpoint'e denk gelmiyor._"
        ),
        "",
        "## Aday Pencereleri (en yüksek skorun %80'i ve üstü)",
        "",
        _md_table(
            ["Başlangıç", "Bitiş", "En iyi saat", "En iyi skor", "Aday sayısı"],
            [
                (
                    w["start_time"],
                    w["end_time"],
                    w["best_time"],
                    w["best_score"],
                    w["candidate_count"],
                )
                for w in windows
            ],
        ),
        "",
        "## Aday Sıralaması",
        "",
        _md_table(
            [
                "Sıra",
                "Saat",
                "Skor",
                "Sıra skoru",
                "ASC anchor",
                "MC anchor",
                "Natal",
                "Transit",
                "Progresyon",
                "Solar Arc",
                "Profection",
                "Fird",
                "F.Stars",
                "Syz",
                "Paran",
                "Mid",
                "PD",
                "SR",
            ],
            [
                (
                    r["rank"],
                    r["time"],
                    r["total_score"],
                    r["ranking_score"],
                    r["asc_anchor"].get("status"),
                    r["mc_anchor"].get("status"),
                    r["layer_scores_total"]["natal"],
                    r["layer_scores_total"]["transit"],
                    r["layer_scores_total"]["progression"],
                    r["layer_scores_total"]["solar_arc"],
                    r["layer_scores_total"]["profection"],
                    r["layer_scores_total"].get("firdaria", 0.0),
                    r["layer_scores_total"].get("fixed_stars", 0.0),
                    r["layer_scores_total"].get("syzygy", 0.0),
                    r["layer_scores_total"].get("parans", 0.0),
                    r["layer_scores_total"].get("midpoints", 0.0),
                    r["layer_scores_total"].get("primary_directions", 0.0),
                    r["layer_scores_total"].get("solar_return", 0.0),
                    )
                    for r in rankings
            ],
        ),
        "",
        "## En İyi Aday için Olay Kanıt Matrisi",
        "",
        _md_table(
            [
                "Tarih",
                "Tip",
                "Konu",
                "Ağırlıklı skor",
                "Natal*",
                "Transit*",
                "Prog*",
                "SA*",
                "Prof*",
                "Fird*",
                "PD*",
                "SR*",
                "Faktör",
            ],
            [
                (
                    row.get("event_date"),
                    row.get("event_type"),
                    row.get("topic"),
                    row.get("weighted_score"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("natal"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("transit"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("progression"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("solar_arc"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("profection"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("firdaria"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("primary_directions"),
                    (row.get("weighted_layer_scores") or row.get("layer_scores") or {}).get("solar_return"),
                    row.get("factor_count"),
                )
                for row in evidence
            ],
        ),
        "",
        "_* Olay tipine göre ayarlanmış layer skorları. Aşağıdaki tablo kullanılan ağırlıkları gösterir._",
        "",
        "### Olay Tipi Layer Ağırlıkları",
        "",
        _md_table(
            ["Tarih", "Tip", "Natal", "Transit", "Prog", "SA", "Prof", "PD", "SR"],
            [
                (
                    row.get("event_date"),
                    row.get("event_type"),
                    (row.get("event_layer_weights") or {}).get("natal"),
                    (row.get("event_layer_weights") or {}).get("transit"),
                    (row.get("event_layer_weights") or {}).get("progression"),
                    (row.get("event_layer_weights") or {}).get("solar_arc"),
                    (row.get("event_layer_weights") or {}).get("profection"),
                    (row.get("event_layer_weights") or {}).get("primary_directions"),
                    (row.get("event_layer_weights") or {}).get("solar_return"),
                )
                for row in evidence
            ],
        ),
        "",
        "## Uyarılar",
        "",
        "- Bu rapor hesaplanmış teknik kanıttır, kesin saat seçmez.",
        "- Olayların kesinliği ve sayısı sonucu doğrudan etkiler.",
        "- Bilinen ASC ile mismatch olan adaylar elendi.",
        "- Lunar Return ve istatistiksel model bu sürümde yok.",
        "",
    ]
    # En iyi adayın PD direction'ları
    top_pd_directions = []
    if analysis.get("candidates"):
        top_pd_directions = (analysis["candidates"][0] or {}).get("pd_directions") or []
    if top_pd_directions:
        sections.extend([
            "## Primary Directions (En iyi aday)",
            "",
            f"_Placidus semi-arc, mundane, direct. {len(top_pd_directions)} aktif yönelim._",
            "",
            _md_table(
                ["Tahmini Tarih", "Yaş", "Promissor", "Açı", "Significator", "Ark"],
                [
                    (
                        d.get("estimated_date_utc"),
                        f"{d.get('event_age', 0):.2f}",
                        d.get("promissor_tr") or d.get("promissor"),
                        d.get("aspect_tr") or d.get("aspect"),
                        d.get("significator_tr") or d.get("significator"),
                        f"{d.get('arc_of_direction_degrees', 0):.3f}°",
                    )
                    for d in top_pd_directions[:30]
                ],
            ),
            "",
        ])
    if cross_val.get("enabled") and cross_val.get("runs"):
        consistency_tr = {
            "stable": "sabit (tüm turlarda aynı top)",
            "moderate": "orta (1-2 farklı top)",
            "unstable": "kararsız (3+ farklı top)",
        }.get(cross_val.get("top_consistency"), cross_val.get("top_consistency"))
        sections.extend([
            "## Cross-Validation (Leave-One-Out)",
            "",
            f"_Her olay sırayla dışarıda bırakılarak sıralama yeniden hesaplandı. "
            f"Orijinal top: **{cross_val.get('original_top_time')}** "
            f"(skor {cross_val.get('original_top_ranking_score')})._",
            "",
            _md_table(
                ["Metrik", "Değer"],
                [
                    ("Olay sayısı", cross_val.get("event_count")),
                    ("Tur sayısı", cross_val.get("runs_count")),
                    ("Stability skoru", f"{cross_val.get('stability_score', 0) * 100:.0f}%"),
                    ("Farklı top aday sayısı", cross_val.get("unique_top_candidates")),
                    ("Top tutarlılığı", consistency_tr),
                    ("Skor oynaklığı (max-min)", cross_val.get("score_volatility")),
                ],
            ),
            "",
            "### LOO Turları",
            "",
            _md_table(
                ["Tur", "Çıkarılan olay", "Tip", "Yeni top", "Yeni skor", "Orijinal skor", "Eşleşme"],
                [
                    (
                        i + 1,
                        r.get("removed_event_date"),
                        r.get("removed_event_type"),
                        r.get("new_top_time"),
                        r.get("new_top_ranking_score"),
                        r.get("original_top_score_in_run"),
                        "✓" if r.get("matches_original") else "✗",
                    )
                    for i, r in enumerate(cross_val["runs"])
                ],
            ),
            "",
        ])
    if refinement.get("enabled") and refinement.get("groups"):
        sections.extend([
            "## Sub-Minute Refinement",
            "",
            f"_Top {refinement.get('top_n_refined')} adayın ±{refinement.get('radius_seconds')}sn etrafında {refinement.get('step_seconds')}sn adımla hassas tarama. "
            f"En iyi hassas saat: **{refinement.get('best_overall_time') or '-'}** (skor {refinement.get('best_overall_score') or '-'})._",
            "",
            _md_table(
                ["Ana sıra", "Ana saat", "Ana skor", "Hassas saat", "Hassas skor", "Delta", "Alt aday"],
                [
                    (
                        g.get("parent_rank"),
                        g.get("parent_time"),
                        g.get("parent_score"),
                        g.get("best_time"),
                        g.get("best_score"),
                        g.get("delta"),
                        g.get("sub_candidate_count"),
                    )
                    for g in refinement["groups"]
                ],
            ),
            "",
        ])
    rankings_with_stars = [r for r in rankings[:5] if r.get("angle_star_profile")]
    if rankings_with_stars:
        sections.extend([
            "## En İyi Adayların Angle Sabit Yıldız Profili",
            "",
            "_60 sabit yıldız (4 royal + 14 birinci + 10 ikinci + 32 üçüncü kademe), ASC ve MC ile orb 1° kavuşumlar. "
            "4 dakikalık ASC kayması farklı yıldız verir; rektifikasyon için ayırt edici filtre._",
            "",
            _md_table(
                ["Sıra", "Saat", "Angle", "Yıldız", "Kademe", "Orb", "Bonus", "Klasik Doğa"],
                [
                    (
                        r["rank"],
                        r["time"],
                        "Yükselen" if profile["angle"] == "ascendant" else "MC",
                        profile["star_name_tr"],
                        profile["tier"],
                        f"{profile['orb']:.2f}°",
                        profile["bonus"],
                        profile.get("nature_tr") or "-",
                    )
                    for r in rankings_with_stars
                    for profile in r["angle_star_profile"]
                ],
            ),
            "",
        ])
    return "\n".join(sections)
