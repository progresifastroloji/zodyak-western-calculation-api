#!/usr/bin/env python3
"""Western Horary (Soru) Astrology calculations.

Soru anı için harita kurar; significator atamaları, considerations before
judgment ve temel perfection analizini bir veri paketi olarak sunar.
Yorum üretmez; yargı ve danışmanlık dili bu teknik hesap katmanının dışındadır.

v1 kapsamı:
- Question chart kurulumu (Regiomontanus default, Placidus/Whole Sign opsiyonel)
- Question category → quesited house mapping (60+ klasik kategori)
- Significators: querent (1st ev ruler), quesited (target house ruler),
  Moon (co-sig), opsiyonel natural significator
- Considerations before judgment (Lilly tarzı klasik kontrol listesi)
- Significator-to-significator aspect (applying/separating, orb, reception)
- Moon's last & upcoming major aspects (out-of-sign'a kadar)
- Part of Fortune
- Hedef ev cusp condition
- Combust / under beams / cazimi
- Via Combusta

v2'ye:
- Translation of Light
- Collection of Light
- Prohibition / Refranation / Frustration
- Antiscia
- Almuten figuris

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını kullanır.
"""

from __future__ import annotations

import json
import re
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    SIGNS,
    _shortest_separation,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


HORARY_VERSION = "1.0.0"

# Question category → hedef ev numarası (klasik Lilly çizgisinde)
QUESTION_CATEGORIES = {
    # 1. ev — kişi, sağlık, görünüm
    "self_health": 1,
    "self_general": 1,
    "self_appearance": 1,
    # 2. ev — para, taşınır mal
    "money": 2,
    "lost_object": 2,
    "movable_possessions": 2,
    "personal_resources": 2,
    # 3. ev — kardeşler, kısa yolculuk, iletişim, komşu
    "sibling": 3,
    "short_journey": 3,
    "communication": 3,
    "neighbor": 3,
    "education_basic": 3,
    # 4. ev — ebeveyn, ev, gayrimenkul, son durum
    "parent": 4,
    "home": 4,
    "real_estate": 4,
    "buried_treasure": 4,
    "end_of_matter": 4,
    "ancestors": 4,
    # 5. ev — çocuk, hamilelik, romantizm, spekülasyon
    "child": 5,
    "pregnancy": 5,
    "romance": 5,
    "speculation": 5,
    "entertainment": 5,
    "creative_work": 5,
    # 6. ev — küçük hayvan, hastalık, hizmetkâr, günlük iş
    "pet_small": 6,
    "illness": 6,
    "employee": 6,
    "service": 6,
    "daily_work": 6,
    # 7. ev — evlilik, ortak, açık düşman, kontrat, dava
    "marriage": 7,
    "partner": 7,
    "spouse": 7,
    "open_enemy": 7,
    "contract": 7,
    "lawsuit": 7,
    "business_partner": 7,
    # 8. ev — ölüm, miras, ortak finans
    "death": 8,
    "inheritance": 8,
    "joint_finances": 8,
    "shared_resources": 8,
    "surgery": 8,
    "occult": 8,
    # 9. ev — uzun yolculuk, yüksek eğitim, din, yayın
    "long_journey": 9,
    "education_higher": 9,
    "religion": 9,
    "publishing": 9,
    "legal_higher_court": 9,
    "philosophy": 9,
    # 10. ev — kariyer, itibar, otorite
    "career": 10,
    "reputation": 10,
    "boss": 10,
    "government": 10,
    "honors": 10,
    "public_status": 10,
    # 11. ev — arkadaşlar, umutlar, gruplar
    "friends": 11,
    "hopes": 11,
    "groups": 11,
    "income_from_career": 11,
    # 12. ev — gizli düşman, sırlar, hapis, sürgün
    "hidden_enemies": 12,
    "secrets": 12,
    "imprisonment": 12,
    "large_animals": 12,
    "self_undoing": 12,
    "hospital": 12,
    "exile": 12,
}

# Klasik (Lilly / Hellenistic) rulership
CLASSICAL_RULERSHIP = {
    "aries": "mars",
    "taurus": "venus",
    "gemini": "mercury",
    "cancer": "moon",
    "leo": "sun",
    "virgo": "mercury",
    "libra": "venus",
    "scorpio": "mars",
    "sagittarius": "jupiter",
    "capricorn": "saturn",
    "aquarius": "saturn",
    "pisces": "jupiter",
}

# Modern rulership (outer planets co-ruler olarak)
MODERN_RULERSHIP = {
    "scorpio": "pluto",
    "aquarius": "uranus",
    "pisces": "neptune",
}

# Exaltation (klasik)
EXALTATION = {
    "aries": "sun",
    "taurus": "moon",
    "cancer": "jupiter",
    "virgo": "mercury",
    "libra": "saturn",
    "capricorn": "mars",
    "pisces": "venus",
}

