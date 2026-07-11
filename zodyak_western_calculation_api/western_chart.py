#!/usr/bin/env python3
"""Western astrology core calculations backed by Swiss Ephemeris."""

from __future__ import annotations

import math
import os
from itertools import combinations
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

from .western_fixed_stars import (
    FIXED_STAR_ORB,
    STAR_CATALOG,
    find_star_conjunctions,
    is_available as _fixed_stars_available,
)

# Configure Swiss Ephemeris file path for asteroids (Chiron etc.)
_EPHE_PATH = os.path.join(os.path.dirname(os.path.abspath(__file__)), "ephe")
if os.path.isdir(_EPHE_PATH):
    swe.set_ephe_path(_EPHE_PATH)


SIGNS = [
    ("Aries", "Koç"),
    ("Taurus", "Boğa"),
    ("Gemini", "İkizler"),
    ("Cancer", "Yengeç"),
    ("Leo", "Aslan"),
    ("Virgo", "Başak"),
    ("Libra", "Terazi"),
    ("Scorpio", "Akrep"),
    ("Sagittarius", "Yay"),
    ("Capricorn", "Oğlak"),
    ("Aquarius", "Kova"),
    ("Pisces", "Balık"),
]

PLANETS = [
    (swe.SUN, "sun", "Sun", "Güneş"),
    (swe.MOON, "moon", "Moon", "Ay"),
    (swe.MERCURY, "mercury", "Mercury", "Merkür"),
    (swe.VENUS, "venus", "Venus", "Venüs"),
    (swe.MARS, "mars", "Mars", "Mars"),
    (swe.JUPITER, "jupiter", "Jupiter", "Jüpiter"),
    (swe.SATURN, "saturn", "Saturn", "Satürn"),
    (swe.URANUS, "uranus", "Uranus", "Uranüs"),
    (swe.NEPTUNE, "neptune", "Neptune", "Neptün"),
    (swe.PLUTO, "pluto", "Pluto", "Plüton"),
    (swe.CHIRON, "chiron", "Chiron", "Şiron"),
]

HOUSE_SYSTEMS = {
    "placidus": b"P",
    "regiomontanus": b"R",
    "whole_sign": b"W",
}

ASPECTS = [
    ("conjunction", 0.0, "major", "neutral"),
    ("semisextile", 30.0, "minor", "neutral"),
    ("semisquare", 45.0, "minor", "challenging"),
    ("sextile", 60.0, "major", "harmonious"),
    ("quintile", 72.0, "minor", "harmonious"),
    ("square", 90.0, "major", "challenging"),
    ("trine", 120.0, "major", "harmonious"),
    ("sesquiquadrate", 135.0, "minor", "challenging"),
    ("biquintile", 144.0, "minor", "harmonious"),
    ("quincunx", 150.0, "minor", "adjustment"),
    ("opposition", 180.0, "major", "challenging"),
]

MODERN_STANDARD_V1 = {
    "conjunction": 8.0,
    "opposition": 8.0,
    "square": 7.0,
    "trine": 7.0,
    "sextile": 5.0,
    "quincunx": 3.0,
    "semisextile": 2.0,
    "semisquare": 2.0,
    "quintile": 2.0,
    "sesquiquadrate": 2.0,
    "biquintile": 2.0,
}

ORB_PROFILES = {
    "modern_standard_v1": MODERN_STANDARD_V1,
}

# Declination aspects (parallel / contraparallel / out-of-bounds)
DECLINATION_ORB = 1.0                  # parallel ve contraparallel orbı
OOB_DECLINATION_THRESHOLD = 23.4367    # Güneş'in maksimum declination'ı

# Jones chart shapes — pattern tespitinde kullanılan görünür 10 gezegen
JONES_PLANETS = {
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
}

TIME_CONFIDENCE = {"high", "rectified", "medium", "low", "unknown"}
NODE_TYPES = {"true", "mean"}

CLASSICAL_RULERS = {
    0: "mars",
    1: "venus",
    2: "mercury",
    3: "moon",
    4: "sun",
    5: "mercury",
    6: "venus",
    7: "mars",
    8: "jupiter",
    9: "saturn",
    10: "saturn",
    11: "jupiter",
}

MODERN_RULERS = {
    **CLASSICAL_RULERS,
    7: "pluto",
    10: "uranus",
    11: "neptune",
}

CLASSICAL_DOMICILES = {
    "sun": {4},
    "moon": {3},
    "mercury": {2, 5},
    "venus": {1, 6},
    "mars": {0, 7},
    "jupiter": {8, 11},
    "saturn": {9, 10},
}

CLASSICAL_EXALTATIONS = {
    "sun": 0,
    "moon": 1,
    "mercury": 5,
    "venus": 11,
    "mars": 9,
    "jupiter": 3,
    "saturn": 6,
}

SIGN_ELEMENTS = [
    "fire", "earth", "air", "water",
    "fire", "earth", "air", "water",
    "fire", "earth", "air", "water",
]

SIGN_MODALITIES = [
    "cardinal", "fixed", "mutable",
    "cardinal", "fixed", "mutable",
    "cardinal", "fixed", "mutable",
    "cardinal", "fixed", "mutable",
]

SIGN_POLARITIES = [
    "positive", "negative", "positive", "negative",
    "positive", "negative", "positive", "negative",
    "positive", "negative", "positive", "negative",
]

CLASSICAL_PLANETS = {
    "sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn",
}

DIURNAL_SECT_PLANETS = {"sun", "jupiter", "saturn"}
NOCTURNAL_SECT_PLANETS = {"moon", "venus", "mars"}

# Dorothean triplicity rulers (Hellenistic/traditional standard).
# Each element has three lords: diurnal (day), nocturnal (night),
# participating (cooperating). The active lord in a chart depends on sect.
TRIPLICITY_RULERS = {
    "fire":  {"diurnal": "sun",   "nocturnal": "jupiter", "participating": "saturn"},
    "earth": {"diurnal": "venus", "nocturnal": "moon",    "participating": "mars"},
    "air":   {"diurnal": "saturn","nocturnal": "mercury", "participating": "jupiter"},
    "water": {"diurnal": "venus", "nocturnal": "mars",    "participating": "moon"},
}

# Egyptian bounds (terms): each sign divided into five unequal segments,
# each ruled by one of the five classical non-luminary planets.
# Format per sign: list of (start_degree, end_degree, planet_id).
EGYPTIAN_BOUNDS = {
    0:  [(0, 6, "jupiter"), (6, 12, "venus"),   (12, 20, "mercury"), (20, 25, "mars"),    (25, 30, "saturn")],
    1:  [(0, 8, "venus"),   (8, 14, "mercury"), (14, 22, "jupiter"), (22, 27, "saturn"),  (27, 30, "mars")],
    2:  [(0, 6, "mercury"), (6, 12, "jupiter"), (12, 17, "venus"),   (17, 24, "mars"),    (24, 30, "saturn")],
    3:  [(0, 7, "mars"),    (7, 13, "venus"),   (13, 19, "mercury"), (19, 26, "jupiter"), (26, 30, "saturn")],
    4:  [(0, 6, "jupiter"), (6, 11, "venus"),   (11, 18, "saturn"),  (18, 24, "mercury"), (24, 30, "mars")],
    5:  [(0, 7, "mercury"), (7, 17, "venus"),   (17, 21, "jupiter"), (21, 28, "mars"),    (28, 30, "saturn")],
    6:  [(0, 6, "saturn"),  (6, 14, "mercury"), (14, 21, "jupiter"), (21, 28, "venus"),   (28, 30, "mars")],
    7:  [(0, 7, "mars"),    (7, 11, "venus"),   (11, 19, "mercury"), (19, 24, "jupiter"), (24, 30, "saturn")],
    8:  [(0, 12, "jupiter"),(12, 17, "venus"),  (17, 21, "mercury"), (21, 26, "saturn"),  (26, 30, "mars")],
    9:  [(0, 7, "mercury"), (7, 14, "jupiter"), (14, 22, "venus"),   (22, 26, "saturn"),  (26, 30, "mars")],
    10: [(0, 7, "mercury"), (7, 13, "venus"),   (13, 20, "jupiter"), (20, 25, "mars"),    (25, 30, "saturn")],
    11: [(0, 12, "venus"),  (12, 16, "jupiter"),(16, 19, "mercury"), (19, 28, "mars"),    (28, 30, "saturn")],
}

# Chaldean faces/decans: each sign divided into three 10-degree thirds,
# rulers cycling in Chaldean order (Saturn-Jupiter-Mars-Sun-Venus-Mercury-Moon).
# Format per sign: list of three planet_ids (0-10°, 10-20°, 20-30°).
CHALDEAN_FACES = {
    0:  ["mars", "sun", "venus"],
    1:  ["mercury", "moon", "saturn"],
    2:  ["jupiter", "mars", "sun"],
    3:  ["venus", "mercury", "moon"],
    4:  ["saturn", "jupiter", "mars"],
    5:  ["sun", "venus", "mercury"],
    6:  ["moon", "saturn", "jupiter"],
    7:  ["mars", "sun", "venus"],
    8:  ["mercury", "moon", "saturn"],
    9:  ["jupiter", "mars", "sun"],
    10: ["venus", "mercury", "moon"],
    11: ["saturn", "jupiter", "mars"],
}


class ChartInputError(ValueError):
    """Raised when request data cannot define a valid chart."""


class ChartCalculationError(RuntimeError):
    """Raised when Swiss Ephemeris cannot calculate a requested chart."""

    def __init__(self, message: str, code: str = "calculation_error"):
        super().__init__(message)
        self.code = code


def _require_int(data: dict, key: str) -> int:
    if key not in data:
        raise ChartInputError(f"Eksik alan: birth.{key}")
    try:
        return int(data[key])
    except (TypeError, ValueError) as exc:
        raise ChartInputError(f"birth.{key} tam sayı olmalıdır") from exc


def _require_float(data: dict, key: str) -> float:
    if key not in data:
        raise ChartInputError(f"Eksik alan: birth.{key}")
    try:
        value = float(data[key])
    except (TypeError, ValueError) as exc:
        raise ChartInputError(f"birth.{key} sayı olmalıdır") from exc
    if not math.isfinite(value):
        raise ChartInputError(f"birth.{key} sonlu bir sayı olmalıdır")
    return value