# Detriment (domicile'in karşı burcu)
DETRIMENT = {
    "aries": "venus",      # libra'nın karşıtı
    "taurus": "mars",      # scorpio
    "gemini": "jupiter",   # sagittarius
    "cancer": "saturn",    # capricorn
    "leo": "saturn",       # aquarius
    "virgo": "jupiter",    # pisces
    "libra": "mars",       # aries
    "scorpio": "venus",    # taurus
    "sagittarius": "mercury",  # gemini
    "capricorn": "moon",   # cancer
    "aquarius": "sun",     # leo
    "pisces": "mercury",   # virgo
}

# Fall (exaltation karşıtı)
FALL = {
    "aries": "saturn",
    "taurus": None,
    "cancer": "mars",
    "libra": "sun",
    "capricorn": "jupiter",
    "scorpio": "moon",
    "virgo": "venus",
    "pisces": "mercury",
}

# Doğal anlamlandırıcılar (kategori bazlı)
NATURAL_SIGNIFICATORS = {
    "marriage": "venus",
    "romance": "venus",
    "spouse": "venus",
    "child": "moon",
    "pregnancy": "moon",
    "career": "saturn",
    "money": "jupiter",
    "lost_object": "mercury",
    "movable_possessions": "mercury",
    "illness": "saturn",
    "death": "saturn",
    "education_higher": "jupiter",
    "long_journey": "jupiter",
    "contract": "mercury",
    "lawsuit": "saturn",
    "publishing": "jupiter",
    "speculation": "jupiter",
    "communication": "mercury",
    "self_health": "sun",
    "honors": "sun",
    "reputation": "sun",
    "buried_treasure": "saturn",
}

# Via Combusta: 15° Libra (195°) - 15° Scorpio (225°)
VIA_COMBUSTA_START = 195.0
VIA_COMBUSTA_END = 225.0

# Considerations
LATE_DEGREE_THRESHOLD = 27.0
EARLY_DEGREE_THRESHOLD = 3.0
END_OF_SIGN_THRESHOLD = 29.0

# Sun proximity
COMBUST_ORB = 8.5
UNDER_BEAMS_ORB = 17.0
CAZIMI_ORB_MINUTES = 17.0 / 60.0  # ~0.2833°

# Horary moiety orbs (Lilly tarzı)
HORARY_ORBS = {
    "sun": 17.0,
    "moon": 12.5,
    "mercury": 7.0,
    "venus": 7.0,
    "mars": 7.5,
    "jupiter": 9.0,
    "saturn": 9.0,
    "uranus": 5.0,
    "neptune": 5.0,
    "pluto": 5.0,
    "mean_node": 4.0,
    "south_node": 4.0,
    "true_node": 4.0,
    "chiron": 5.0,
}

# Açı tipleri: (exact_angle, tr, harmonious)
ASPECT_TYPES = {
    "conjunction": (0.0, "Kavuşum", None),  # nötr; gezegenin doğasına bağlı
    "sextile": (60.0, "Sekstil", True),
    "square": (90.0, "Kare", False),
    "trine": (120.0, "Üçgen", True),
    "opposition": (180.0, "Karşıt", False),
}

MAJOR_ASPECTS_FOR_MOON = ("conjunction", "sextile", "square", "trine", "opposition")

CLASSICAL_PLANETS = ("sun", "moon", "mercury", "venus", "mars", "jupiter", "saturn")
MALEFICS_CLASSICAL = ("mars", "saturn")
BENEFICS_CLASSICAL = ("venus", "jupiter")


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class HoraryInputError(ValueError):
    """Horary için geçersiz input."""