def _degree_fields(longitude: float) -> dict:
    longitude = longitude % 360.0
    sign_index = int(longitude // 30.0)
    degree = longitude % 30.0
    whole_degree = int(degree)
    minute_float = (degree - whole_degree) * 60.0
    minute = int(minute_float)
    second = (minute_float - minute) * 60.0
    sign, sign_tr = SIGNS[sign_index]
    return {
        "longitude": round(longitude, 8),
        "sign_index": sign_index,
        "sign": sign,
        "sign_tr": sign_tr,
        "degree": round(degree, 8),
        "degree_str": f"{whole_degree}°{minute:02d}'{second:04.1f}\"",
    }


def _signed_delta(value: float, reference: float) -> float:
    return ((value - reference + 180.0) % 360.0) - 180.0


def _shortest_separation(longitude_a: float, longitude_b: float) -> float:
    return abs(_signed_delta(longitude_a, longitude_b))


def _ephemeris_source(retflags: int) -> str:
    if retflags & swe.FLG_JPLEPH:
        return "jpl_ephemeris"
    if retflags & swe.FLG_SWIEPH:
        return "swiss_ephemeris_files"
    if retflags & swe.FLG_MOSEPH:
        return "moshier_analytical_fallback"
    return "unknown"


def _resolve_local_datetime(birth: dict) -> tuple[datetime, float, str | None, list[str]]:
    year = _require_int(birth, "year")
    month = _require_int(birth, "month")
    day = _require_int(birth, "day")
    hour = _require_int(birth, "hour")
    minute = _require_int(birth, "minute")
    second = int(birth.get("second") or 0)

    if not 0 <= hour <= 23:
        raise ChartInputError("birth.hour 0 ile 23 arasında olmalıdır")
    if not 0 <= minute <= 59:
        raise ChartInputError("birth.minute 0 ile 59 arasında olmalıdır")
    if not 0 <= second <= 59:
        raise ChartInputError("birth.second 0 ile 59 arasında olmalıdır")

    try:
        naive = datetime(year, month, day, hour, minute, second)
    except ValueError as exc:
        raise ChartInputError(f"Geçersiz doğum tarihi veya saati: {exc}") from exc

    warnings = []
    timezone_id = birth.get("timezone_id")
    if timezone_id:
        try:
            zone = ZoneInfo(str(timezone_id))
        except ZoneInfoNotFoundError as exc:
            raise ChartInputError(f"Geçersiz birth.timezone_id: {timezone_id}") from exc

        candidates = []
        for fold in (0, 1):
            candidate = naive.replace(tzinfo=zone, fold=fold)
            roundtrip = candidate.astimezone(timezone.utc).astimezone(zone)
            if roundtrip.replace(tzinfo=None) == naive:
                candidates.append(candidate)

        unique_offsets = {
            candidate.utcoffset()
            for candidate in candidates
            if candidate.utcoffset() is not None
        }
        if not candidates:
            raise ChartInputError(
                "Doğum saati seçilen timezone_id içinde mevcut değil "
                "(yaz/kış saati geçiş boşluğu)"
            )

        requested_fold = birth.get("fold")
        if len(unique_offsets) > 1:
            if requested_fold is None:
                warnings.append(
                    "Doğum saati yaz/kış saati geçişinde iki olası UTC anına karşılık "
                    "geliyor; birth.fold verilmediği için fold=0 kullanıldı."
                )
                fold = 0
            else:
                try:
                    fold = int(requested_fold)
                except (TypeError, ValueError) as exc:
                    raise ChartInputError("birth.fold 0 veya 1 olmalıdır") from exc
                if fold not in (0, 1):
                    raise ChartInputError("birth.fold 0 veya 1 olmalıdır")
            local_dt = naive.replace(tzinfo=zone, fold=fold)
        else:
            local_dt = candidates[0]

        offset = local_dt.utcoffset()
        if offset is None:
            raise ChartInputError("timezone_id için UTC farkı çözülemedi")
        return local_dt, offset.total_seconds() / 3600.0, str(timezone_id), warnings

    if "tz_offset" not in birth:
        raise ChartInputError("birth.timezone_id veya birth.tz_offset zorunludur")

    try:
        tz_offset = float(birth["tz_offset"])
    except (TypeError, ValueError) as exc:
        raise ChartInputError("birth.tz_offset sayı olmalıdır") from exc
    if not math.isfinite(tz_offset) or not -14.0 <= tz_offset <= 14.0:
        raise ChartInputError("birth.tz_offset -14 ile +14 arasında olmalıdır")

    warnings.append(
        "Sabit tz_offset kullanıldı; tarihsel yaz/kış saati doğruluğu için "
        "timezone_id tercih edilmelidir."
    )
    local_dt = naive.replace(tzinfo=timezone(timedelta(hours=tz_offset)))
    return local_dt, tz_offset, None, warnings


def _julian_day(dt_utc: datetime) -> float:
    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond / 3_600_000_000.0
    )
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)


def _house_number(longitude: float, cusps: list[float]) -> int:
    longitude %= 360.0
    for index, cusp in enumerate(cusps):
        next_cusp = cusps[(index + 1) % 12]
        span = (next_cusp - cusp) % 360.0
        offset = (longitude - cusp) % 360.0
        if offset < span or math.isclose(offset, 0.0, abs_tol=1e-9):
            return index + 1
    raise ChartCalculationError("Gezegen ev yerleşimi belirlenemedi")


def _calculate_houses(
    jd_ut: float,
    latitude: float,
    longitude: float,
    house_system: str,
) -> tuple[list[float], tuple[float, ...]]:
    try:
        cusps, ascmc = swe.houses_ex(
            jd_ut,
            latitude,
            longitude,
            HOUSE_SYSTEMS[house_system],
            0,
        )
    except swe.Error as exc:
        raise ChartCalculationError(
            f"{house_system} ev sistemi bu enlem/tarih için hesaplanamadı",
            code="house_system_unavailable",
        ) from exc
    return [float(cusp) % 360.0 for cusp in cusps], ascmc


def _body_position(
    jd_ut: float,
    planet_id: int,
    body_id: str,
    name: str,
    name_tr: str,
    cusps: list[float],
) -> tuple[dict, str]:
    try:
        values, retflags = swe.calc_ut(
            jd_ut,
            planet_id,
            swe.FLG_SWIEPH | swe.FLG_SPEED,
        )
    except swe.Error as exc:
        raise ChartCalculationError(f"{name} konumu hesaplanamadı") from exc

    longitude, latitude, distance, speed_longitude, speed_latitude, speed_distance = values
    row = {
        "id": body_id,
        "name": name,
        "name_tr": name_tr,
        **_degree_fields(longitude),
        "latitude": round(latitude, 8),
        "distance_au": round(distance, 10),
        "speed_longitude": round(speed_longitude, 8),
        "speed_latitude": round(speed_latitude, 8),
        "speed_distance": round(speed_distance, 10),
        "retrograde": speed_longitude < 0.0,
        "house": _house_number(longitude, cusps),
    }
    return row, _ephemeris_source(retflags)


def _calculate_nodes(
    jd_ut: float,
    node_type: str,
    cusps: list[float],
) -> tuple[list[dict], str]:
    planet_id = swe.TRUE_NODE if node_type == "true" else swe.MEAN_NODE
    north, source = _body_position(
        jd_ut,
        planet_id,
        "north_node",
        "North Node",
        "Kuzey Ay Düğümü",
        cusps,
    )
    north["node_type"] = node_type

    south_longitude = (north["longitude"] + 180.0) % 360.0
    south = {
        "id": "south_node",
        "name": "South Node",
        "name_tr": "Güney Ay Düğümü",
        **_degree_fields(south_longitude),
        "latitude": round(-north["latitude"], 8),
        "distance_au": north["distance_au"],
        "speed_longitude": north["speed_longitude"],
        "speed_latitude": round(-north["speed_latitude"], 8),
        "speed_distance": north["speed_distance"],
        "retrograde": north["retrograde"],
        "house": _house_number(south_longitude, cusps),
        "node_type": node_type,
        "derived_from": "north_node_plus_180_degrees",
    }
    return [north, south], source


def _effective_orbs(options: dict) -> tuple[str, dict[str, float], float]:
    profile = str(options.get("orb_profile") or "modern_standard_v1")
    if profile not in ORB_PROFILES:
        raise ChartInputError(
            f"Desteklenmeyen options.orb_profile: {profile}. "
            f"Desteklenen: {', '.join(sorted(ORB_PROFILES))}"
        )

    orbs = dict(ORB_PROFILES[profile])
    overrides = options.get("orb_overrides") or {}
    if not isinstance(overrides, dict):
        raise ChartInputError("options.orb_overrides nesne olmalıdır")

    for aspect, raw_value in overrides.items():
        if aspect == "sun_moon_bonus":
            continue
        if aspect not in orbs:
            raise ChartInputError(f"Bilinmeyen orb override açısı: {aspect}")
        try:
            value = float(raw_value)
        except (TypeError, ValueError) as exc:
            raise ChartInputError(f"Orb değeri sayı olmalıdır: {aspect}") from exc
        if not 0.0 <= value <= 12.0:
            raise ChartInputError(f"{aspect} orb değeri 0 ile 12 arasında olmalıdır")
        orbs[aspect] = value

    try:
        luminary_bonus = float(overrides.get("sun_moon_bonus", 2.0))
    except (TypeError, ValueError) as exc:
        raise ChartInputError("sun_moon_bonus sayı olmalıdır") from exc
    if not 0.0 <= luminary_bonus <= 2.0:
        raise ChartInputError("sun_moon_bonus 0 ile 2 arasında olmalıdır")

    return profile, orbs, luminary_bonus


def _calculate_aspects(
    bodies: list[dict],
    orbs: dict[str, float],
    luminary_bonus: float,
) -> dict:
    result = {"status": "available", "major": [], "minor": []}

    for first_index, first in enumerate(bodies):
        for second in bodies[first_index + 1 :]:
            separation = _shortest_separation(first["longitude"], second["longitude"])
            future_separation = _shortest_separation(
                first["longitude"] + first["speed_longitude"] / 1440.0,
                second["longitude"] + second["speed_longitude"] / 1440.0,
            )

            matches = []
            for aspect_type, exact_angle, group, nature in ASPECTS:
                orb = abs(separation - exact_angle)
                allowed_orb = orbs[aspect_type]
                if first["id"] in {"sun", "moon"} or second["id"] in {"sun", "moon"}:
                    allowed_orb += luminary_bonus
                if orb <= allowed_orb:
                    matches.append(
                        (orb, aspect_type, exact_angle, group, nature, allowed_orb)
                    )

            if not matches:
                continue

            orb, aspect_type, exact_angle, group, nature, allowed_orb = min(matches)
            future_orb = abs(future_separation - exact_angle)
            exact = orb <= 0.0001
            applying = None if exact else future_orb < orb
            row = {
                "from": first["id"],
                "to": second["id"],
                "type": aspect_type,
                "group": group,
                "exact_angle": exact_angle,
                "actual_angle": round(separation, 8),
                "orb": round(orb, 8),
                "allowed_orb": round(allowed_orb, 8),
                "applying": applying,
                "separating": None if exact else not applying,
                "exact": exact,
                "nature": nature,
                "motion_method": "one_minute_forward_longitude_projection",
            }
            result[group].append(row)

    for group in ("major", "minor"):
        result[group].sort(key=lambda row: (row["orb"], row["from"], row["to"]))
    return result


def _planet_declinations(
    jd_ut: float,
    ascendant: float,
    midheaven: float,
    obliquity_deg: float,
) -> list[dict]:
    """Sun–Pluto + Chiron + ASC + MC için declination listesi (FLG_EQUATORIAL)."""
    items: list[dict] = []
    for planet_id, body_id, name, name_tr in PLANETS:
        try:
            values, _ = swe.calc_ut(
                jd_ut,
                planet_id,
                swe.FLG_SWIEPH | swe.FLG_SPEED | swe.FLG_EQUATORIAL,
            )
        except swe.Error:
            continue
        # FLG_EQUATORIAL dönüşü: [RA, declination, distance, RA_speed, decl_speed, dist_speed]
        items.append({
            "id": body_id,
            "name_tr": name_tr,
            "declination": round(float(values[1]), 6),
            "kind": "planet",
        })

    # ASC ve MC declination'ı (ekliptik enlemi 0 kabul ederek)
    eps_rad = math.radians(obliquity_deg)
    for label, lon in (
        ("ascendant", ascendant % 360.0),
        ("midheaven", midheaven % 360.0),
    ):
        lon_rad = math.radians(lon)
        sin_decl = math.sin(eps_rad) * math.sin(lon_rad)
        sin_decl = max(-1.0, min(1.0, sin_decl))
        decl = math.degrees(math.asin(sin_decl))
        items.append({
            "id": label,
            "name_tr": label,
            "declination": round(decl, 6),
            "kind": "angle",
        })
    return items


def _compute_declination_aspects(decl_items: list[dict]) -> dict:
    """Parallel, contraparallel ve out-of-bounds tespiti."""
    parallels: list[dict] = []
    contraparallels: list[dict] = []
    out_of_bounds: list[dict] = []

    for i, a in enumerate(decl_items):
        for b in decl_items[i + 1:]:
            same_sign = (a["declination"] >= 0) == (b["declination"] >= 0)
            abs_diff = abs(abs(a["declination"]) - abs(b["declination"]))
            if same_sign and abs_diff <= DECLINATION_ORB:
                parallels.append({
                    "from": a["id"],
                    "to": b["id"],
                    "orb": round(abs(a["declination"] - b["declination"]), 4),
                    "decl_from": a["declination"],
                    "decl_to": b["declination"],
                })
            elif (not same_sign) and abs_diff <= DECLINATION_ORB:
                contraparallels.append({
                    "from": a["id"],
                    "to": b["id"],
                    "orb": round(abs_diff, 4),
                    "decl_from": a["declination"],
                    "decl_to": b["declination"],
                })

    for item in decl_items:
        if abs(item["declination"]) > OOB_DECLINATION_THRESHOLD:
            out_of_bounds.append({
                "id": item["id"],
                "declination": item["declination"],
                "direction": "north" if item["declination"] > 0 else "south",
                "excess_degrees": round(
                    abs(item["declination"]) - OOB_DECLINATION_THRESHOLD, 4,
                ),
            })

    parallels.sort(key=lambda r: r["orb"])
    contraparallels.sort(key=lambda r: r["orb"])

    return {
        "status": "available",
        "orb": DECLINATION_ORB,
        "oob_threshold": OOB_DECLINATION_THRESHOLD,
        "parallels": parallels,
        "contraparallels": contraparallels,
        "out_of_bounds": out_of_bounds,
        "items": [
            {
                "id": item["id"],
                "name_tr": item.get("name_tr"),
                "declination": item["declination"],
                "kind": item["kind"],
            }
            for item in decl_items
        ],
    }


JONES_SHAPES_TR = {
    "bundle": "Demet",
    "bowl": "Kâse",
    "bucket": "Kova",
    "locomotive": "Lokomotif",
    "see_saw": "Tahterevalli",
    "splash": "Sıçrama",
    "splay": "Yayma",
}


def _classify_chart_shape(planet_rows: list[dict]) -> dict:
    """Jones chart shape tespiti (Bundle/Bowl/Bucket/Locomotive/See-saw/Splash/Splay)."""
    selected = [
        (planet["id"], planet["longitude"])
        for planet in planet_rows
        if planet["id"] in JONES_PLANETS and planet.get("longitude") is not None
    ]
    if len(selected) < 7:
        return {
            "status": "limited",
            "reason": "insufficient_planets_for_jones_shape",
            "shape": None,
            "shape_tr": None,
            "planet_count": len(selected),
        }

    # Boylama göre sırala (id ile birlikte tut)
    selected.sort(key=lambda row: row[1])
    longitudes = [lon for _id, lon in selected]
    n = len(longitudes)

    # Ardışık circular gap'ler
    gaps = []
    for i in range(n):
        nxt = longitudes[(i + 1) % n]
        gap = (nxt - longitudes[i]) % 360.0
        gaps.append({
            "from_id": selected[i][0],
            "to_id": selected[(i + 1) % n][0],
            "gap": gap,
        })
    sorted_gaps = sorted(gaps, key=lambda g: g["gap"], reverse=True)
    largest_gap = sorted_gaps[0]
    second_gap = sorted_gaps[1]["gap"] if len(sorted_gaps) > 1 else 0.0
    span = 360.0 - largest_gap["gap"]

    shape = "splay"
    rationale = ""
    if span <= 120.0:
        shape = "bundle"
        rationale = f"Tüm gezegenler 120° yay içinde toplandı (yayılım {span:.1f}°)."
    elif span <= 180.0:
        shape = "bowl"
        rationale = f"Tüm gezegenler 180° yay içinde toplandı (yayılım {span:.1f}°)."
    elif span <= 240.0 and largest_gap["gap"] >= 120.0:
        shape = "locomotive"
        rationale = (
            f"Yayılım {span:.1f}°; en büyük boşluk {largest_gap['gap']:.1f}°."
        )
    elif second_gap >= 60.0 and largest_gap["gap"] >= 60.0 and (largest_gap["gap"] + second_gap) >= 180.0:
        shape = "see_saw"
        rationale = (
            f"İki büyük boşluk: {largest_gap['gap']:.1f}° ve {second_gap:.1f}°."
        )
    elif largest_gap["gap"] < 60.0:
        shape = "splash"
        rationale = (
            f"En büyük boşluk {largest_gap['gap']:.1f}°; eşit yayılım."
        )
    else:
        shape = "splay"
        rationale = (
            f"Düzensiz dağılım; en büyük boşluk {largest_gap['gap']:.1f}°."
        )

    # Bucket kontrolü: 9 gezegen 180° yayda, 1 handle 90°+ uzakta
    if shape in ("bowl", "splay", "locomotive"):
        for i in range(n):
            others_sorted = sorted(
                longitudes[j] for j in range(n) if j != i
            )
            others_gaps = [
                (others_sorted[(k + 1) % len(others_sorted)] - others_sorted[k]) % 360.0
                for k in range(len(others_sorted))
            ]
            others_span = 360.0 - max(others_gaps)
            # i gezegeninin diğer kümeden uzaklığı: i'nin iki komşusu arasındaki en yakın mesafe
            handle_lon = longitudes[i]
            dist_to_others = min(
                (others_sorted[k + 1] - handle_lon if k + 1 < len(others_sorted) else (others_sorted[0] + 360.0 - handle_lon)) % 360.0
                for k in range(len(others_sorted))
            )
            dist_back = min(
                (handle_lon - others_sorted[k]) % 360.0
                for k in range(len(others_sorted))
            )
            min_dist = min(dist_to_others, dist_back)
            if min_dist >= 90.0 and others_span <= 180.0:
                shape = "bucket"
                rationale = (
                    f"{len(others_sorted)} gezegen 180° yayda; '{selected[i][0]}' "
                    f"handle olarak min {min_dist:.1f}° uzakta."
                )
                break

    return {
        "status": "available",
        "version": "1.0.0",
        "method": "jones_classic_thresholds",
        "shape": shape,
        "shape_tr": JONES_SHAPES_TR.get(shape, shape),
        "span_degrees": round(span, 4),
        "largest_gap_degrees": round(largest_gap["gap"], 4),
        "largest_gap_edge": {
            "from": largest_gap["from_id"],
            "to": largest_gap["to_id"],
        },
        "second_largest_gap_degrees": round(second_gap, 4),
        "planet_count": n,
        "rationale": rationale,
    }


def _pattern_aspect_index(core_chart: dict, planet_ids: set[str]) -> dict:
    index = {}
    for group in ("major", "minor"):
        for aspect in core_chart["aspects"].get(group, []):
            first = aspect["from"]
            second = aspect["to"]
            if first not in planet_ids or second not in planet_ids:
                continue
            index[frozenset((first, second))] = aspect
    return index


def _required_pattern_aspects(
    aspect_index: dict,
    requirements: list[tuple[str, str, str]],
) -> list[dict] | None:
    matches = []
    for first, second, aspect_type in requirements:
        aspect = aspect_index.get(frozenset((first, second)))
        if not aspect or aspect["type"] != aspect_type:
            return None
        matches.append(
            {
                "from": aspect["from"],
                "to": aspect["to"],
                "type": aspect["type"],
                "orb": aspect["orb"],
                "applying": aspect["applying"],
                "separating": aspect["separating"],
            }
        )
    return sorted(
        matches,
        key=lambda row: (row["type"], row["from"], row["to"]),
    )