class HoraryCalculationError(RuntimeError):
    """Horary hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _slugify(text: str) -> str:
    text = text.lower()
    text = re.sub(r"[^\w\s-]", "", text, flags=re.UNICODE)
    text = re.sub(r"\s+", "-", text.strip())
    return text[:60] or "question"


def _validate_horary_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise HoraryInputError("JSON gövdesi nesne olmalıdır")
    h = payload.get("horary") or {}
    if not isinstance(h, dict):
        raise HoraryInputError("horary alanı nesne olmalıdır")

    question = h.get("question")
    if not question or not isinstance(question, str):
        raise HoraryInputError("horary.question (soru metni) zorunludur")
    question = question.strip()
    if len(question) > 500:
        raise HoraryInputError("horary.question 500 karakteri aşamaz")

    category = h.get("category")
    if not category or category not in QUESTION_CATEGORIES:
        raise HoraryInputError(
            f"horary.category zorunlu ve geçerli olmalı "
            f"({len(QUESTION_CATEGORIES)} kategori mevcut). "
            f"Örnek: 'marriage', 'career', 'lost_object'"
        )

    qdt_value = h.get("question_datetime_utc")
    if not qdt_value:
        raise HoraryInputError(
            "horary.question_datetime_utc zorunlu (ISO-8601 UTC, örn 2026-06-23T14:30:00Z)"
        )
    try:
        question_dt = datetime.fromisoformat(str(qdt_value).replace("Z", "+00:00"))
        if question_dt.tzinfo is None:
            question_dt = question_dt.replace(tzinfo=timezone.utc)
        else:
            question_dt = question_dt.astimezone(timezone.utc)
    except (ValueError, TypeError) as exc:
        raise HoraryInputError(
            f"Geçersiz horary.question_datetime_utc: {qdt_value}"
        ) from exc

    loc = h.get("location") or {}
    if not isinstance(loc, dict):
        raise HoraryInputError("horary.location alanı nesne olmalıdır")
    if "lat" not in loc or "lon" not in loc:
        raise HoraryInputError("horary.location.lat ve lon zorunludur")
    if not loc.get("timezone_id"):
        raise HoraryInputError("horary.location.timezone_id zorunludur")
    try:
        ZoneInfo(loc["timezone_id"])
    except ZoneInfoNotFoundError as exc:
        raise HoraryInputError(
            f"Geçersiz horary.location.timezone_id: {loc['timezone_id']}"
        ) from exc

    return {
        "question": question,
        "category": category,
        "question_dt_utc": question_dt,
        "location": loc,
    }


def _build_question_chart_payload(h_input: dict, options: dict | None) -> dict:
    """Soru anı için core_chart payload'ı oluştur."""
    qdt = h_input["question_dt_utc"]
    loc = h_input["location"]
    if not options or not isinstance(options, dict):
        options = {}
    final_options = {
        "zodiac": options.get("zodiac", "tropical"),
        "house_system": options.get("house_system", "regiomontanus"),
        "node_type": options.get("node_type", "mean"),
    }
    return {
        "birth": {
            "year": qdt.year,
            "month": qdt.month,
            "day": qdt.day,
            "hour": qdt.hour,
            "minute": qdt.minute,
            "second": qdt.second,
            "lat": float(loc["lat"]),
            "lon": float(loc["lon"]),
            "timezone_id": loc["timezone_id"],
            "place": loc.get("place"),
            "time_confidence": "high",
            "utc": True,
        },
        "options": final_options,
    }


def _sign_id_from_name_en(name_en: str) -> str:
    return name_en.lower()


def _planet_by_id(chart: dict, planet_id: str) -> dict | None:
    for p in chart["planets"]["items"]:
        if p["id"] == planet_id:
            return p
    return None


def _sign_id_of(planet: dict) -> str:
    # western_chart core item'da sign_index var; SIGNS[idx] = (en, tr)
    idx = planet.get("sign_index")
    if idx is None:
        return ""
    return SIGNS[idx][0].lower()


def _classical_ruler_of_sign(sign_id: str) -> str:
    return CLASSICAL_RULERSHIP.get(sign_id, "")


def _modern_ruler_of_sign(sign_id: str) -> str:
    return MODERN_RULERSHIP.get(sign_id) or CLASSICAL_RULERSHIP.get(sign_id, "")


def _planet_dignity_status(planet: dict) -> dict:
    """Gezegenin bulunduğu burçtaki essential dignity durumu."""
    sign_id = _sign_id_of(planet)
    pid = planet["id"]
    return {
        "in_domicile": CLASSICAL_RULERSHIP.get(sign_id) == pid,
        "in_exaltation": EXALTATION.get(sign_id) == pid,
        "in_detriment": DETRIMENT.get(sign_id) == pid,
        "in_fall": FALL.get(sign_id) == pid,
        "sign_id": sign_id,
    }


def _combustion_status(planet: dict, sun: dict) -> dict:
    if planet["id"] == "sun":
        return {"combust": False, "under_beams": False, "cazimi": False, "separation_deg": 0.0}
    sep = _shortest_separation(planet["longitude"], sun["longitude"])
    cazimi = sep <= CAZIMI_ORB_MINUTES
    combust = (not cazimi) and sep <= COMBUST_ORB
    under_beams = (not combust) and (not cazimi) and sep <= UNDER_BEAMS_ORB
    return {
        "combust": combust,
        "under_beams": under_beams,
        "cazimi": cazimi,
        "separation_deg": round(sep, 4),
    }


def _is_applying(p_a: dict, p_b: dict, exact_aspect_angle: float) -> bool | None:
    """A B'ye verilen aspekt açısı için yaklaşıyor mu?"""
    sep_now = _shortest_separation(p_a["longitude"], p_b["longitude"])
    speed_a = float(p_a.get("speed_longitude") or 0.0)
    speed_b = float(p_b.get("speed_longitude") or 0.0)
    if speed_a == 0.0 and speed_b == 0.0:
        return None
    dt = 0.01  # gün
    lon_a_next = (p_a["longitude"] + speed_a * dt) % 360.0
    lon_b_next = (p_b["longitude"] + speed_b * dt) % 360.0
    sep_next = _shortest_separation(lon_a_next, lon_b_next)
    orb_now = abs(sep_now - exact_aspect_angle)
    orb_next = abs(sep_next - exact_aspect_angle)
    return orb_next < orb_now