def _conditional_pattern_aspects(
    core_chart: dict,
    requirements: list[tuple[str, str, str]],
    tolerance: float = 1.0,
) -> tuple[list[dict], list[dict]] | None:
    planets_by_id = {
        planet["id"]: planet
        for planet in core_chart["planets"]["items"]
        if "longitude" in planet
    }
    orb_policy = core_chart["aspects"].get("orb_policy", {})
    orbs = orb_policy.get("orbs", {})
    luminary_bonus = float(orb_policy.get("sun_moon_bonus", 0.0))
    aspect_angles = {
        aspect_type: exact_angle
        for aspect_type, exact_angle, _group, _nature in ASPECTS
    }

    rows = []
    conditional_edges = []
    for first, second, aspect_type in requirements:
        first_planet = planets_by_id.get(first)
        second_planet = planets_by_id.get(second)
        if not first_planet or not second_planet:
            return None
        if aspect_type not in orbs or aspect_type not in aspect_angles:
            return None

        exact_angle = aspect_angles[aspect_type]
        separation = _shortest_separation(
            first_planet["longitude"],
            second_planet["longitude"],
        )
        orb = abs(separation - exact_angle)
        allowed_orb = float(orbs[aspect_type])
        if first in {"sun", "moon"} or second in {"sun", "moon"}:
            allowed_orb += luminary_bonus
        excess = max(0.0, orb - allowed_orb)
        if excess > tolerance:
            return None

        future_separation = _shortest_separation(
            first_planet["longitude"]
            + float(first_planet.get("speed_longitude", 0.0)) / 1440.0,
            second_planet["longitude"]
            + float(second_planet.get("speed_longitude", 0.0)) / 1440.0,
        )
        future_orb = abs(future_separation - exact_angle)
        exact = orb <= 0.0001
        applying = None if exact else future_orb < orb
        row = {
            "from": first,
            "to": second,
            "type": aspect_type,
            "orb": round(orb, 8),
            "allowed_orb": round(allowed_orb, 8),
            "orb_excess": round(excess, 8),
            "within_standard_orb": excess == 0.0,
            "applying": applying,
            "separating": None if exact else not applying,
        }
        rows.append(row)
        if excess > 0.0:
            conditional_edges.append(row)

    if len(conditional_edges) != 1:
        return None
    return (
        sorted(rows, key=lambda row: (row["type"], row["from"], row["to"])),
        conditional_edges,
    )


def _pattern_match(
    pattern_type: str,
    name: str,
    planets: tuple[str, ...] | list[str],
    roles: dict,
    aspects: list[dict],
    rule: str,
    status: str = "available",
    conditional_edges: list[dict] | None = None,
) -> dict:
    sorted_planets = sorted(planets)
    match = {
        "id": f"{pattern_type}:{','.join(sorted_planets)}",
        "type": pattern_type,
        "name": name,
        "status": status,
        "planets": sorted_planets,
        "roles": roles,
        "aspects": aspects,
        "max_orb": round(max(row["orb"] for row in aspects), 8),
        "rule": rule,
    }
    if conditional_edges:
        match["conditional_edges"] = conditional_edges
        match["max_orb_excess"] = round(
            max(row["orb_excess"] for row in conditional_edges),
            8,
        )
        match["conditional_tolerance"] = 1.0
    return match


def _conditional_pattern_match(
    core_chart: dict,
    pattern_type: str,
    name: str,
    planets: tuple[str, ...] | list[str],
    roles: dict,
    requirements: list[tuple[str, str, str]],
    rule: str,
) -> dict | None:
    evaluated = _conditional_pattern_aspects(core_chart, requirements)
    if not evaluated:
        return None
    aspects, conditional_edges = evaluated
    return _pattern_match(
        pattern_type,
        name,
        planets,
        roles,
        aspects,
        rule,
        status="conditional",
        conditional_edges=conditional_edges,
    )


def _stellium_match(
    stellium_type: str,
    name: str,
    planets: list[str],
    roles: dict,
    rule: str,
    status: str = "available",
    aspects: list[dict] | None = None,
) -> dict:
    sorted_planets = sorted(planets)
    aspect_rows = aspects or []
    return {
        "id": f"{stellium_type}:{','.join(sorted_planets)}",
        "type": stellium_type,
        "name": name,
        "status": status,
        "planets": sorted_planets,
        "roles": roles,
        "aspects": aspect_rows,
        "max_orb": (
            round(max(row["orb"] for row in aspect_rows), 8)
            if aspect_rows
            else None
        ),
        "rule": rule,
    }


def _stellium_matches(
    core_chart: dict,
    planet_rows: list[dict],
    aspect_index: dict,
) -> tuple[list[dict], dict]:
    sign_groups = {}
    house_groups = {}
    for planet in planet_rows:
        if "sign_index" in planet:
            sign_groups.setdefault(planet["sign_index"], []).append(planet["id"])
        if "house" in planet:
            house_groups.setdefault(planet["house"], []).append(planet["id"])

    matches = []
    for sign_index, planets in sign_groups.items():
        if len(planets) < 3:
            continue
        sign, sign_tr = SIGNS[sign_index]
        matches.append(
            _stellium_match(
                "sign_stellium",
                "Sign Stellium",
                planets,
                {
                    "sign_index": sign_index,
                    "sign": sign,
                    "sign_tr": sign_tr,
                },
                "at_least_three_planets_in_the_same_tropical_sign",
            )
        )

    time_confidence = (
        core_chart.get("data_quality", {}).get("birth_time_confidence")
        or "unknown"
    )
    house_status = (
        "limited" if time_confidence in {"low", "unknown"} else "available"
    )
    for house, planets in house_groups.items():
        if len(planets) < 3:
            continue
        matches.append(
            _stellium_match(
                "house_stellium",
                "House Stellium",
                planets,
                {"house": house},
                "at_least_three_planets_in_the_same_house",
                status=house_status,
            )
        )

    adjacency = {planet["id"]: set() for planet in planet_rows}
    conjunction_edges = {}
    for pair, aspect in aspect_index.items():
        if aspect["type"] != "conjunction":
            continue
        first, second = sorted(pair)
        adjacency[first].add(second)
        adjacency[second].add(first)
        conjunction_edges[frozenset((first, second))] = aspect

    visited = set()
    for planet_id in sorted(adjacency):
        if planet_id in visited or not adjacency[planet_id]:
            continue
        stack = [planet_id]
        component = set()
        while stack:
            current = stack.pop()
            if current in component:
                continue
            component.add(current)
            stack.extend(adjacency[current] - component)
        visited.update(component)
        if len(component) < 3:
            continue

        aspect_rows = []
        for first, second in combinations(sorted(component), 2):
            aspect = conjunction_edges.get(frozenset((first, second)))
            if not aspect:
                continue
            aspect_rows.append(
                {
                    "from": aspect["from"],
                    "to": aspect["to"],
                    "type": aspect["type"],
                    "orb": aspect["orb"],
                    "applying": aspect["applying"],
                    "separating": aspect["separating"],
                }
            )
        aspect_rows.sort(key=lambda row: (row["orb"], row["from"], row["to"]))
        matches.append(
            _stellium_match(
                "conjunction_cluster",
                "Conjunction Cluster",
                list(component),
                {"connection": "conjunction_graph_component"},
                "at_least_three_planets_connected_in_one_conjunction_graph",
                aspects=aspect_rows,
            )
        )

    layer_status = {
        "sign_stellium": {
            "status": "available",
            "minimum_planets": 3,
        },
        "house_stellium": {
            "status": house_status,
            "minimum_planets": 3,
            "birth_time_confidence": time_confidence,
        },
        "conjunction_cluster": {
            "status": "available",
            "minimum_planets": 3,
            "connection_rule": "connected_component",
        },
    }
    return matches, layer_status


def calculate_aspect_patterns(core_chart: dict) -> dict:
    """Detect interpretation-free geometric patterns among Sun through Pluto."""

    planet_rows = core_chart["planets"]["items"]
    planet_ids = {row["id"] for row in planet_rows}
    aspect_index = _pattern_aspect_index(core_chart, planet_ids)
    matches = {}

    for trio in combinations(sorted(planet_ids), 3):
        first, second, third = trio
        pairings = [
            (first, second),
            (first, third),
            (second, third),
        ]

        grand_trine_requirements = [
            (left, right, "trine") for left, right in pairings
        ]
        grand_trine_aspects = _required_pattern_aspects(
            aspect_index,
            grand_trine_requirements,
        )
        if grand_trine_aspects:
            match = _pattern_match(
                "grand_trine",
                "Grand Trine",
                trio,
                {"triangle": list(trio)},
                grand_trine_aspects,
                "three_planets_connected_by_three_trines",
            )
            matches[match["id"]] = match
        else:
            match = _conditional_pattern_match(
                core_chart,
                "grand_trine",
                "Grand Trine",
                trio,
                {"triangle": list(trio)},
                grand_trine_requirements,
                "three_planets_connected_by_three_trines",
            )
            if match and match["id"] not in matches:
                matches[match["id"]] = match

        for opposition_pair in pairings:
            apex = next(planet for planet in trio if planet not in opposition_pair)
            t_square_requirements = [
                (*opposition_pair, "opposition"),
                (apex, opposition_pair[0], "square"),
                (apex, opposition_pair[1], "square"),
            ]
            t_square_aspects = _required_pattern_aspects(
                aspect_index,
                t_square_requirements,
            )
            if t_square_aspects:
                match = _pattern_match(
                    "t_square",
                    "T-Square",
                    trio,
                    {
                        "opposition": sorted(opposition_pair),
                        "apex": apex,
                    },
                    t_square_aspects,
                    "one_opposition_with_a_third_planet_square_to_both_ends",
                )
                matches[match["id"]] = match
            else:
                match = _conditional_pattern_match(
                    core_chart,
                    "t_square",
                    "T-Square",
                    trio,
                    {
                        "opposition": sorted(opposition_pair),
                        "apex": apex,
                    },
                    t_square_requirements,
                    "one_opposition_with_a_third_planet_square_to_both_ends",
                )
                if match and match["id"] not in matches:
                    matches[match["id"]] = match

        for sextile_pair in pairings:
            apex = next(planet for planet in trio if planet not in sextile_pair)
            yod_requirements = [
                (*sextile_pair, "sextile"),
                (apex, sextile_pair[0], "quincunx"),
                (apex, sextile_pair[1], "quincunx"),
            ]
            yod_aspects = _required_pattern_aspects(
                aspect_index,
                yod_requirements,
            )
            if yod_aspects:
                match = _pattern_match(
                    "yod",
                    "Yod",
                    trio,
                    {
                        "sextile_base": sorted(sextile_pair),
                        "apex": apex,
                    },
                    yod_aspects,
                    "one_sextile_with_a_third_planet_quincunx_to_both_ends",
                )
                matches[match["id"]] = match
            else:
                match = _conditional_pattern_match(
                    core_chart,
                    "yod",
                    "Yod",
                    trio,
                    {
                        "sextile_base": sorted(sextile_pair),
                        "apex": apex,
                    },
                    yod_requirements,
                    "one_sextile_with_a_third_planet_quincunx_to_both_ends",
                )
                if match and match["id"] not in matches:
                    matches[match["id"]] = match

    for quartet in combinations(sorted(planet_ids), 4):
        first, second, third, fourth = quartet
        opposition_pairings = [
            ((first, second), (third, fourth)),
            ((first, third), (second, fourth)),
            ((first, fourth), (second, third)),
        ]
        for opposition_a, opposition_b in opposition_pairings:
            square_pairs = [
                (left, right)
                for left in opposition_a
                for right in opposition_b
            ]
            grand_cross_requirements = [
                (*opposition_a, "opposition"),
                (*opposition_b, "opposition"),
                *((left, right, "square") for left, right in square_pairs),
            ]
            grand_cross_aspects = _required_pattern_aspects(
                aspect_index,
                grand_cross_requirements,
            )
            if grand_cross_aspects:
                match = _pattern_match(
                    "grand_cross",
                    "Grand Cross",
                    quartet,
                    {
                        "oppositions": [
                            sorted(opposition_a),
                            sorted(opposition_b),
                        ]
                    },
                    grand_cross_aspects,
                    "two_oppositions_with_all_four_cross_connections_square",
                )
                matches[match["id"]] = match
            else:
                match = _conditional_pattern_match(
                    core_chart,
                    "grand_cross",
                    "Grand Cross",
                    quartet,
                    {
                        "oppositions": [
                            sorted(opposition_a),
                            sorted(opposition_b),
                        ]
                    },
                    grand_cross_requirements,
                    "two_oppositions_with_all_four_cross_connections_square",
                )
                if match and match["id"] not in matches:
                    matches[match["id"]] = match

        for trine_planets in combinations(quartet, 3):
            fourth_planet = next(
                planet for planet in quartet if planet not in trine_planets
            )
            trine_pairs = list(combinations(trine_planets, 2))
            trine_aspects = _required_pattern_aspects(
                aspect_index,
                [(left, right, "trine") for left, right in trine_pairs],
            )
            for opposition_target in trine_planets:
                sextile_targets = [
                    planet
                    for planet in trine_planets
                    if planet != opposition_target
                ]
                kite_roles = {
                    "grand_trine": sorted(trine_planets),
                    "opposition_axis": sorted(
                        (fourth_planet, opposition_target)
                    ),
                    "tail": fourth_planet,
                }
                kite_requirements = [
                    *((left, right, "trine") for left, right in trine_pairs),
                    (fourth_planet, opposition_target, "opposition"),
                    (fourth_planet, sextile_targets[0], "sextile"),
                    (fourth_planet, sextile_targets[1], "sextile"),
                ]
                kite_aspects = _required_pattern_aspects(
                    aspect_index,
                    kite_requirements,
                )
                if kite_aspects:
                    match = _pattern_match(
                        "kite",
                        "Kite",
                        quartet,
                        kite_roles,
                        kite_aspects,
                        "grand_trine_plus_opposition_to_one_vertex_and_sextiles_to_two",
                    )
                    matches[match["id"]] = match
                else:
                    match = _conditional_pattern_match(
                        core_chart,
                        "kite",
                        "Kite",
                        quartet,
                        kite_roles,
                        kite_requirements,
                        "grand_trine_plus_opposition_to_one_vertex_and_sextiles_to_two",
                    )
                    if match and match["id"] not in matches:
                        matches[match["id"]] = match

    stellium_matches, stellium_layers = _stellium_matches(
        core_chart,
        planet_rows,
        aspect_index,
    )
    for match in stellium_matches:
        matches[match["id"]] = match

    ordered_matches = sorted(
        matches.values(),
        key=lambda row: (row["type"], row["planets"]),
    )
    chart_shape = _classify_chart_shape(planet_rows)
    return {
        "status": "available",
        "version": "1.3.0",
        "rule_profile": "geometric_patterns_v1",
        "conditional_policy": {
            "profile": "single_edge_orb_extension_v1",
            "maximum_outside_edges": 1,
            "maximum_orb_excess": 1.0,
            "exact_patterns_remain_unchanged": True,
        },
        "aspect_source": "core_chart.aspects",
        "orb_policy": core_chart["aspects"].get("orb_policy", {}),
        "bodies_included": sorted(planet_ids),
        "bodies_excluded": ["north_node", "south_node"],
        "supported_patterns": [
            "grand_trine",
            "t_square",
            "grand_cross",
            "yod",
            "kite",
            "sign_stellium",
            "house_stellium",
            "conjunction_cluster",
        ],
        "stellium_layers": stellium_layers,
        "matches": ordered_matches,
        "chart_shape": chart_shape,
        "limitations": [],
    }


def _ascendant_sensitivity(
    jd_ut: float,
    latitude: float,
    longitude: float,
    house_system: str,
    ascendant: float,
) -> dict:
    minute_in_days = 1.0 / 1440.0
    try:
        _, before = _calculate_houses(
            jd_ut - minute_in_days,
            latitude,
            longitude,
            house_system,
        )
        _, after = _calculate_houses(
            jd_ut + minute_in_days,
            latitude,
            longitude,
            house_system,
        )
    except ChartCalculationError:
        return {
            "status": "limited",
            "method": "plus_minus_one_minute_perturbation",
            "reason": "perturbation_house_calculation_failed",
        }

    degrees_per_minute = abs(_signed_delta(after[0], before[0])) / 2.0
    degree_in_sign = ascendant % 30.0
    if degrees_per_minute <= 1e-12:
        previous_boundary = None
        next_boundary = None
    else:
        previous_boundary = degree_in_sign / degrees_per_minute
        next_boundary = (30.0 - degree_in_sign) / degrees_per_minute

    return {
        "status": "available",
        "method": "plus_minus_one_minute_perturbation_linear_estimate",
        "longitude_change_degrees_per_minute": round(degrees_per_minute, 8),
        "estimated_minutes_to_previous_sign_boundary": (
            round(previous_boundary, 2) if previous_boundary is not None else None
        ),
        "estimated_minutes_to_next_sign_boundary": (
            round(next_boundary, 2) if next_boundary is not None else None
        ),
    }


def _validate_request(payload: dict) -> tuple[dict, dict, str, str]:
    if not isinstance(payload, dict):
        raise ChartInputError("JSON gövdesi nesne olmalıdır")
    birth = payload.get("birth")
    if not isinstance(birth, dict):
        raise ChartInputError("birth nesnesi zorunludur")
    options = payload.get("options") or {}
    if not isinstance(options, dict):
        raise ChartInputError("options nesne olmalıdır")

    latitude = _require_float(birth, "lat")
    longitude = _require_float(birth, "lon")
    if not -90.0 <= latitude <= 90.0:
        raise ChartInputError("birth.lat -90 ile +90 arasında olmalıdır")
    if not -180.0 <= longitude <= 180.0:
        raise ChartInputError("birth.lon -180 ile +180 arasında olmalıdır")

    zodiac = str(options.get("zodiac") or "tropical")
    if zodiac != "tropical":
        raise ChartInputError("İlk sürüm yalnız options.zodiac=tropical destekler")

    house_system = options.get("house_system")
    if not house_system:
        raise ChartInputError("options.house_system zorunludur")
    house_system = str(house_system)
    if house_system not in HOUSE_SYSTEMS:
        raise ChartInputError(
            "Desteklenmeyen options.house_system. "
            "Desteklenen: placidus, regiomontanus, whole_sign"
        )

    node_type = str(options.get("node_type") or "true")
    if node_type not in NODE_TYPES:
        raise ChartInputError("options.node_type true veya mean olmalıdır")

    return birth, options, house_system, node_type


def _rulership_rows(rulers: dict[int, str]) -> list[dict]:
    return [
        {
            "sign_index": sign_index,
            "sign": SIGNS[sign_index][0],
            "sign_tr": SIGNS[sign_index][1],
            "ruler": rulers[sign_index],
        }
        for sign_index in range(12)
    ]


def _house_ruler_rows(
    houses: list[dict],
    classical_planets: dict[str, dict],
    modern_planets: dict[str, dict],
    time_status: str,
) -> list[dict]:
    rows = []
    for house in houses:
        classical_ruler = CLASSICAL_RULERS[house["sign_index"]]
        modern_ruler = MODERN_RULERS[house["sign_index"]]
        rows.append({
            "house": house["house"],
            "cusp_sign_index": house["sign_index"],
            "cusp_sign": house["sign"],
            "cusp_sign_tr": house["sign_tr"],
            "status": time_status,
            "classical": {
                "ruler": classical_ruler,
                "ruler_house": classical_planets[classical_ruler]["house"],
                "ruler_sign_index": classical_planets[classical_ruler]["sign_index"],
                "ruler_sign": classical_planets[classical_ruler]["sign"],
                "ruler_sign_tr": classical_planets[classical_ruler]["sign_tr"],
            },
            "modern": {
                "ruler": modern_ruler,
                "ruler_house": modern_planets[modern_ruler]["house"],
                "ruler_sign_index": modern_planets[modern_ruler]["sign_index"],
                "ruler_sign": modern_planets[modern_ruler]["sign"],
                "ruler_sign_tr": modern_planets[modern_ruler]["sign_tr"],
            },
        })
    return rows


def _dispositor_chain(
    start_planet: str,
    planets_by_id: dict[str, dict],
    rulers: dict[int, str],
) -> dict:
    path = []
    current = start_planet

    for _ in range(16):
        if current in path:
            cycle_start = path.index(current)
            return {
                "planet": start_planet,
                "path": path,
                "termination": "cycle",
                "cycle": path[cycle_start:],
                "final_dispositor": None,
            }

        path.append(current)
        current_row = planets_by_id[current]
        next_planet = rulers[current_row["sign_index"]]
        if next_planet == current:
            return {
                "planet": start_planet,
                "path": path,
                "termination": "final_dispositor",
                "cycle": [],
                "final_dispositor": current,
            }
        current = next_planet

    return {
        "planet": start_planet,
        "path": path,
        "termination": "depth_limit",
        "cycle": [],
        "final_dispositor": None,
    }


def _dispositor_profile(
    planets: list[dict],
    rulers: dict[int, str],
    profile: str,
) -> dict:
    planets_by_id = {planet["id"]: planet for planet in planets}
    chains = [
        _dispositor_chain(planet["id"], planets_by_id, rulers)
        for planet in planets
    ]
    final_dispositors = sorted({
        chain["final_dispositor"]
        for chain in chains
        if chain["final_dispositor"]
    })
    cycles = []
    seen_cycles = set()
    for chain in chains:
        if not chain["cycle"]:
            continue
        normalized = tuple(sorted(chain["cycle"]))
        if normalized not in seen_cycles:
            seen_cycles.add(normalized)
            cycles.append(chain["cycle"])

    return {
        "status": "available",
        "profile": profile,
        "chains": chains,
        "final_dispositors": final_dispositors,
        "cycles": cycles,
    }


def _term_lord(sign_index: int, degree: float) -> tuple[str, float, float]:
    """Pozisyon için Egyptian bounds (term) lord ve aralığını döner."""
    deg = degree % 30.0
    for start, end, planet in EGYPTIAN_BOUNDS[sign_index]:
        if start <= deg < end:
            return planet, float(start), float(end)
    last = EGYPTIAN_BOUNDS[sign_index][-1]
    return last[2], float(last[0]), float(last[1])