def _aspect_between(p_a: dict, p_b: dict) -> dict | None:
    """İki gezegen arasında horary orb içinde majör açı varsa döner."""
    sep = _shortest_separation(p_a["longitude"], p_b["longitude"])
    a_orb = HORARY_ORBS.get(p_a["id"], 5.0)
    b_orb = HORARY_ORBS.get(p_b["id"], 5.0)
    # Lilly moiety yöntemi: iki orbun yarılarının toplamı
    orb_allowed = (a_orb + b_orb) / 2.0

    best = None
    for aspect_id, (exact, name_tr, harmonious) in ASPECT_TYPES.items():
        diff = abs(sep - exact)
        if diff <= orb_allowed and (best is None or diff < best["_diff"]):
            best = {
                "_diff": diff,
                "type": aspect_id,
                "type_tr": name_tr,
                "exact_angle": exact,
                "orb": round(diff, 4),
                "orb_allowed": round(orb_allowed, 4),
                "harmonious": harmonious,
            }
    if not best:
        return None
    applying = _is_applying(p_a, p_b, best["exact_angle"])
    best["applying"] = applying
    best.pop("_diff")
    return best


def _reception_between(p_a: dict, p_b: dict) -> dict:
    """İki gezegen arasında reception ilişkilerini listele."""
    sign_a = _sign_id_of(p_a)
    sign_b = _sign_id_of(p_b)
    a_id = p_a["id"]
    b_id = p_b["id"]

    receptions = []
    # A'nın burcunu B yönetiyorsa B, A'yı domicile ile ağırlıyor
    if CLASSICAL_RULERSHIP.get(sign_a) == b_id:
        receptions.append({"giver": b_id, "receiver": a_id, "type": "domicile"})
    if CLASSICAL_RULERSHIP.get(sign_b) == a_id:
        receptions.append({"giver": a_id, "receiver": b_id, "type": "domicile"})
    if EXALTATION.get(sign_a) == b_id:
        receptions.append({"giver": b_id, "receiver": a_id, "type": "exaltation"})
    if EXALTATION.get(sign_b) == a_id:
        receptions.append({"giver": a_id, "receiver": b_id, "type": "exaltation"})

    mutual_domicile = any(
        r["receiver"] == a_id and r["type"] == "domicile" for r in receptions
    ) and any(
        r["receiver"] == b_id and r["type"] == "domicile" for r in receptions
    )
    mutual_exaltation = any(
        r["receiver"] == a_id and r["type"] == "exaltation" for r in receptions
    ) and any(
        r["receiver"] == b_id and r["type"] == "exaltation" for r in receptions
    )

    return {
        "receptions": receptions,
        "mutual_reception_by_domicile": mutual_domicile,
        "mutual_reception_by_exaltation": mutual_exaltation,
        "any_mutual": mutual_domicile or mutual_exaltation,
    }


def _potential_aspect_targets(exact_angle: float) -> list[float]:
    if exact_angle == 0.0:
        return [0.0]
    if exact_angle == 180.0:
        return [180.0]
    return [exact_angle, -exact_angle]