def _face_lord(sign_index: int, degree: float) -> tuple[str, float, float]:
    """Pozisyon için Chaldean face/decan lord ve aralığını döner."""
    deg = degree % 30.0
    if deg < 10.0:
        return CHALDEAN_FACES[sign_index][0], 0.0, 10.0
    if deg < 20.0:
        return CHALDEAN_FACES[sign_index][1], 10.0, 20.0
    return CHALDEAN_FACES[sign_index][2], 20.0, 30.0


def _triplicity_for_sign(sign_index: int) -> dict:
    """Bir burç için (Dorothean) triplicity lord triolisi."""
    return TRIPLICITY_RULERS[SIGN_ELEMENTS[sign_index]]


def _essential_dignities(planets: list[dict], chart_sect: str) -> dict:
    rows = []
    for planet in planets:
        planet_id = planet["id"]
        if planet_id not in CLASSICAL_PLANETS:
            rows.append({
                "planet": planet_id,
                "status": "not_applicable",
                "reason": "classical_dignity_limited_to_seven_visible_planets",
                "conditions": [],
            })
            continue

        sign_index = planet["sign_index"]
        degree_in_sign = float(planet["degree"])
        conditions = []
        domiciles = CLASSICAL_DOMICILES[planet_id]
        detriments = {(sign + 6) % 12 for sign in domiciles}
        exaltation = CLASSICAL_EXALTATIONS[planet_id]
        fall = (exaltation + 6) % 12

        if sign_index in domiciles:
            conditions.append("domicile")
        if sign_index == exaltation:
            conditions.append("exaltation")
        if sign_index in detriments:
            conditions.append("detriment")
        if sign_index == fall:
            conditions.append("fall")

        triplicity = _triplicity_for_sign(sign_index)
        active_role = "diurnal" if chart_sect == "diurnal" else "nocturnal"
        active_lord = triplicity[active_role]
        is_active_triplicity_lord = active_lord == planet_id
        is_out_of_sect_triplicity_lord = (
            (triplicity["diurnal"] == planet_id or triplicity["nocturnal"] == planet_id)
            and not is_active_triplicity_lord
        )
        is_participating_lord = triplicity["participating"] == planet_id
        if is_active_triplicity_lord:
            conditions.append("triplicity_in_sect")
        elif is_out_of_sect_triplicity_lord:
            conditions.append("triplicity_out_of_sect")
        if is_participating_lord:
            conditions.append("triplicity_participating")

        term_planet, term_start, term_end = _term_lord(sign_index, degree_in_sign)
        if term_planet == planet_id:
            conditions.append("term")

        face_planet, face_start, face_end = _face_lord(sign_index, degree_in_sign)
        if face_planet == planet_id:
            conditions.append("face")

        rows.append({
            "planet": planet_id,
            "status": "available",
            "sign_index": sign_index,
            "sign": planet["sign"],
            "sign_tr": planet["sign_tr"],
            "degree_in_sign": round(degree_in_sign, 4),
            "conditions": conditions or ["none"],
            "triplicity": {
                "element": SIGN_ELEMENTS[sign_index],
                "diurnal_lord": triplicity["diurnal"],
                "nocturnal_lord": triplicity["nocturnal"],
                "participating_lord": triplicity["participating"],
                "active_lord": active_lord,
                "chart_sect": chart_sect,
                "system": "dorothean",
            },
            "term": {
                "lord": term_planet,
                "range": [term_start, term_end],
                "system": "egyptian",
            },
            "face": {
                "lord": face_planet,
                "range": [face_start, face_end],
                "system": "chaldean",
            },
        })

    return {
        "status": "available",
        "system": "classical_seven_planets_with_five_dignities",
        "included_dignities": [
            "domicile", "exaltation", "triplicity", "term", "face",
            "detriment", "fall",
        ],
        "triplicity_system": "dorothean",
        "bounds_system": "egyptian",
        "faces_system": "chaldean",
        "chart_sect": chart_sect,
        "scoring": "not_applied",
        "items": rows,
    }


def _sect_data(planets: list[dict], time_status: str) -> dict:
    planets_by_id = {planet["id"]: planet for planet in planets}
    sun = planets_by_id["sun"]
    mercury = planets_by_id["mercury"]
    chart_sect = "diurnal" if sun["house"] in {7, 8, 9, 10, 11, 12} else "nocturnal"
    mercury_delta = _signed_delta(mercury["longitude"], sun["longitude"])
    mercury_phase = "oriental" if mercury_delta < 0 else "occidental"
    mercury_affiliation = "diurnal" if mercury_phase == "oriental" else "nocturnal"

    rows = []
    for planet in planets:
        planet_id = planet["id"]
        if planet_id in DIURNAL_SECT_PLANETS:
            affiliation = "diurnal"
        elif planet_id in NOCTURNAL_SECT_PLANETS:
            affiliation = "nocturnal"
        elif planet_id == "mercury":
            affiliation = mercury_affiliation
        else:
            rows.append({
                "planet": planet_id,
                "status": "not_applicable",
                "reason": "outer_planet_has_no_classical_sect_assignment",
            })
            continue

        row = {
            "planet": planet_id,
            "status": time_status,
            "sect_affiliation": affiliation,
            "in_sect": affiliation == chart_sect,
        }
        if planet_id == "mercury":
            row["phase_relative_to_sun"] = mercury_phase
            row["method"] = "signed_ecliptic_longitude_relative_to_sun"
        rows.append(row)

    return {
        "status": time_status,
        "chart_sect": chart_sect,
        "sun_above_horizon": chart_sect == "diurnal",
        "method": "sun_house_7_to_12_is_above_horizon",
        "items": rows,
    }


DIGNITY_STRENGTH_RANK = {
    "domicile": 5,
    "exaltation": 4,
    "triplicity": 3,
    "triplicity_participating": 2,
    "term": 1,
    "face": 0,
}


def _dignity_hosts(sign_index: int, degree: float, chart_sect: str) -> list[dict]:
    """Bir konumdaki gezegeni hangi gezegenlerin hangi dignity ile ağırladığı."""
    hosts = [{
        "planet": CLASSICAL_RULERS[sign_index],
        "dignity": "domicile",
    }]
    for planet, exaltation_sign in CLASSICAL_EXALTATIONS.items():
        if exaltation_sign == sign_index:
            hosts.append({
                "planet": planet,
                "dignity": "exaltation",
            })
    triplicity = _triplicity_for_sign(sign_index)
    active_role = "diurnal" if chart_sect == "diurnal" else "nocturnal"
    hosts.append({
        "planet": triplicity[active_role],
        "dignity": "triplicity",
    })
    hosts.append({
        "planet": triplicity["participating"],
        "dignity": "triplicity_participating",
    })
    term_planet, _, _ = _term_lord(sign_index, degree)
    hosts.append({
        "planet": term_planet,
        "dignity": "term",
    })
    face_planet, _, _ = _face_lord(sign_index, degree)
    hosts.append({
        "planet": face_planet,
        "dignity": "face",
    })
    return hosts


def _mutual_receptions(planets: list[dict], chart_sect: str) -> dict:
    classical = [
        planet for planet in planets
        if planet["id"] in CLASSICAL_PLANETS
    ]
    matches = []
    for index, first in enumerate(classical):
        for second in classical[index + 1:]:
            first_hosted = [
                host["dignity"]
                for host in _dignity_hosts(
                    first["sign_index"], float(first["degree"]), chart_sect,
                )
                if host["planet"] == second["id"]
            ]
            second_hosted = [
                host["dignity"]
                for host in _dignity_hosts(
                    second["sign_index"], float(second["degree"]), chart_sect,
                )
                if host["planet"] == first["id"]
            ]
            if first_hosted and second_hosted:
                first_max = max(
                    DIGNITY_STRENGTH_RANK.get(d, 0) for d in first_hosted
                )
                second_max = max(
                    DIGNITY_STRENGTH_RANK.get(d, 0) for d in second_hosted
                )
                strength_score = min(first_max, second_max)
                shared_levels = sorted(
                    set(first_hosted) & set(second_hosted),
                    key=lambda d: -DIGNITY_STRENGTH_RANK.get(d, -1),
                )
                matches.append({
                    "planets": [first["id"], second["id"]],
                    "first_in_second_dignities": first_hosted,
                    "second_in_first_dignities": second_hosted,
                    "shared_levels": shared_levels,
                    "reception_type": "mutual",
                    "strength_score": strength_score,
                })

    matches.sort(key=lambda m: (-m["strength_score"], m["planets"]))
    return {
        "status": "available",
        "included_dignities": [
            "domicile", "exaltation", "triplicity",
            "triplicity_participating", "term", "face",
        ],
        "chart_sect": chart_sect,
        "strength_ranking": DIGNITY_STRENGTH_RANK,
        "items": matches,
    }


def _dominant_keys(counts: dict[str, int]) -> list[str]:
    maximum = max(counts.values())
    if maximum == 0:
        return []
    return sorted(key for key, value in counts.items() if value == maximum)


def _distribution_data(planets: list[dict], time_status: str) -> dict:
    elements = {"fire": 0, "earth": 0, "air": 0, "water": 0}
    modalities = {"cardinal": 0, "fixed": 0, "mutable": 0}
    polarities = {"positive": 0, "negative": 0}
    hemispheres = {
        "eastern": 0,
        "western": 0,
        "above_horizon": 0,
        "below_horizon": 0,
    }
    quadrants = {"first": 0, "second": 0, "third": 0, "fourth": 0}
    house_modes = {"angular": 0, "succedent": 0, "cadent": 0}

    for planet in planets:
        sign_index = planet["sign_index"]
        house = planet["house"]
        elements[SIGN_ELEMENTS[sign_index]] += 1
        modalities[SIGN_MODALITIES[sign_index]] += 1
        polarities[SIGN_POLARITIES[sign_index]] += 1
        hemispheres["eastern" if house in {10, 11, 12, 1, 2, 3} else "western"] += 1
        hemispheres["above_horizon" if house >= 7 else "below_horizon"] += 1

        if house <= 3:
            quadrants["first"] += 1
        elif house <= 6:
            quadrants["second"] += 1
        elif house <= 9:
            quadrants["third"] += 1
        else:
            quadrants["fourth"] += 1

        if house in {1, 4, 7, 10}:
            house_modes["angular"] += 1
        elif house in {2, 5, 8, 11}:
            house_modes["succedent"] += 1
        else:
            house_modes["cadent"] += 1

    return {
        "status": "available",
        "bodies_included": [planet["id"] for planet in planets],
        "weighting": "one_body_one_count",
        "sign_based": {
            "status": "available",
            "elements": elements,
            "dominant_elements": _dominant_keys(elements),
            "modalities": modalities,
            "dominant_modalities": _dominant_keys(modalities),
            "polarities": polarities,
            "dominant_polarities": _dominant_keys(polarities),
        },
        "house_based": {
            "status": time_status,
            "hemispheres": hemispheres,
            "quadrants": quadrants,
            "house_modes": house_modes,
        },
    }


def _accidental_conditions(planets: list[dict], time_status: str) -> dict:
    rows = []
    for planet in planets:
        house = planet["house"]
        if house in {1, 4, 7, 10}:
            angularity = "angular"
        elif house in {2, 5, 8, 11}:
            angularity = "succedent"
        else:
            angularity = "cadent"
        rows.append({
            "planet": planet["id"],
            "status": time_status,
            "house": house,
            "angularity": angularity,
            "hemisphere_east_west": (
                "eastern" if house in {10, 11, 12, 1, 2, 3} else "western"
            ),
            "hemisphere_horizon": "above" if house >= 7 else "below",
            "retrograde": planet["retrograde"],
        })
    return {
        "status": time_status,
        "scoring": "not_applied",
        "items": rows,
    }


def calculate_natal_derivatives(core_chart: dict) -> dict:
    """Build interpretation-free natal derivative data from a core chart."""

    planets = core_chart["planets"]["items"]
    planets_by_id = {planet["id"]: planet for planet in planets}
    time_confidence = core_chart["data_quality"]["birth_time_confidence"]
    time_status = "limited" if time_confidence in {"low", "unknown"} else "available"

    sun = planets_by_id["sun"]
    chart_sect = (
        "diurnal" if sun["house"] in {7, 8, 9, 10, 11, 12} else "nocturnal"
    )

    return {
        "status": time_status,
        "version": "1.1.0",
        "rulerships": {
            "status": "available",
            "classical": {
                "profile": "classical_seven_planet",
                "signs": _rulership_rows(CLASSICAL_RULERS),
            },
            "modern": {
                "profile": "modern_outer_planet_primary",
                "signs": _rulership_rows(MODERN_RULERS),
            },
        },
        "house_rulers": {
            "status": time_status,
            "house_system": core_chart["meta"]["house_system"],
            "items": _house_ruler_rows(
                core_chart["houses"]["items"],
                planets_by_id,
                planets_by_id,
                time_status,
            ),
        },
        "dispositor_chains": {
            "status": "available",
            "classical": _dispositor_profile(
                planets,
                CLASSICAL_RULERS,
                "classical_seven_planet",
            ),
            "modern": _dispositor_profile(
                planets,
                MODERN_RULERS,
                "modern_outer_planet_primary",
            ),
        },
        "essential_dignities": _essential_dignities(planets, chart_sect),
        "sect": _sect_data(planets, time_status),
        "receptions": _mutual_receptions(planets, chart_sect),
        "distributions": _distribution_data(planets, time_status),
        "accidental_conditions": _accidental_conditions(planets, time_status),
        "limitations": (
            [
                "House-based derivatives are limited because birth time confidence "
                f"is {time_confidence}."
            ]
            if time_status == "limited"
            else []
        ),
    }


def _advanced_point(
    point_id: str,
    name: str,
    name_tr: str,
    longitude: float,
    cusps: list[float],
    time_status: str,
    method: str,
    **extra,
) -> dict:
    return {
        "id": point_id,
        "name": name,
        "name_tr": name_tr,
        "status": time_status,
        **_degree_fields(longitude),
        "house": _house_number(longitude, cusps),
        "house_status": time_status,
        "method": method,
        **extra,
    }


def calculate_advanced_natal(payload: dict, core_chart: dict | None = None) -> dict:
    """Calculate interpretation-free advanced natal points."""

    chart = core_chart or calculate_core_chart(payload)
    utc_dt = datetime.fromisoformat(
        chart["birth"]["utc_datetime"].replace("Z", "+00:00")
    )
    jd_ut = _julian_day(utc_dt)
    latitude = float(chart["birth"]["latitude"])
    longitude_geo = float(chart["birth"]["longitude"])
    house_system = chart["meta"]["house_system"]
    cusps, ascmc = _calculate_houses(
        jd_ut,
        latitude,
        longitude_geo,
        house_system,
    )

    time_confidence = chart["data_quality"]["birth_time_confidence"]
    time_status = "limited" if time_confidence in {"low", "unknown"} else "available"
    planets_by_id = {
        planet["id"]: planet
        for planet in chart["planets"]["items"]
    }
    ascendant = chart["angles"]["ascendant"]["longitude"]
    sun = planets_by_id["sun"]
    moon = planets_by_id["moon"]
    chart_sect = (
        "diurnal"
        if sun["house"] in {7, 8, 9, 10, 11, 12}
        else "nocturnal"
    )
    venus = planets_by_id["venus"]
    mercury = planets_by_id["mercury"]
    mars = planets_by_id["mars"]
    jupiter = planets_by_id["jupiter"]
    saturn = planets_by_id["saturn"]
    if chart_sect == "diurnal":
        fortune_longitude = ascendant + moon["longitude"] - sun["longitude"]
        fortune_formula = "ascendant_plus_moon_minus_sun"
        spirit_longitude = ascendant + sun["longitude"] - moon["longitude"]
        spirit_formula = "ascendant_plus_sun_minus_moon"
        eros_longitude = ascendant + venus["longitude"] - spirit_longitude
        eros_formula = "ascendant_plus_venus_minus_spirit"
        necessity_longitude = ascendant + fortune_longitude - mercury["longitude"]
        necessity_formula = "ascendant_plus_fortune_minus_mercury"
        courage_longitude = ascendant + mars["longitude"] - fortune_longitude
        courage_formula = "ascendant_plus_mars_minus_fortune"
        victory_longitude = ascendant + jupiter["longitude"] - spirit_longitude
        victory_formula = "ascendant_plus_jupiter_minus_spirit"
        nemesis_longitude = ascendant + fortune_longitude - saturn["longitude"]
        nemesis_formula = "ascendant_plus_fortune_minus_saturn"
    else:
        fortune_longitude = ascendant + sun["longitude"] - moon["longitude"]
        fortune_formula = "ascendant_plus_sun_minus_moon"
        spirit_longitude = ascendant + moon["longitude"] - sun["longitude"]
        spirit_formula = "ascendant_plus_moon_minus_sun"
        eros_longitude = ascendant + spirit_longitude - venus["longitude"]
        eros_formula = "ascendant_plus_spirit_minus_venus"
        necessity_longitude = ascendant + mercury["longitude"] - fortune_longitude
        necessity_formula = "ascendant_plus_mercury_minus_fortune"
        courage_longitude = ascendant + fortune_longitude - mars["longitude"]
        courage_formula = "ascendant_plus_fortune_minus_mars"
        victory_longitude = ascendant + spirit_longitude - jupiter["longitude"]
        victory_formula = "ascendant_plus_spirit_minus_jupiter"
        nemesis_longitude = ascendant + saturn["longitude"] - fortune_longitude
        nemesis_formula = "ascendant_plus_saturn_minus_fortune"

    vertex_longitude = float(ascmc[3]) % 360.0
    east_point_longitude = float(ascmc[4]) % 360.0
    points = [
        _advanced_point(
            "vertex",
            "Vertex",
            "Vertex",
            vertex_longitude,
            cusps,
            time_status,
            "swiss_ephemeris_ascmc_vertex",
        ),
        _advanced_point(
            "anti_vertex",
            "Anti-Vertex",
            "Anti-Vertex",
            vertex_longitude + 180.0,
            cusps,
            time_status,
            "vertex_plus_180_degrees",
            derived_from="vertex",
        ),
        _advanced_point(
            "east_point",
            "East Point",
            "Doğu Noktası",
            east_point_longitude,
            cusps,
            time_status,
            "swiss_ephemeris_ascmc_equatorial_ascendant",
        ),
        _advanced_point(
            "west_point",
            "West Point",
            "Batı Noktası",
            east_point_longitude + 180.0,
            cusps,
            time_status,
            "east_point_plus_180_degrees",
            derived_from="east_point",
        ),
        _advanced_point(
            "part_of_fortune",
            "Part of Fortune",
            "Pars Fortuna",
            fortune_longitude,
            cusps,
            time_status,
            fortune_formula,
            chart_sect=chart_sect,
            sect_method="sun_house_7_to_12_is_above_horizon",
            lot_family="hermetic",
        ),
    ]

    # Diger 6 Hermetic Lot (Brennan / Hellenistic Astrology kaynagi)
    hermetic_lots = [
        ("part_of_spirit", "Part of Spirit", "Pars Spirit (Daimon)",
         spirit_longitude, spirit_formula),
        ("part_of_eros", "Part of Eros", "Pars Eros",
         eros_longitude, eros_formula),
        ("part_of_necessity", "Part of Necessity", "Pars Necessity (Ananke)",
         necessity_longitude, necessity_formula),
        ("part_of_courage", "Part of Courage", "Pars Courage (Tolma)",
         courage_longitude, courage_formula),
        ("part_of_victory", "Part of Victory", "Pars Victory (Nike)",
         victory_longitude, victory_formula),
        ("part_of_nemesis", "Part of Nemesis", "Pars Nemesis",
         nemesis_longitude, nemesis_formula),
    ]
    for lot_id, name, name_tr, longitude_value, formula in hermetic_lots:
        points.append(_advanced_point(
            lot_id, name, name_tr, longitude_value, cusps, time_status, formula,
            chart_sect=chart_sect,
            sect_method="sun_house_7_to_12_is_above_horizon",
            lot_family="hermetic",
        ))

    ephemeris_sources = set()
    for planet_id, point_id, name, name_tr, method in (
        (
            swe.MEAN_APOG,
            "mean_black_moon_lilith",
            "Mean Black Moon Lilith",
            "Ortalama Kara Ay Lilith",
            "swiss_ephemeris_mean_lunar_apogee",
        ),
        (
            swe.OSCU_APOG,
            "osculating_black_moon_lilith",
            "Osculating Black Moon Lilith",
            "Salınımlı Kara Ay Lilith",
            "swiss_ephemeris_osculating_lunar_apogee",
        ),
    ):
        row, source = _body_position(
            jd_ut,
            planet_id,
            point_id,
            name,
            name_tr,
            cusps,
        )
        row.update(
            {
                "status": time_status,
                "house_status": time_status,
                "longitude_status": "available",
                "method": method,
            }
        )
        points.append(row)
        ephemeris_sources.add(source)

    return {
        "status": time_status,
        "version": "1.0.0",
        "house_system": house_system,
        "points": points,
        "ephemeris_sources": sorted(ephemeris_sources),
        "excluded": [
            {
                "key": "main_asteroids",
                "status": "not_available",
                "reason": "required_swiss_ephemeris_asteroid_file_not_installed",
                "missing_items": ["ceres", "pallas", "juno", "vesta"],
            },
            {
                "key": "fixed_stars_and_other_arabic_parts",
                "status": "not_available",
                "reason": "outside_advanced_natal_v1_scope",
            },
        ],
        "limitations": (
            [
                "Time-sensitive points and house placements are limited because "
                f"birth time confidence is {time_confidence}."
            ]
            if time_status == "limited"
            else []
        ),
    }