def _moon_next_aspects(chart: dict) -> list[dict]:
    """Ay'ın bulunduğu burçtan çıkana kadar yapacağı majör açılar (sıralı)."""
    moon = _planet_by_id(chart, "moon")
    if not moon:
        return []
    moon_lon = moon["longitude"]
    moon_speed = float(moon.get("speed_longitude") or 13.18)
    if moon_speed <= 0:
        return []
    current_sign_index = int(moon_lon // 30)
    sign_end_lon = (current_sign_index + 1) * 30.0
    max_advance_deg = sign_end_lon - moon_lon

    found = []
    for other_id in CLASSICAL_PLANETS:
        if other_id == "moon":
            continue
        other = _planet_by_id(chart, other_id)
        if not other:
            continue
        other_speed = float(other.get("speed_longitude") or 0.0)
        rel_speed = moon_speed - other_speed
        if rel_speed <= 0.01:
            continue

        current_diff = ((moon_lon - other["longitude"] + 180.0) % 360.0) - 180.0
        for aspect_id, (exact, tr, harmonious) in ASPECT_TYPES.items():
            for target_diff in _potential_aspect_targets(exact):
                rel_advance_needed = (target_diff - current_diff) % 360.0
                if rel_advance_needed <= 0.0:
                    continue
                moon_advance_deg = rel_advance_needed * moon_speed / rel_speed
                if moon_advance_deg > max_advance_deg:
                    continue
                found.append({
                    "target_planet": other_id,
                    "aspect": aspect_id,
                    "aspect_tr": tr,
                    "harmonious": harmonious,
                    "moon_advance_degrees": round(moon_advance_deg, 4),
                    "days_until": round(rel_advance_needed / rel_speed, 4),
                    "moon_target_longitude": round(
                        (moon_lon + moon_advance_deg) % 360.0, 4
                    ),
                })
    found.sort(key=lambda x: x["moon_advance_degrees"])
    return found


def _moon_void_of_course(next_aspects: list[dict], moon_speed: float) -> dict:
    """Ay burçtan çıkana kadar başka gezegene majör açı yapmıyorsa VoC."""
    if not next_aspects:
        return {"void_of_course": moon_speed > 0, "reason": "no_perfecting_aspect_in_sign"}
    return {"void_of_course": False, "reason": None}


def _build_considerations(chart: dict, target_house: int) -> dict:
    """Considerations Before Judgment (Lilly kontrol listesi)."""
    moon = _planet_by_id(chart, "moon")
    saturn = _planet_by_id(chart, "saturn")
    sun = _planet_by_id(chart, "sun")

    asc_lon = chart["angles"]["ascendant"]["longitude"]
    asc_degree_in_sign = asc_lon % 30.0

    considerations = {
        "asc_too_early_lt_3deg": asc_degree_in_sign < EARLY_DEGREE_THRESHOLD,
        "asc_too_late_gt_27deg": asc_degree_in_sign >= LATE_DEGREE_THRESHOLD,
        "asc_degree_in_sign": round(asc_degree_in_sign, 4),
        "saturn_in_1st_house": (saturn and saturn.get("house") == 1) or False,
        "saturn_in_7th_house": (saturn and saturn.get("house") == 7) or False,
    }

    if moon:
        moon_lon = moon["longitude"]
        moon_degree_in_sign = moon_lon % 30.0
        considerations.update({
            "moon_in_via_combusta": VIA_COMBUSTA_START <= moon_lon < VIA_COMBUSTA_END,
            "moon_at_end_of_sign_29deg": moon_degree_in_sign >= END_OF_SIGN_THRESHOLD,
            "moon_degree_in_sign": round(moon_degree_in_sign, 4),
        })

    if sun:
        considerations["sun_combust_other_planets"] = []
        for other_id in ("mercury", "venus", "mars"):
            other = _planet_by_id(chart, other_id)
            if not other:
                continue
            comb = _combustion_status(other, sun)
            if comb["combust"]:
                considerations["sun_combust_other_planets"].append(other_id)

    # Hedef ev cusp condition: cusp'ta malefic var mı?
    cusp_lon = chart["houses"]["items"][target_house - 1]["longitude"]
    cusp_malefics = []
    for malefic_id in MALEFICS_CLASSICAL:
        m = _planet_by_id(chart, malefic_id)
        if not m:
            continue
        sep = _shortest_separation(m["longitude"], cusp_lon)
        if sep <= 5.0:  # 5° orb
            cusp_malefics.append({
                "planet": malefic_id,
                "orb": round(sep, 4),
            })
    considerations["target_cusp_malefics_within_5deg"] = cusp_malefics

    return considerations


def _significator_detail(chart: dict, planet: dict | None, sun: dict | None) -> dict | None:
    if planet is None:
        return None
    dignity = _planet_dignity_status(planet)
    combustion = _combustion_status(planet, sun) if sun else None
    return {
        "planet_id": planet["id"],
        "planet_tr": planet.get("name_tr"),
        "sign_id": dignity["sign_id"],
        "sign_tr": planet.get("sign_tr"),
        "degree_str": planet.get("degree_str"),
        "longitude": round(planet["longitude"], 4),
        "house": planet.get("house"),
        "retrograde": planet.get("retrograde", False),
        "speed_longitude": round(float(planet.get("speed_longitude") or 0.0), 6),
        "essential_dignity": dignity,
        "combustion": combustion,
        "in_via_combusta": (
            VIA_COMBUSTA_START <= planet["longitude"] < VIA_COMBUSTA_END
        ),
    }


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_horary(payload: dict) -> dict:
    """Horary soru anı için veri paketi üretir."""

    h_input = _validate_horary_input(payload)
    chart_payload = _build_question_chart_payload(h_input, payload.get("options"))
    chart = calculate_core_chart(chart_payload)

    target_house = QUESTION_CATEGORIES[h_input["category"]]

    # Significators
    asc_sign_id = _sign_id_from_name_en(chart["angles"]["ascendant"]["sign"])
    querent_ruler_id = _classical_ruler_of_sign(asc_sign_id)

    target_cusp_sign = chart["houses"]["items"][target_house - 1]["sign"].lower()
    quesited_ruler_id = _classical_ruler_of_sign(target_cusp_sign)

    moon = _planet_by_id(chart, "moon")
    sun = _planet_by_id(chart, "sun")
    querent_planet = _planet_by_id(chart, querent_ruler_id)
    quesited_planet = _planet_by_id(chart, quesited_ruler_id)
    natural_sig_id = NATURAL_SIGNIFICATORS.get(h_input["category"])
    natural_planet = _planet_by_id(chart, natural_sig_id) if natural_sig_id else None

    significators = {
        "querent": {
            "house": 1,
            "ruler_id": querent_ruler_id,
            "asc_sign_id": asc_sign_id,
            "asc_sign_tr": chart["angles"]["ascendant"]["sign_tr"],
            "detail": _significator_detail(chart, querent_planet, sun),
        },
        "quesited": {
            "house": target_house,
            "ruler_id": quesited_ruler_id,
            "cusp_sign_id": target_cusp_sign,
            "cusp_sign_tr": chart["houses"]["items"][target_house - 1]["sign_tr"],
            "cusp_degree_str": chart["houses"]["items"][target_house - 1]["degree_str"],
            "detail": _significator_detail(chart, quesited_planet, sun),
        },
        "co_significator_moon": _significator_detail(chart, moon, sun),
        "natural_significator": {
            "planet_id": natural_sig_id,
            "detail": _significator_detail(chart, natural_planet, sun),
        } if natural_sig_id else None,
    }

    # Significator aspects
    aspect_pairs = []

    def _add_pair(label, p_a, p_b):
        if not p_a or not p_b or p_a["id"] == p_b["id"]:
            return
        aspect = _aspect_between(p_a, p_b)
        reception = _reception_between(p_a, p_b)
        aspect_pairs.append({
            "pair_label": label,
            "planet_a": p_a["id"],
            "planet_b": p_b["id"],
            "aspect": aspect,  # None olabilir
            "reception": reception,
        })

    _add_pair("querent_quesited", querent_planet, quesited_planet)
    _add_pair("querent_moon", querent_planet, moon)
    _add_pair("quesited_moon", quesited_planet, moon)
    if natural_planet:
        _add_pair("querent_natural", querent_planet, natural_planet)
        _add_pair("quesited_natural", quesited_planet, natural_planet)
        _add_pair("moon_natural", moon, natural_planet)

    # Moon's upcoming aspects
    moon_next = _moon_next_aspects(chart)
    moon_voc = _moon_void_of_course(
        moon_next, float(moon.get("speed_longitude") or 0.0) if moon else 0.0
    )

    # Considerations
    considerations = _build_considerations(chart, target_house)

    # Part of Fortune (advanced_natal'da hesaplanıyor; burada core'a göre türev)
    # Lots gerek olursa advanced_natal çağrılabilir; horary için PoF ev konumu yeter.
    pof_data = None
    if sun and moon:
        asc_lon = chart["angles"]["ascendant"]["longitude"]
        # Gündüz: ASC + Moon - Sun; Gece: ASC + Sun - Moon (klasik Lilly)
        is_day = sun.get("house") in (7, 8, 9, 10, 11, 12)  # ufkun üstü
        if is_day:
            pof_lon = (asc_lon + moon["longitude"] - sun["longitude"]) % 360.0
        else:
            pof_lon = (asc_lon + sun["longitude"] - moon["longitude"]) % 360.0
        pof_sign_idx = int(pof_lon // 30)
        pof_data = {
            "longitude": round(pof_lon, 4),
            "sign_id": SIGNS[pof_sign_idx][0].lower(),
            "sign_tr": SIGNS[pof_sign_idx][1],
            "degree_str": f"{int(pof_lon % 30)}°{int((pof_lon % 1) * 60):02d}'",
            "house": _house_number_for_pof(pof_lon, chart),
            "sect": "day" if is_day else "night",
        }

    limitations = [
        "Bu veri paketi yargı (judgment) içermez; yalnızca girdileri sunar.",
        "Translation/Collection of Light, Prohibition, Refranation v1'de yoktur.",
        "Antiscia v1'de yoktur.",
        "Klasik (Lilly) yaklaşımı esas alınır; modern outer planet'lar yalnızca co-ruler olarak kullanılır.",
        "Ascendant erken/geç derece uyarıları danışmanın yargısı için iletilir; otomatik red oluşturulmaz.",
    ]

    return {
        "status": "available",
        "version": HORARY_VERSION,
        "method": "horary_lilly_classical_data_only",
        "question": h_input["question"],
        "category": h_input["category"],
        "question_datetime_utc": h_input["question_dt_utc"].isoformat().replace("+00:00", "Z"),
        "question_datetime_local": chart["birth"]["local_datetime"],
        "location": {
            "lat": float(h_input["location"]["lat"]),
            "lon": float(h_input["location"]["lon"]),
            "timezone_id": h_input["location"]["timezone_id"],
            "place": h_input["location"].get("place"),
        },
        "chart_summary": {
            "ascendant_sign_tr": chart["angles"]["ascendant"]["sign_tr"],
            "ascendant_degree_str": chart["angles"]["ascendant"]["degree_str"],
            "midheaven_sign_tr": chart["angles"]["midheaven"]["sign_tr"],
            "house_system": chart["meta"]["house_system"],
            "moon_sign_tr": moon["sign_tr"] if moon else None,
            "moon_degree_str": moon["degree_str"] if moon else None,
        },
        "target_house": target_house,
        "significators": significators,
        "significator_pairs": aspect_pairs,
        "moon_next_aspects_in_sign": moon_next,
        "moon_void_of_course": moon_voc,
        "considerations_before_judgment": considerations,
        "part_of_fortune": pof_data,
        "full_chart": chart,
        "limitations": limitations,
    }


def _house_number_for_pof(pof_lon: float, chart: dict) -> int:
    cusps = [h["longitude"] for h in chart["houses"]["items"]]
    for i in range(12):
        start = cusps[i]
        end = cusps[(i + 1) % 12]
        if start <= end:
            if start <= pof_lon < end:
                return i + 1
        else:
            if pof_lon >= start or pof_lon < end:
                return i + 1
    return 1


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def _markdown_value(value) -> str:
    if value is None:
        return "-"
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(headers, rows) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_value(v) for v in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def _format_significator_row(label: str, sig: dict | None) -> tuple:
    if not sig or not sig.get("detail"):
        return (label, "-", "-", "-", "-", "-")
    d = sig["detail"]
    dig = d["essential_dignity"]
    dignity_flags = []
    if dig["in_domicile"]:
        dignity_flags.append("Domicile")
    if dig["in_exaltation"]:
        dignity_flags.append("Exalt.")
    if dig["in_detriment"]:
        dignity_flags.append("Detrim.")
    if dig["in_fall"]:
        dignity_flags.append("Fall")
    return (
        label,
        d["planet_tr"] or d["planet_id"],
        f'{d["sign_tr"]} {d["degree_str"]}',
        f'e{d["house"]}' if d.get("house") else "-",
        "R" if d["retrograde"] else "-",
        ", ".join(dignity_flags) or "-",
    )


def build_horary_markdown(
    horary: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    sigs = horary["significators"]
    cons = horary["considerations_before_judgment"]
    moon_next = horary["moon_next_aspects_in_sign"]
    voc = horary["moon_void_of_course"]
    pof = horary["part_of_fortune"]
    chart_summary = horary["chart_summary"]

    question_slug = _slugify(horary["question"])

    fm_lines = [
        "---",
        f'title: "{person_name} - Horary {question_slug}"',
        'type: "horary_pack"',
        'source: "western_api_v2_horary"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'question: {json.dumps(horary["question"], ensure_ascii=False)}',
        f'category: "{horary["category"]}"',
        f'target_house: {horary["target_house"]}',
        f'question_datetime_utc: "{horary["question_datetime_utc"]}"',
        f'location_place: "{horary["location"].get("place") or "-"}"',
        f'location_tz: "{horary["location"]["timezone_id"]}"',
        f'house_system: "{chart_summary["house_system"]}"',
        f'method: "{horary["method"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{HORARY_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    intro = [
        f"# {person_name} - Horary",
        "",
        f"**Soru:** {horary['question']}",
        f"**Kategori:** {horary['category']} → Hedef ev: **{horary['target_house']}**",
        f"**Soru zamanı (UTC):** {horary['question_datetime_utc']}",
        f"**Soru zamanı (yerel):** {chart_summary.get('ascendant_sign_tr') and horary['question_datetime_local']}",
        f"**Konum:** {horary['location'].get('place') or '-'} ({horary['location']['timezone_id']})",
        "",
        "## Kullanım Notu",
        "",
        "- Bu dosya horary için API tarafından üretilen veri paketidir.",
        "- Yargı (judgment) içermez; significator durumlarını, açıları, considerations'ı listeler.",
        "- Klasik Lilly çizgisinde 7 gezegen + 12 ev mantığı esastır.",
        "- v1: Translation/Collection of Light, Prohibition, Refranation yoktur (v2'ye bırakıldı).",
        "",
    ]

    summary_section = [
        "## Harita Özeti",
        "",
        f"- Yükselen: **{chart_summary['ascendant_sign_tr']} {chart_summary['ascendant_degree_str']}**",
        f"- MC: {chart_summary['midheaven_sign_tr']}",
        f"- Ay: {chart_summary['moon_sign_tr']} {chart_summary['moon_degree_str']}",
        f"- Ev sistemi: {chart_summary['house_system']}",
        "",
    ]

    sig_rows = [
        _format_significator_row("Querent (1. ev rulers)", sigs["querent"]),
        _format_significator_row(
            f"Quesited ({sigs['quesited']['house']}. ev rulers)",
            sigs["quesited"],
        ),
    ]
    co_sig = sigs.get("co_significator_moon")
    if co_sig:
        sig_rows.append((
            "Co-sig: Ay",
            co_sig["planet_tr"] or "moon",
            f'{co_sig["sign_tr"]} {co_sig["degree_str"]}',
            f'e{co_sig["house"]}' if co_sig.get("house") else "-",
            "R" if co_sig["retrograde"] else "-",
            "-",
        ))
    if sigs.get("natural_significator") and sigs["natural_significator"]["detail"]:
        ns = sigs["natural_significator"]
        sig_rows.append(_format_significator_row(
            f"Natural sig: {ns['planet_id']}", ns,
        ))

    sig_section = [
        "## Significatorlar",
        "",
        f"- Querent burç: **{sigs['querent']['asc_sign_tr']}** → ruler = {sigs['querent']['ruler_id']}",
        f"- Quesited cusp: **{sigs['quesited']['cusp_sign_tr']} {sigs['quesited']['cusp_degree_str']}** → ruler = {sigs['quesited']['ruler_id']}",
        "",
        _md_table(
            ["Rol", "Gezegen", "Konum", "Ev", "Retro", "Dignity"],
            sig_rows,
        ),
        "",
    ]

    pair_rows = []
    for pair in horary["significator_pairs"]:
        aspect = pair["aspect"]
        rec = pair["reception"]
        rec_summary = []
        if rec["mutual_reception_by_domicile"]:
            rec_summary.append("M.Rec(Domicile)")
        if rec["mutual_reception_by_exaltation"]:
            rec_summary.append("M.Rec(Exalt)")
        if rec["receptions"] and not (rec["mutual_reception_by_domicile"] or rec["mutual_reception_by_exaltation"]):
            for r in rec["receptions"]:
                rec_summary.append(f'{r["giver"]}→{r["receiver"]}({r["type"][:3]})')

        if aspect:
            pair_rows.append((
                pair["pair_label"],
                f'{pair["planet_a"]} - {pair["planet_b"]}',
                aspect["type_tr"],
                f'{aspect["orb"]:.2f}°',
                ("App" if aspect["applying"] else "Sep") if aspect["applying"] is not None else "?",
                ", ".join(rec_summary) or "-",
            ))
        else:
            pair_rows.append((
                pair["pair_label"],
                f'{pair["planet_a"]} - {pair["planet_b"]}',
                "(orb dışı)",
                "-",
                "-",
                ", ".join(rec_summary) or "-",
            ))
    pairs_section = [
        "## Significator Çiftleri (Açı + Reception)",
        "",
        _md_table(
            ["Çift", "Gezegenler", "Açı", "Orb", "App/Sep", "Reception"],
            pair_rows,
        ),
        "",
    ]

    voc_text = (
        "**VOID OF COURSE** — Ay burcunu terk edene kadar majör açı yapmıyor."
        if voc["void_of_course"]
        else f"Ay aktif; burç çıkışına kadar **{len(moon_next)}** majör açı yapacak."
    )
    moon_rows = [
        (
            ma["target_planet"],
            ma["aspect_tr"],
            f'{ma["moon_advance_degrees"]:.2f}°',
            f'{ma["days_until"]:.2f}',
            "Hoş" if ma["harmonious"] else ("Zor" if ma["harmonious"] is False else "Nötr"),
        )
        for ma in moon_next
    ]
    moon_section = [
        "## Ay'ın Sonraki Açıları (burç çıkışına kadar)",
        "",
        voc_text,
        "",
        _md_table(
            ["Hedef", "Açı", "Ay İlerlemesi", "Gün", "Doğa"],
            moon_rows,
        ) if moon_rows else "_Burç sonuna kadar majör açı yok._",
        "",
    ]

    cons_rows = []
    for key in (
        "asc_too_early_lt_3deg",
        "asc_too_late_gt_27deg",
        "saturn_in_1st_house",
        "saturn_in_7th_house",
        "moon_in_via_combusta",
        "moon_at_end_of_sign_29deg",
    ):
        if key in cons:
            cons_rows.append((key, "EVET" if cons[key] else "-"))
    cons_rows.append((
        "ASC derecesi (burç içi)",
        f'{cons["asc_degree_in_sign"]:.2f}°',
    ))
    if "moon_degree_in_sign" in cons:
        cons_rows.append((
            "Ay derecesi (burç içi)",
            f'{cons["moon_degree_in_sign"]:.2f}°',
        ))
    cusp_malefics = cons.get("target_cusp_malefics_within_5deg") or []
    cons_rows.append((
        f"Hedef ev cusp'ında malefic (5° orb)",
        ", ".join(f'{m["planet"]} ({m["orb"]:.1f}°)' for m in cusp_malefics) or "-",
    ))
    sun_combust_list = cons.get("sun_combust_other_planets") or []
    cons_rows.append((
        "Güneş combust ettiği gezegenler",
        ", ".join(sun_combust_list) or "-",
    ))
    cons_section = [
        "## Considerations Before Judgment (Lilly Kontrol Listesi)",
        "",
        _md_table(["Madde", "Durum"], cons_rows),
        "",
    ]

    pof_section = []
    if pof:
        pof_section = [
            "## Part of Fortune",
            "",
            f'- Konum: **{pof["sign_tr"]} {pof["degree_str"]}** (e{pof["house"]})',
            f'- Sect (sect harita): **{pof["sect"]}**',
            "",
        ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in horary["limitations"]],
        "",
    ]

    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "```json",
        json.dumps(horary, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *intro,
        *summary_section,
        *sig_section,
        *pairs_section,
        *moon_section,
        *cons_section,
        *pof_section,
        *limit_section,
        *technical_section,
    ])