def calculate_house_system_comparison(
    payload: dict,
    selected_chart: dict | None = None,
) -> dict:
    """Compare Sun-through-Pluto house placements in Placidus and Whole Sign."""

    charts = {}
    unavailable = {}
    if selected_chart:
        selected_system = selected_chart["meta"]["house_system"]
        charts[selected_system] = selected_chart

    for house_system in ("placidus", "whole_sign"):
        if house_system in charts:
            continue
        comparison_payload = {
            **payload,
            "birth": dict(payload.get("birth") or {}),
            "person": dict(payload.get("person") or {}),
            "options": {
                **(payload.get("options") or {}),
                "house_system": house_system,
            },
        }
        try:
            charts[house_system] = calculate_core_chart(comparison_payload)
        except ChartCalculationError as exc:
            if exc.code != "house_system_unavailable":
                raise
            unavailable[house_system] = {
                "status": "not_available",
                "reason": exc.code,
                "message": str(exc),
            }

    available_chart = next(iter(charts.values()))
    planet_ids = [row["id"] for row in available_chart["planets"]["items"]]
    planets_by_system = {
        house_system: {
            row["id"]: row
            for row in chart["planets"]["items"]
        }
        for house_system, chart in charts.items()
    }

    rows = []
    for planet_id in planet_ids:
        placidus = planets_by_system.get("placidus", {}).get(planet_id)
        whole_sign = planets_by_system.get("whole_sign", {}).get(planet_id)
        placidus_house = placidus["house"] if placidus else None
        whole_sign_house = whole_sign["house"] if whole_sign else None
        changed = (
            placidus_house != whole_sign_house
            if placidus_house is not None and whole_sign_house is not None
            else None
        )
        source = placidus or whole_sign
        rows.append(
            {
                "planet": planet_id,
                "name": source["name"],
                "name_tr": source["name_tr"],
                "placidus_house": placidus_house,
                "whole_sign_house": whole_sign_house,
                "changed": changed,
            }
        )

    systems = {}
    for house_system in ("placidus", "whole_sign"):
        if house_system in charts:
            systems[house_system] = {
                "status": "available",
                "house_system": house_system,
            }
        else:
            systems[house_system] = unavailable[house_system]

    comparable_rows = [row for row in rows if row["changed"] is not None]
    changed_count = sum(row["changed"] for row in comparable_rows)
    return {
        "status": "available" if len(charts) == 2 else "limited",
        "version": "1.0.0",
        "comparison_profile": "placidus_vs_whole_sign_planet_houses_v1",
        "scope": "sun_through_pluto_planet_house_placements",
        "systems": systems,
        "items": rows,
        "summary": {
            "planet_count": len(rows),
            "comparable_count": len(comparable_rows),
            "changed_count": changed_count,
            "unchanged_count": len(comparable_rows) - changed_count,
        },
        "limitations": [
            "This version compares planet house numbers only.",
            "House rulers, house stelliums and interpretive judgments are not compared.",
        ],
    }


def calculate_core_chart(payload: dict) -> dict:
    """Calculate the first, interpretation-free Western natal package."""

    birth_input, options, house_system, node_type = _validate_request(payload)
    local_dt, tz_offset, timezone_id, warnings = _resolve_local_datetime(birth_input)
    utc_dt = local_dt.astimezone(timezone.utc)
    jd_ut = _julian_day(utc_dt)
    latitude = float(birth_input["lat"])
    longitude_geo = float(birth_input["lon"])

    cusps, ascmc = _calculate_houses(
        jd_ut,
        latitude,
        longitude_geo,
        house_system,
    )
    ascendant = float(ascmc[0]) % 360.0
    midheaven = float(ascmc[1]) % 360.0

    planet_rows = []
    ephemeris_sources = set()
    for planet_id, body_id, name, name_tr in PLANETS:
        try:
            row, source = _body_position(
                jd_ut,
                planet_id,
                body_id,
                name,
                name_tr,
                cusps,
            )
        except ChartCalculationError:
            if body_id == "chiron":
                # Chiron'un asteroid ephemeris dosyası (seas_*.se1) bazı
                # kurulumlarda eksik/kısmi olabilir; bu durumda Chiron'u
                # atlayıp haritanın geri kalanını (Güneş-Plüton) döndürürüz.
                continue
            raise
        planet_rows.append(row)
        ephemeris_sources.add(source)

    node_rows, node_source = _calculate_nodes(jd_ut, node_type, cusps)
    ephemeris_sources.add(node_source)

    occupants = {house: [] for house in range(1, 13)}
    for body in [*planet_rows, *node_rows]:
        occupants[body["house"]].append(body["id"])

    houses = []
    for index, cusp in enumerate(cusps):
        houses.append(
            {
                "house": index + 1,
                **_degree_fields(cusp),
                "occupants": occupants[index + 1],
            }
        )

    orb_profile, effective_orbs, luminary_bonus = _effective_orbs(options)
    aspects = _calculate_aspects(
        [*planet_rows, *node_rows],
        effective_orbs,
        luminary_bonus,
    )
    # Declination aspects (parallel, contraparallel, out-of-bounds)
    try:
        ecl_nut, _ = swe.calc_ut(jd_ut, swe.ECL_NUT)
        obliquity_deg = float(ecl_nut[0])
        decl_items = _planet_declinations(
            jd_ut, ascendant, midheaven, obliquity_deg,
        )
        declination_data = _compute_declination_aspects(decl_items)
    except swe.Error:
        declination_data = {
            "status": "unavailable",
            "reason": "declination_calculation_failed",
        }
    # Fixed star contacts (klasik kavuşum, orb 1°)
    stars_ok = _fixed_stars_available()
    if stars_ok:
        star_bodies: list[dict] = []
        for p in planet_rows:
            star_bodies.append({
                "id": p["id"],
                "label": p.get("name_tr") or p["id"],
                "longitude": p["longitude"],
                "kind": "planet",
            })
        for n in node_rows:
            star_bodies.append({
                "id": n["id"],
                "label": n.get("name_tr") or n["id"],
                "longitude": n["longitude"],
                "kind": "node",
            })
        for angle_id, angle_lon in (
            ("ascendant", ascendant),
            ("descendant", ascendant + 180.0),
            ("midheaven", midheaven),
            ("imum_coeli", midheaven + 180.0),
        ):
            star_bodies.append({
                "id": angle_id,
                "label": angle_id,
                "longitude": angle_lon % 360.0,
                "kind": "angle",
            })
        try:
            fixed_star_contacts = find_star_conjunctions(
                star_bodies, jd_ut, orb=FIXED_STAR_ORB,
            )
        except Exception:
            fixed_star_contacts = []
            stars_ok = False
    else:
        fixed_star_contacts = []

    time_confidence = str(birth_input.get("time_confidence") or "unknown")
    if time_confidence not in TIME_CONFIDENCE:
        raise ChartInputError(
            "birth.time_confidence high, rectified, medium, low veya unknown olmalıdır"
        )

    person = payload.get("person") or {}
    birth = {
        "date": local_dt.date().isoformat(),
        "time": local_dt.strftime("%H:%M:%S"),
        "local_datetime": local_dt.isoformat(),
        "utc_datetime": utc_dt.isoformat().replace("+00:00", "Z"),
        "timezone_id": timezone_id,
        "tz_offset": tz_offset,
        "latitude": latitude,
        "longitude": longitude_geo,
        "place": birth_input.get("place"),
        "time_confidence": time_confidence,
    }
    if person:
        if not isinstance(person, dict):
            raise ChartInputError("person nesne olmalıdır")
        birth["person"] = {
            "id": person.get("id"),
            "name": person.get("name"),
        }

    result = {
        "ok": True,
        "meta": {
            "schema_version": "2.0.0",
            "api_version": "v2",
            "generated_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
            "engine": "progressive-western-chart",
            "engine_version": "0.2.0",
            "ephemeris": {
                "library": "Swiss Ephemeris",
                "library_version": swe.version,
                "calculation_sources": sorted(ephemeris_sources),
            },
            "zodiac": "tropical",
            "house_system": house_system,
            "node_type": node_type,
            "orb_policy": {
                "profile": orb_profile,
                "orbs": effective_orbs,
                "sun_moon_bonus": luminary_bonus,
            },
            "calculation_policy": "api_only_no_chat_calculation",
        },
        "birth": birth,
        "data_quality": {
            "status": "available",
            "birth_time_confidence": time_confidence,
            "rectification_needed": time_confidence in {"low", "unknown"},
            "timezone_source": "timezone_id" if timezone_id else "fixed_tz_offset",
            "ascendant_sensitivity": _ascendant_sensitivity(
                jd_ut,
                latitude,
                longitude_geo,
                house_system,
                ascendant,
            ),
            "warnings": warnings,
        },
        "angles": {
            "status": "available",
            "ascendant": _degree_fields(ascendant),
            "descendant": _degree_fields(ascendant + 180.0),
            "midheaven": _degree_fields(midheaven),
            "imum_coeli": _degree_fields(midheaven + 180.0),
        },
        "planets": {
            "status": "available",
            "items": planet_rows,
        },
        "nodes": {
            "status": "available",
            "node_type": node_type,
            "items": node_rows,
        },
        "houses": {
            "status": "available",
            "house_system": house_system,
            "items": houses,
        },
        "aspects": {
            **aspects,
            "orb_policy": {
                "profile": orb_profile,
                "orbs": effective_orbs,
                "sun_moon_bonus": luminary_bonus,
            },
            "declination": declination_data,
        },
        "package_status": {
            "core": {
                "status": "available",
                "version": "1.0.0",
            },
            "fixed_stars": {
                "status": "available" if stars_ok else "unavailable",
                "version": "1.0.0",
            },
        },
        "fixed_stars": {
            "status": "available" if stars_ok else "unavailable",
            "orb": FIXED_STAR_ORB,
            "catalog_size": len(STAR_CATALOG),
            "contacts": fixed_star_contacts,
            "note": (
                "Klasik sabit yıldız kavuşumları (orb 1°). "
                "sefstars.txt eksikse 'unavailable' döner."
            ),
        },
        "missing": [],
    }
    return result
