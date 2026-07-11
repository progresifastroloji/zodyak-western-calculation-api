#!/usr/bin/env python3
"""Western astrology transit period calculations and markdown render.

Verilen tarih aralığında günlük öğlen 12:00 (yerel) snapshot listesi üretir.
Her snapshot'ta gezegen konumları, natal evlere yerleşimi, kritik temaslar
ve yıllık profection bilgisi bulunur. Vedik analoğu Vimshottari dasha
yerine Hellenistic yıllık profection kullanılır.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

from .western_chart import (
    CLASSICAL_RULERS,
    _degree_fields,
    _house_number,
    _julian_day,
    _shortest_separation,
    calculate_core_chart,
)
from .western_solar_return import (
    SolarReturnError,
    build_solar_return_markdown,
    calculate_solar_return,
)


# ---------------------------------------------------------------------------
# Sabitler ve yardımcı tablolar
# ---------------------------------------------------------------------------


TRANSIT_PLANET_IDS = [
    ("sun", swe.SUN),
    ("moon", swe.MOON),
    ("mercury", swe.MERCURY),
    ("venus", swe.VENUS),
    ("mars", swe.MARS),
    ("jupiter", swe.JUPITER),
    ("saturn", swe.SATURN),
    ("uranus", swe.URANUS),
    ("neptune", swe.NEPTUNE),
    ("pluto", swe.PLUTO),
]

# Hızlı/yavaş ayrımı (rapor için)
FAST_PLANETS = {"sun", "moon", "mercury", "venus", "mars"}
SLOW_PLANETS = {"jupiter", "saturn", "uranus", "neptune", "pluto"}

DEFAULT_TRANSIT_HOUR = 12
DEFAULT_TRANSIT_TIMEZONE = os.environ.get(
    "WESTERN_ASTROLOGY_DEFAULT_TIMEZONE", "Europe/Istanbul",
)
MAX_DAY_COUNT = 400

CRITICAL_TIGHT_ORB = 2.0
CRITICAL_ANGLE_ORB = 3.0
CRITICAL_SLOW_ANGLE_ORB = 5.0

SLOW_TRANSITS = ("jupiter", "saturn", "uranus", "neptune", "pluto")

NODE_IDS = ("north_node", "south_node")
ANGLE_IDS = ("ascendant", "descendant", "midheaven", "imum_coeli")

LUNAR_PHASE_NAMES_TR = {
    "new_moon": "Yeni Ay",
    "waxing_crescent": "Hilal (Büyüyen)",
    "first_quarter": "İlk Dördün",
    "waxing_gibbous": "Şişkin Ay (Büyüyen)",
    "full_moon": "Dolunay",
    "waning_gibbous": "Şişkin Ay (Küçülen)",
    "last_quarter": "Son Dördün",
    "waning_crescent": "Hilal (Küçülen)",
}

LUNAR_PHASE_PRIMARY = (
    (0.0, "new_moon", "Yeni Ay"),
    (90.0, "first_quarter", "İlk Dördün"),
    (180.0, "full_moon", "Dolunay"),
    (270.0, "last_quarter", "Son Dördün"),
)


def _lunar_phase_name(phase_angle: float) -> str:
    """Ay-Güneş faz açısı (0° yeni ay, 90° ilk dördün, 180° dolunay, 270° son dördün).
    Ana 4 faz ±6° penceresinde etiketlenir; diğerleri ara fazlar.
    """
    a = phase_angle % 360.0
    if a < 6.0 or a >= 354.0:
        return "new_moon"
    if a < 84.0:
        return "waxing_crescent"
    if a < 96.0:
        return "first_quarter"
    if a < 174.0:
        return "waxing_gibbous"
    if a < 186.0:
        return "full_moon"
    if a < 264.0:
        return "waning_gibbous"
    if a < 276.0:
        return "last_quarter"
    return "waning_crescent"


def _resolve_contact_threshold(transit_body_id: str, target_kind: str) -> float:
    """Bağlama göre orb eşiği:
    - gezegen ↔ gezegen: 2°
    - gezegen ↔ angle/node: 3°
    - yavaş gezegen (J/S/U/N/P) ↔ angle/node: 5° (uzun etki süresi)
    """
    if target_kind in ("angle", "node"):
        if transit_body_id in SLOW_TRANSITS:
            return CRITICAL_SLOW_ANGLE_ORB
        return CRITICAL_ANGLE_ORB
    return CRITICAL_TIGHT_ORB

MAJOR_ASPECT_ANGLES = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

# Pattern tanıma açıları (major + quincunx)
PATTERN_ASPECTS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "quincunx": 150.0,
    "opposition": 180.0,
}

PATTERN_ORB = 8.0  # Pattern aspect orb toleransi (Grand Trine için klasik 8°)
PATTERN_MIN_DURATION_DAYS = 3  # Pattern penceresi minimum süre (kısa gürültüyü filtrele)


PLANET_TR = {
    "sun": "Güneş",
    "moon": "Ay",
    "mercury": "Merkür",
    "venus": "Venüs",
    "mars": "Mars",
    "jupiter": "Jüpiter",
    "saturn": "Satürn",
    "uranus": "Uranüs",
    "neptune": "Neptün",
    "pluto": "Plüton",
    "chiron": "Şiron",
    "north_node": "KAD",
    "south_node": "GAD",
    "ascendant": "Yükselen",
    "descendant": "Düşen",
    "midheaven": "MC",
    "imum_coeli": "IC",
}

ASPECT_TR = {
    "conjunction": "Kavuşum",
    "opposition": "Karşıt",
    "square": "Kare",
    "trine": "Üçgen",
    "sextile": "Sekstil",
}


class TransitInputError(ValueError):
    """Transit hesaplama için geçersiz input."""


class TransitCalculationError(RuntimeError):
    """Transit hesaplama hatası."""


# ---------------------------------------------------------------------------
# Hesaplama yardımcıları
# ---------------------------------------------------------------------------


def _parse_date(value: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise TransitInputError(
            f"Geçersiz tarih (YYYY-MM-DD bekleniyor): {value}"
        ) from exc


def _validate_transit_input(payload: dict) -> tuple[date, date, str, int]:
    if not isinstance(payload, dict):
        raise TransitInputError("JSON gövdesi nesne olmalıdır")
    transit = payload.get("transit") or {}
    if not isinstance(transit, dict):
        raise TransitInputError("transit alanı nesne olmalıdır")

    start_str = transit.get("start_date")
    end_str = transit.get("end_date")
    if not start_str or not end_str:
        raise TransitInputError(
            "transit.start_date ve transit.end_date zorunludur (YYYY-MM-DD)"
        )

    start_date = _parse_date(start_str)
    end_date = _parse_date(end_str)
    if end_date < start_date:
        raise TransitInputError("transit.end_date başlangıçtan önce olamaz")

    day_count = (end_date - start_date).days + 1
    if day_count > MAX_DAY_COUNT:
        raise TransitInputError(
            f"Maksimum {MAX_DAY_COUNT} gün desteklenir, istenen: {day_count}"
        )

    transit_tz = str(transit.get("transit_timezone") or DEFAULT_TRANSIT_TIMEZONE)
    try:
        ZoneInfo(transit_tz)
    except ZoneInfoNotFoundError as exc:
        raise TransitInputError(
            f"Geçersiz transit.transit_timezone: {transit_tz}"
        ) from exc

    try:
        transit_hour = int(transit.get("transit_hour") or DEFAULT_TRANSIT_HOUR)
    except (TypeError, ValueError) as exc:
        raise TransitInputError("transit.transit_hour tam sayı olmalıdır") from exc
    if not 0 <= transit_hour <= 23:
        raise TransitInputError(
            "transit.transit_hour 0 ile 23 arasında olmalıdır"
        )

    return start_date, end_date, transit_tz, transit_hour


def _transit_jd(target_date: date, hour: int, timezone_id: str) -> float:
    tz = ZoneInfo(timezone_id)
    local_dt = datetime(
        target_date.year, target_date.month, target_date.day,
        hour, 0, 0, tzinfo=tz,
    )
    utc_dt = local_dt.astimezone(timezone.utc)
    return _julian_day(utc_dt)


def _planet_position(jd_ut: float, swe_id: int) -> tuple[float, float]:
    try:
        values, _ = swe.calc_ut(jd_ut, swe_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
    except swe.Error as exc:
        raise TransitCalculationError("Transit gezegen konumu hesaplanamadı") from exc
    longitude, _lat, _dist, speed_long, _spd_lat, _spd_dist = values
    return longitude % 360.0, speed_long


def _critical_contacts(
    transit_body_id: str,
    transit_longitude: float,
    natal_targets: list[dict],
) -> list[dict]:
    """Bir transit body ile natal targets arası kritik major açılar.

    Orb eşiği bağlama göre değişir (bkz. _resolve_contact_threshold).
    natal_targets: her biri {id, longitude, kind, sign_tr, house}. kind ∈ {planet, node, angle}.
    `restricted_transits` alanı varsa, sadece o transit body listesindeki id'ler taranır.
    """
    transit_pace = "slow" if transit_body_id in SLOW_TRANSITS else "fast"
    contacts = []
    for target in natal_targets:
        restricted = target.get("restricted_transits")
        if restricted is not None and transit_body_id not in restricted:
            continue
        target_kind = target.get("kind", "planet")
        threshold = _resolve_contact_threshold(transit_body_id, target_kind)
        separation = _shortest_separation(transit_longitude, target["longitude"])
        best = None
        for aspect_type, exact_angle in MAJOR_ASPECT_ANGLES.items():
            orb = abs(separation - exact_angle)
            if orb <= threshold and (best is None or orb < best[1]):
                best = (aspect_type, orb)
        if best:
            aspect_type, orb = best
            contacts.append({
                "transit": transit_body_id,
                "natal": target["id"],
                "kind": target_kind,
                "type": aspect_type,
                "orb": round(orb, 4),
                "natal_sign_tr": target.get("sign_tr"),
                "natal_house": target.get("house"),
                "transit_pace": transit_pace,
                "orb_threshold": threshold,
            })
    contacts.sort(key=lambda c: c["orb"])
    return contacts


def _transit_transit_contacts(
    transit_bodies: list[dict],
    threshold: float = CRITICAL_TIGHT_ORB,
) -> list[dict]:
    """Transit body çiftleri arası major aspect temasları (orb ≤ threshold).

    Kısıtlamalar:
    - Düğüm-düğüm çifti dahil edilmez (KAD-GAD sabit 180° oppositionda).
    - Self-conjunction yok (aynı body).
    """
    contacts = []
    for i in range(len(transit_bodies)):
        for j in range(i + 1, len(transit_bodies)):
            a = transit_bodies[i]
            b = transit_bodies[j]
            if a["id"] in NODE_IDS and b["id"] in NODE_IDS:
                continue
            separation = _shortest_separation(a["longitude"], b["longitude"])
            best = None
            for aspect_type, exact_angle in MAJOR_ASPECT_ANGLES.items():
                orb = abs(separation - exact_angle)
                if orb <= threshold and (best is None or orb < best[1]):
                    best = (aspect_type, orb)
            if best:
                aspect_type, orb = best
                contacts.append({
                    "from": a["id"],
                    "to": b["id"],
                    "type": aspect_type,
                    "orb": round(orb, 4),
                })
    contacts.sort(key=lambda c: c["orb"])
    return contacts


def _transit_node_position(jd_ut: float, node_type: str = "mean") -> tuple[float, float]:
    """Kuzey Düğüm (Mean veya True) longitude ve hızını döner."""
    swe_id = swe.TRUE_NODE if node_type == "true" else swe.MEAN_NODE
    try:
        values, _ = swe.calc_ut(jd_ut, swe_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
    except swe.Error as exc:
        raise TransitCalculationError("Transit düğüm konumu hesaplanamadı") from exc
    longitude, _lat, _dist, speed_long, _spd_lat, _spd_dist = values
    return longitude % 360.0, speed_long


def _resolve_detail_mode(period_type: str) -> str:
    """Period tipine göre ayrıntı modu: 'full' (kavuşak+düğüm+transit-transit dahil) veya 'core'."""
    return "full" if period_type in ("monthly", "three_month") else "core"


def _build_natal_targets(
    natal_planets: list[dict],
    natal_nodes: list[dict],
    natal_angles: dict,
    detail_mode: str,
) -> list[dict]:
    """Transit-natal temas hesabı için birleşik natal hedef listesi.

    detail_mode='full': gezegenler + düğümler + açı kavşakları (ASC/DSC/MC/IC).
    detail_mode='core': sadece gezegenler.
    """
    targets = []
    for planet in natal_planets:
        targets.append({
            "id": planet["id"],
            "longitude": planet["longitude"],
            "kind": "planet",
            "sign_tr": planet["sign_tr"],
            "house": planet["house"],
        })
    if detail_mode == "full":
        for node in natal_nodes:
            targets.append({
                "id": node["id"],
                "longitude": node["longitude"],
                "kind": "node",
                "sign_tr": node["sign_tr"],
                "house": node["house"],
            })
        for angle_id in ANGLE_IDS:
            a = natal_angles[angle_id]
            targets.append({
                "id": angle_id,
                "longitude": a["longitude"],
                "kind": "angle",
                "sign_tr": a["sign_tr"],
                "house": None,
            })
    else:
        # core mode: Jüpiter ve Satürn'ün ASC ve MC'ye teması her zaman görünsün.
        for angle_id in ("ascendant", "midheaven"):
            a = natal_angles[angle_id]
            targets.append({
                "id": angle_id,
                "longitude": a["longitude"],
                "kind": "angle",
                "sign_tr": a["sign_tr"],
                "house": None,
                "restricted_transits": ("jupiter", "saturn"),
            })
    return targets


def _profected_house_for_age(age: int) -> int:
    return (age % 12) + 1


def _current_age(birth_date: date, snapshot_date: date) -> int:
    age = snapshot_date.year - birth_date.year
    if (snapshot_date.month, snapshot_date.day) < (birth_date.month, birth_date.day):
        age -= 1
    return max(0, age)


def _classify_period(day_count: int) -> str:
    if day_count <= 31:
        return "monthly"
    if day_count <= 100:
        return "three_month"
    if day_count <= 200:
        return "six_month"
    return "annual"


def _period_label_tr(period_type: str) -> str:
    return {
        "monthly": "Aylık",
        "three_month": "3 Aylık",
        "six_month": "6 Aylık",
        "annual": "1 Yıllık",
    }.get(period_type, "Transit")


def _natal_summary_for(planet: dict | None) -> dict | None:
    if not planet:
        return None
    return {
        "id": planet["id"],
        "sign_tr": planet["sign_tr"],
        "degree_str": planet["degree_str"],
        "house": planet["house"],
    }


# ---------------------------------------------------------------------------
# Snapshot üretimi ve önemli olayların tespiti
# ---------------------------------------------------------------------------


def _build_snapshot(
    snapshot_date: date,
    jd_ut: float,
    natal_targets: list[dict],
    natal_cusps: list[float],
    natal_houses: list[dict],
    natal_planet_by_id: dict,
    birth_date: date,
    node_type: str,
    detail_mode: str,
) -> dict:
    transit_planets = []
    for planet_id, swe_id in TRANSIT_PLANET_IDS:
        longitude, speed = _planet_position(jd_ut, swe_id)
        deg_fields = _degree_fields(longitude)
        transit_planets.append({
            "id": planet_id,
            **deg_fields,
            "speed_longitude": round(speed, 8),
            "retrograde": speed < 0.0,
            "house": _house_number(longitude, natal_cusps),
        })

    nn_long, nn_speed = _transit_node_position(jd_ut, node_type)
    sn_long = (nn_long + 180.0) % 360.0
    transit_nodes = [
        {
            "id": "north_node",
            **_degree_fields(nn_long),
            "speed_longitude": round(nn_speed, 8),
            "retrograde": nn_speed < 0.0,
            "house": _house_number(nn_long, natal_cusps),
        },
        {
            "id": "south_node",
            **_degree_fields(sn_long),
            "speed_longitude": round(-nn_speed, 8),
            "retrograde": (-nn_speed) < 0.0,
            "house": _house_number(sn_long, natal_cusps),
        },
    ]

    if detail_mode == "full":
        transit_bodies_for_contacts = transit_planets + transit_nodes
    else:
        transit_bodies_for_contacts = transit_planets

    critical = []
    for tp in transit_bodies_for_contacts:
        critical.extend(_critical_contacts(
            tp["id"], tp["longitude"], natal_targets,
        ))
    critical.sort(key=lambda c: c["orb"])

    if detail_mode == "full":
        transit_transit = _transit_transit_contacts(transit_planets + transit_nodes)
    else:
        transit_transit = []

    sun_planet = next((p for p in transit_planets if p["id"] == "sun"), None)
    moon_planet = next((p for p in transit_planets if p["id"] == "moon"), None)
    if sun_planet and moon_planet:
        phase_angle = (moon_planet["longitude"] - sun_planet["longitude"]) % 360.0
        phase_key = _lunar_phase_name(phase_angle)
        lunar_phase = {
            "name": phase_key,
            "name_tr": LUNAR_PHASE_NAMES_TR[phase_key],
            "phase_angle": round(phase_angle, 4),
            "moon_sign_tr": moon_planet["sign_tr"],
            "sun_sign_tr": sun_planet["sign_tr"],
            "moon_house": moon_planet["house"],
            "sun_house": sun_planet["house"],
        }
    else:
        lunar_phase = None

    age = _current_age(birth_date, snapshot_date)
    profected_house_num = _profected_house_for_age(age)
    profected_house_row = natal_houses[profected_house_num - 1]
    profected_lord = CLASSICAL_RULERS[profected_house_row["sign_index"]]
    lord_planet = natal_planet_by_id.get(profected_lord, {})

    return {
        "date": snapshot_date.isoformat(),
        "age": age,
        "profection": {
            "house": profected_house_num,
            "sign_tr": profected_house_row["sign_tr"],
            "lord": profected_lord,
            "lord_natal_house": lord_planet.get("house"),
            "lord_natal_sign_tr": lord_planet.get("sign_tr"),
        },
        "planets": transit_planets,
        "transit_nodes": transit_nodes,
        "lunar_phase": lunar_phase,
        "critical_contacts": critical,
        "critical_count": len(critical),
        "transit_transit_contacts": transit_transit,
    }


def _detect_significant_events(snapshots: list[dict]) -> list[dict]:
    """Snapshot dizisinde tespit edilebilen olaylar:

    - Gezegen burç geçişi (Ay hariç — çok sık)
    - Retrograd/direkt station
    - Natal ev geçişi
    - Profection yaş geçişi
    """
    events = []
    if len(snapshots) < 2:
        return events

    for i in range(1, len(snapshots)):
        prev = snapshots[i - 1]
        curr = snapshots[i]
        prev_planets = {p["id"]: p for p in prev["planets"]}
        curr_planets = {p["id"]: p for p in curr["planets"]}

        for planet_id, curr_p in curr_planets.items():
            prev_p = prev_planets.get(planet_id)
            if not prev_p:
                continue

            # Ay her gün burç değiştirir — burç geçişlerinden dışla
            if planet_id != "moon" and prev_p["sign_index"] != curr_p["sign_index"]:
                events.append({
                    "date": curr["date"],
                    "type": "sign_ingress",
                    "planet": planet_id,
                    "from_sign_tr": prev_p["sign_tr"],
                    "to_sign_tr": curr_p["sign_tr"],
                })

            if not prev_p["retrograde"] and curr_p["retrograde"]:
                events.append({
                    "date": curr["date"],
                    "type": "retrograde_station",
                    "planet": planet_id,
                    "sign_tr": curr_p["sign_tr"],
                    "degree_str": curr_p["degree_str"],
                })

            if prev_p["retrograde"] and not curr_p["retrograde"]:
                events.append({
                    "date": curr["date"],
                    "type": "direct_station",
                    "planet": planet_id,
                    "sign_tr": curr_p["sign_tr"],
                    "degree_str": curr_p["degree_str"],
                })

            # Ay'ın ev değişimi de sık olur — dışla
            if planet_id != "moon" and prev_p["house"] != curr_p["house"]:
                events.append({
                    "date": curr["date"],
                    "type": "house_ingress",
                    "planet": planet_id,
                    "from_house": prev_p["house"],
                    "to_house": curr_p["house"],
                })

        # Profection değişimi
        if prev["profection"]["house"] != curr["profection"]["house"]:
            events.append({
                "date": curr["date"],
                "type": "profection_change",
                "from_house": prev["profection"]["house"],
                "to_house": curr["profection"]["house"],
                "new_lord": curr["profection"]["lord"],
                "new_lord_natal_house": curr["profection"]["lord_natal_house"],
                "new_age": curr["age"],
            })

    events.extend(_detect_lunar_phase_events(snapshots))
    return sorted(events, key=lambda e: (e["date"], e["type"]))


def _detect_lunar_phase_events(snapshots: list[dict]) -> list[dict]:
    """4 ana ay fazını (Yeni Ay / İlk Dördün / Dolunay / Son Dördün) lokal minimum ile tespit et."""
    if len(snapshots) < 3:
        return []
    events = []
    for target_angle, name, name_tr in LUNAR_PHASE_PRIMARY:
        distances = []
        for snap in snapshots:
            phase = (snap.get("lunar_phase") or {}).get("phase_angle", 0.0)
            diff = abs(((phase - target_angle + 180.0) % 360.0) - 180.0)
            distances.append(diff)
        for i in range(1, len(distances) - 1):
            if (
                distances[i] < distances[i - 1]
                and distances[i] < distances[i + 1]
                and distances[i] < 6.0
            ):
                snap = snapshots[i]
                lunar = snap.get("lunar_phase") or {}
                events.append({
                    "date": snap["date"],
                    "type": "lunar_phase",
                    "phase": name,
                    "phase_tr": name_tr,
                    "moon_sign_tr": lunar.get("moon_sign_tr"),
                    "moon_house": lunar.get("moon_house"),
                    "sun_sign_tr": lunar.get("sun_sign_tr"),
                    "sun_house": lunar.get("sun_house"),
                    "phase_angle": round(lunar.get("phase_angle", 0.0), 4),
                    "orb_to_exact": round(distances[i], 4),
                })
    events.sort(key=lambda e: e["date"])
    return events


def _compute_exact_aspect_dates(
    snapshots: list[dict],
    natal_targets: list[dict],
    min_orb_threshold: float = 1.0,
    track_radius: float = 5.0,
) -> list[dict]:
    """Snapshot dizisinde lokal minimum orb noktalarını exact tarih olarak listele.

    - Ay dışında tüm transit body'ler (gezegenler + düğümler eger snapshot'ta varsa)
    - natal_targets'taki tüm hedefler (planets / nodes / angles, detail_mode'a bağlı)
    - Sadece major aspect (kavuşum/karsit/kare/üçgen/sekstil)
    - Lokal minimum orb < min_orb_threshold olanları raporla
    """
    if len(snapshots) < 3:
        return []

    natal_by_id = {n["id"]: n for n in natal_targets}

    # Her (transit_id, natal_id, aspect_type) için (date, orb) listesi
    series: dict[tuple, list[tuple[str, float]]] = {}

    for snap in snapshots:
        transit_bodies = list(snap["planets"]) + list(snap.get("transit_nodes") or [])
        for tp in transit_bodies:
            if tp["id"] == "moon":
                continue
            for natal_id, natal in natal_by_id.items():
                restricted = natal.get("restricted_transits")
                if restricted is not None and tp["id"] not in restricted:
                    continue
                separation = _shortest_separation(
                    tp["longitude"], natal["longitude"]
                )
                for aspect_type, exact_angle in MAJOR_ASPECT_ANGLES.items():
                    orb = abs(separation - exact_angle)
                    if orb <= track_radius:
                        key = (tp["id"], natal_id, aspect_type)
                        series.setdefault(key, []).append((snap["date"], orb))

    events = []
    for key, sequence in series.items():
        if not sequence:
            continue
        transit_id, natal_id, aspect_type = key
        natal = natal_by_id[natal_id]

        if len(sequence) < 3:
            min_idx = min(range(len(sequence)), key=lambda i: sequence[i][1])
            if sequence[min_idx][1] < min_orb_threshold:
                events.append({
                    "exact_date": sequence[min_idx][0],
                    "transit": transit_id,
                    "natal": natal_id,
                    "kind": natal.get("kind", "planet"),
                    "type": aspect_type,
                    "min_orb": round(sequence[min_idx][1], 4),
                    "natal_sign_tr": natal.get("sign_tr"),
                    "natal_house": natal.get("house"),
                    "transit_pace": "slow" if transit_id in SLOW_TRANSITS else "fast",
                })
            continue

        for i in range(1, len(sequence) - 1):
            prev_orb = sequence[i - 1][1]
            curr_orb = sequence[i][1]
            next_orb = sequence[i + 1][1]
            if (
                curr_orb < prev_orb
                and curr_orb < next_orb
                and curr_orb < min_orb_threshold
            ):
                events.append({
                    "exact_date": sequence[i][0],
                    "transit": transit_id,
                    "natal": natal_id,
                    "kind": natal.get("kind", "planet"),
                    "type": aspect_type,
                    "min_orb": round(curr_orb, 4),
                    "natal_sign_tr": natal.get("sign_tr"),
                    "natal_house": natal.get("house"),
                    "transit_pace": "slow" if transit_id in SLOW_TRANSITS else "fast",
                })

    events.sort(key=lambda e: (e["exact_date"], e["transit"], e["natal"]))
    return events


def _compute_intensity_windows(exact_aspects: list[dict]) -> list[dict]:
    """Exact aspect listesinden 2+ exact içeren günleri (yoğun günler) türet.

    Her giriş: tarih, toplam sayı, yavaş gezegen sayısı, yavaş transit listesi, exact olayları.
    """
    if not exact_aspects:
        return []
    by_date: dict[str, list[dict]] = {}
    for ev in exact_aspects:
        by_date.setdefault(ev["exact_date"], []).append(ev)

    hot_days = []
    for date_str in sorted(by_date.keys()):
        events_for_date = by_date[date_str]
        if len(events_for_date) < 2:
            continue
        slow_events = [
            e for e in events_for_date if e["transit"] in SLOW_TRANSITS
        ]
        slow_transits = sorted({e["transit"] for e in slow_events})
        hot_days.append({
            "date": date_str,
            "count": len(events_for_date),
            "slow_count": len(slow_events),
            "slow_transits": slow_transits,
            "events": events_for_date,
        })
    return hot_days


# ---------------------------------------------------------------------------
# Transit-Natal Pattern Tanıma (Kite, Grand Trine, T-Kare, Yod, Grand Cross)
# ---------------------------------------------------------------------------


def _pattern_aspect_between(
    long_a: float, long_b: float, orb: float = PATTERN_ORB,
) -> tuple[str, float] | None:
    """İki nokta arası PATTERN_ASPECTS içinden en yakın açıyı döner (orb ≤ orb_tol)."""
    sep = _shortest_separation(long_a, long_b)
    best = None
    for name, angle in PATTERN_ASPECTS.items():
        o = abs(sep - angle)
        if o <= orb and (best is None or o < best[1]):
            best = (name, o)
    return best


def _pattern_points(snapshot: dict, natal_targets: list[dict]) -> list[dict]:
    """Pattern tanıma için tüm natal + transit noktaları birleşik liste.

    Transit Ay hızlı hareket ettiği için (12°/gün) pattern signature stabilitesini bozar; dışında bırakılır.
    Natal Ay dahil edilir (sabit).
    """
    points = []
    for nt in natal_targets:
        # core mode'da restricted_transits kısıtlı ASC/MC pattern için dahil edilmemeli
        if nt.get("restricted_transits"):
            continue
        points.append({
            "id": f"n.{nt['id']}",
            "label": f"n.{_planet_tr(nt['id'])}",
            "longitude": nt["longitude"],
            "source": "natal",
        })
    for tp in snapshot["planets"]:
        if tp["id"] == "moon":
            continue
        points.append({
            "id": f"t.{tp['id']}",
            "label": f"t.{_planet_tr(tp['id'])}",
            "longitude": tp["longitude"],
            "source": "transit",
        })
    for tn in (snapshot.get("transit_nodes") or []):
        points.append({
            "id": f"t.{tn['id']}",
            "label": f"t.{_planet_tr(tn['id'])}",
            "longitude": tn["longitude"],
            "source": "transit",
        })
    return points


def _detect_patterns_for_snapshot(
    snapshot: dict, natal_targets: list[dict], orb: float = PATTERN_ORB,
) -> list[dict]:
    """Tek bir snapshot için karışık (transit + natal) major kompozit kalıpları tespit et."""
    points = _pattern_points(snapshot, natal_targets)
    n = len(points)
    aspects: dict[tuple[int, int], tuple[str, float]] = {}
    for i in range(n):
        for j in range(i + 1, n):
            asp = _pattern_aspect_between(
                points[i]["longitude"], points[j]["longitude"], orb,
            )
            if asp:
                aspects[(i, j)] = asp

    def has(i: int, j: int, kind: str) -> bool:
        a, b = (i, j) if i < j else (j, i)
        ent = aspects.get((a, b))
        return ent is not None and ent[0] == kind

    def is_mixed(indices) -> bool:
        srcs = {points[i]["source"] for i in indices}
        return "natal" in srcs and "transit" in srcs

    patterns = []
    seen: set = set()

    def add_pattern(
        ptype: str, type_tr: str, member_indices: tuple, apex_idx: int | None = None,
    ) -> None:
        all_idx = tuple(member_indices) + ((apex_idx,) if apex_idx is not None else ())
        if not is_mixed(all_idx):
            return
        key = (ptype, frozenset(all_idx))
        if key in seen:
            return
        seen.add(key)
        entry = {
            "type": ptype,
            "type_tr": type_tr,
            "members": [points[i]["id"] for i in member_indices],
            "member_labels": [points[i]["label"] for i in member_indices],
        }
        if apex_idx is not None:
            entry["apex"] = points[apex_idx]["id"]
            entry["apex_label"] = points[apex_idx]["label"]
        patterns.append(entry)

    # Grand Trine + Kite
    for i in range(n):
        for j in range(i + 1, n):
            if not has(i, j, "trine"):
                continue
            for k in range(j + 1, n):
                if has(i, k, "trine") and has(j, k, "trine"):
                    add_pattern("grand_trine", "Büyük Üçgen", (i, j, k))
                    # Kite kontrol: 4. apex 1 opposition + 2 sextile
                    for m in range(n):
                        if m in (i, j, k):
                            continue
                        opps = sum(1 for x in (i, j, k) if has(m, x, "opposition"))
                        sexs = sum(1 for x in (i, j, k) if has(m, x, "sextile"))
                        if opps == 1 and sexs == 2:
                            add_pattern("kite", "Uçurtma", (i, j, k), apex_idx=m)

    # T-Kare
    for (i, j), v in aspects.items():
        if v[0] != "opposition":
            continue
        for k in range(n):
            if k in (i, j):
                continue
            if has(i, k, "square") and has(j, k, "square"):
                add_pattern("t_square", "T-Kare", (i, j), apex_idx=k)

    # Yod
    for (i, j), v in aspects.items():
        if v[0] != "sextile":
            continue
        for k in range(n):
            if k in (i, j):
                continue
            if has(i, k, "quincunx") and has(j, k, "quincunx"):
                add_pattern("yod", "Yod (Tanrı Parmağı)", (i, j), apex_idx=k)

    # Grand Cross
    opp_pairs = [(i, j) for (i, j), v in aspects.items() if v[0] == "opposition"]
    for a_idx in range(len(opp_pairs)):
        i, j = opp_pairs[a_idx]
        for b_idx in range(a_idx + 1, len(opp_pairs)):
            k, m = opp_pairs[b_idx]
            if k in (i, j) or m in (i, j):
                continue
            if (
                has(i, k, "square") and has(i, m, "square")
                and has(j, k, "square") and has(j, m, "square")
            ):
                add_pattern("grand_cross", "Büyük Haç", (i, j, k, m))

    return patterns


def _compute_pattern_windows(
    snapshots: list[dict],
    natal_targets: list[dict],
    orb: float = PATTERN_ORB,
    min_duration_days: int = PATTERN_MIN_DURATION_DAYS,
) -> list[dict]:
    """Her snapshot için pattern tara, aynı pattern'in ardışık günlerini birleştir."""
    timeline: dict[tuple, list[str]] = {}
    pattern_meta: dict[tuple, dict] = {}

    for snap in snapshots:
        patterns = _detect_patterns_for_snapshot(snap, natal_targets, orb)
        for p in patterns:
            members = tuple(sorted(p["members"]))
            apex = p.get("apex")
            sig = (p["type"], members, apex)
            timeline.setdefault(sig, []).append(snap["date"])
            if sig not in pattern_meta:
                pattern_meta[sig] = p

    windows = []
    for sig, dates in timeline.items():
        dates_sorted = sorted(dates)
        groups = []
        current = [dates_sorted[0]]
        for d in dates_sorted[1:]:
            prev_date = _parse_date(current[-1])
            curr_date = _parse_date(d)
            if (curr_date - prev_date).days <= 1:
                current.append(d)
            else:
                groups.append(current)
                current = [d]
        groups.append(current)

        meta = pattern_meta[sig]
        for group in groups:
            if len(group) < min_duration_days:
                continue
            windows.append({
                "type": meta["type"],
                "type_tr": meta["type_tr"],
                "members": meta["member_labels"],
                "apex": meta.get("apex_label"),
                "start": group[0],
                "end": group[-1],
                "day_count": len(group),
            })

    # Önce süre/önem sıralaması: uzun süreli (yavaş tetik) üstte
    windows.sort(key=lambda w: (-w["day_count"], w["start"], w["type"]))
    return windows


def _sr_years_in_period(
    natal_birth_date: str, start: date, end: date,
) -> list[int]:
    """Period boyunca aktif Solar Return yıllarının listesi.

    Period başında aktif SR = son geçilmiş doğum günü.
    Period içinde yeni doğum günü geçerse o yılın SR'ı da eklenir.
    29 Şubat doğumlular için artık olmayan yıllarda 28 Şubat'a kaydırılır.
    """
    _, natal_month, natal_day = (int(part) for part in natal_birth_date.split("-"))

    def birthday_in(year: int) -> date:
        try:
            return date(year, natal_month, natal_day)
        except ValueError:
            return date(year, natal_month, 28)

    # Period başlangıcında aktif SR yılı
    sr_year = start.year if birthday_in(start.year) <= start else start.year - 1
    years = [sr_year]

    # Period içinde yeni doğum günü geçerse o yılları da ekle
    next_year = sr_year + 1
    while birthday_in(next_year) <= end:
        years.append(next_year)
        next_year += 1

    return years


# ---------------------------------------------------------------------------
# Ana hesaplama fonksiyonu
# ---------------------------------------------------------------------------


def calculate_transit_period(
    payload: dict,
    natal_chart: dict | None = None,
) -> dict:
    """Verilen tarih aralığı için günlük transit snapshot listesi üret."""
    start_date, end_date, transit_tz, transit_hour = _validate_transit_input(payload)

    natal = natal_chart or calculate_core_chart(payload)
    natal_planets = natal["planets"]["items"]
    natal_nodes = natal["nodes"]["items"]
    natal_angles = natal["angles"]
    natal_cusps = [h["longitude"] for h in natal["houses"]["items"]]
    natal_houses = natal["houses"]["items"]
    natal_planet_by_id = {p["id"]: p for p in natal_planets}
    house_system = natal["meta"]["house_system"]
    node_type = natal["meta"]["node_type"]

    birth_date_str = natal["birth"]["date"]
    birth_date = _parse_date(birth_date_str)

    day_count = (end_date - start_date).days + 1
    period_type = _classify_period(day_count)
    detail_mode = _resolve_detail_mode(period_type)
    natal_targets = _build_natal_targets(
        natal_planets, natal_nodes, natal_angles, detail_mode,
    )

    snapshots = []
    current = start_date
    while current <= end_date:
        jd = _transit_jd(current, transit_hour, transit_tz)
        snapshots.append(_build_snapshot(
            current, jd, natal_targets, natal_cusps, natal_houses,
            natal_planet_by_id, birth_date, node_type, detail_mode,
        ))
        current += timedelta(days=1)

    events = _detect_significant_events(snapshots)
    exact_aspects = _compute_exact_aspect_dates(snapshots, natal_targets)
    intensity_windows = _compute_intensity_windows(exact_aspects)
    pattern_windows = _compute_pattern_windows(snapshots, natal_targets)

    # Solar Return(s) for the period
    sr_years = _sr_years_in_period(birth_date_str, start_date, end_date)
    solar_returns = []
    for sr_year in sr_years:
        try:
            sr_payload = {**payload, "return_year": sr_year}
            sr_data = calculate_solar_return(sr_payload, natal_chart=natal)
            solar_returns.append(sr_data)
        except SolarReturnError:
            continue

    return {
        "status": "available",
        "version": "0.6.0",
        "person_name": (
            (natal.get("birth", {}).get("person") or {}).get("name")
            or (payload.get("person") or {}).get("name")
        ),
        "period": {
            "type": period_type,
            "label_tr": _period_label_tr(period_type),
            "start_date": start_date.isoformat(),
            "end_date": end_date.isoformat(),
            "day_count": day_count,
            "transit_hour": transit_hour,
            "transit_timezone": transit_tz,
            "cadence": "daily_snapshot",
            "detail_mode": detail_mode,
            "node_type": node_type,
        },
        "natal_summary": {
            "ascendant_sign_tr": natal["angles"]["ascendant"]["sign_tr"],
            "midheaven_sign_tr": natal["angles"]["midheaven"]["sign_tr"],
            "sun": _natal_summary_for(natal_planet_by_id.get("sun")),
            "moon": _natal_summary_for(natal_planet_by_id.get("moon")),
            "house_system": house_system,
            "birth_date": birth_date_str,
        },
        "snapshots": snapshots,
        "significant_events": events,
        "exact_aspects": exact_aspects,
        "intensity_windows": intensity_windows,
        "pattern_windows": pattern_windows,
        "solar_returns": solar_returns,
        "limitations": [
            "Lunar Return dahil değildir; ileri sürümde eklenecek.",
        ],
    }


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def _planet_tr(planet_id: str | None) -> str:
    if not planet_id:
        return "-"
    return PLANET_TR.get(planet_id, planet_id)


def _aspect_tr(aspect_type: str | None) -> str:
    if not aspect_type:
        return "-"
    return ASPECT_TR.get(aspect_type, aspect_type)


def _md_value(value) -> str:
    if value is None:
        return ""
    if isinstance(value, bool):
        return "Evet" if value else "Hayır"
    if isinstance(value, list):
        return ", ".join(str(item) for item in value)
    return str(value).replace("|", "\\|").replace("\n", " ")


def _md_table(headers: list[str], rows: list[tuple]) -> str:
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    for row in rows:
        lines.append("| " + " | ".join(_md_value(cell) for cell in row) + " |")
    return "\n".join(lines)


def _format_planet_cell(planet: dict) -> str:
    """Tek gezegen için tek hücre özeti: 'Boğa 17°25, ev 3 R'"""
    r_flag = " R" if planet.get("retrograde") else ""
    return f"{planet['sign_tr']} {planet['degree_str']}, e{planet['house']}{r_flag}"


def _format_critical_contacts(contacts: list[dict]) -> str:
    """Bir snapshot'taki tüm transit-natal temasları hücreye sığan tek string olarak format.

    Yavaş gezegen (J/S/U/N/P) transitleri başında ★ işareti ile vurgulanır.
    """
    parts = []
    for c in contacts:
        pace_flag = "★" if c.get("transit_pace") == "slow" else ""
        parts.append(
            f"{pace_flag}t.{_planet_tr(c['transit'])} {_aspect_tr(c['type'])} "
            f"n.{_planet_tr(c['natal'])} ({c['orb']:.2f}°)"
        )
    return "; ".join(parts) if parts else "-"


def _format_transit_transit_contacts(contacts: list[dict]) -> str:
    """Bir snapshot'taki transit body çiftleri arası temasları string format.

    Her iki taraf yavaş gezegense başında ★ işareti.
    """
    parts = []
    for c in contacts:
        both_slow = (c["from"] in SLOW_TRANSITS and c["to"] in SLOW_TRANSITS)
        pace_flag = "★" if both_slow else ""
        parts.append(
            f"{pace_flag}t.{_planet_tr(c['from'])} {_aspect_tr(c['type'])} "
            f"t.{_planet_tr(c['to'])} ({c['orb']:.2f}°)"
        )
    return "; ".join(parts) if parts else "-"


def _format_profection(prof: dict) -> str:
    return (
        f"yaş {prof.get('age', '?')}: e{prof['house']} ({prof['sign_tr']}); "
        f"lord {_planet_tr(prof['lord'])} → e{prof.get('lord_natal_house', '?')}"
    )


def _daily_table_rows(period_data: dict) -> list[tuple]:
    detail_mode = period_data.get("period", {}).get("detail_mode", "core")
    rows = []
    for snap in period_data.get("snapshots") or []:
        planets = {p["id"]: p for p in snap["planets"]}
        row = [
            snap["date"],
            f"e{snap['profection']['house']} / {_planet_tr(snap['profection']['lord'])}",
            _format_planet_cell(planets["moon"]),
            _format_planet_cell(planets["sun"]),
            _format_planet_cell(planets["mercury"]),
            _format_planet_cell(planets["venus"]),
            _format_planet_cell(planets["mars"]),
            _format_planet_cell(planets["jupiter"]),
            _format_planet_cell(planets["saturn"]),
            _format_planet_cell(planets["uranus"]),
            _format_planet_cell(planets["neptune"]),
            _format_planet_cell(planets["pluto"]),
            _format_critical_contacts(snap["critical_contacts"]),
        ]
        if detail_mode == "full":
            row.append(
                _format_transit_transit_contacts(
                    snap.get("transit_transit_contacts") or []
                )
            )
        rows.append(tuple(row))
    return rows


def _event_label(event: dict) -> str:
    et = event["type"]
    if et == "sign_ingress":
        return (
            f"{_planet_tr(event['planet'])} burç geçişi: "
            f"{event['from_sign_tr']} → {event['to_sign_tr']}"
        )
    if et == "retrograde_station":
        return (
            f"{_planet_tr(event['planet'])} retrograd başlangıç "
            f"({event['sign_tr']} {event['degree_str']})"
        )
    if et == "direct_station":
        return (
            f"{_planet_tr(event['planet'])} direkte dönüş "
            f"({event['sign_tr']} {event['degree_str']})"
        )
    if et == "house_ingress":
        return (
            f"{_planet_tr(event['planet'])} natal ev geçişi: "
            f"e{event['from_house']} → e{event['to_house']}"
        )
    if et == "profection_change":
        return (
            f"Profection değişimi: yaş {event['new_age']} → "
            f"e{event['to_house']} ({_planet_tr(event['new_lord'])} lord, "
            f"natal e{event.get('new_lord_natal_house', '?')})"
        )
    if et == "lunar_phase":
        moon_loc = (
            f"{event.get('moon_sign_tr', '-')} e{event.get('moon_house', '-')}"
        )
        sun_loc = (
            f"{event.get('sun_sign_tr', '-')} e{event.get('sun_house', '-')}"
        )
        return (
            f"{event['phase_tr']} (Ay {moon_loc} / Güneş {sun_loc}, "
            f"orb {event.get('orb_to_exact', 0):.2f}°)"
        )
    return et


def _events_table_rows(period_data: dict) -> list[tuple]:
    rows = []
    for ev in period_data.get("significant_events") or []:
        rows.append((ev["date"], ev["type"], _event_label(ev)))
    return rows


def _exact_aspects_rows(period_data: dict) -> list[tuple]:
    rows = []
    for ev in period_data.get("exact_aspects") or []:
        pace_flag = "★" if ev.get("transit_pace") == "slow" else ""
        rows.append((
            ev["exact_date"],
            f"{pace_flag}{_planet_tr(ev['transit'])}",
            _aspect_tr(ev["type"]),
            _planet_tr(ev["natal"]),
            f"{ev['min_orb']:.2f}°",
            f"e{ev.get('natal_house', '?')} {ev.get('natal_sign_tr', '')}",
        ))
    return rows


def _intensity_windows_rows(period_data: dict) -> list[tuple]:
    rows = []
    for hd in period_data.get("intensity_windows") or []:
        slow_tr = (
            ", ".join(_planet_tr(s) for s in hd["slow_transits"])
            if hd["slow_transits"] else "yok"
        )
        summary_parts = []
        for e in hd["events"]:
            pace_flag = "★" if e.get("transit_pace") == "slow" else ""
            summary_parts.append(
                f"{pace_flag}t.{_planet_tr(e['transit'])} {_aspect_tr(e['type'])} "
                f"n.{_planet_tr(e['natal'])} ({e['min_orb']:.2f}°)"
            )
        rows.append((
            hd["date"],
            hd["count"],
            f"{hd['slow_count']} ({slow_tr})" if hd["slow_count"] else "0",
            "; ".join(summary_parts),
        ))
    return rows


def _pattern_windows_rows(period_data: dict) -> list[tuple]:
    rows = []
    for w in period_data.get("pattern_windows") or []:
        members_str = ", ".join(w["members"])
        apex_str = w.get("apex") or "-"
        rows.append((
            w["type_tr"],
            members_str,
            apex_str,
            w["start"],
            w["end"],
            w["day_count"],
        ))
    return rows


def build_transit_markdown(
    period_data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
    house_system: str | None = None,
) -> str:
    """Vedik tarzı transit raporu için Markdown çıktısı."""
    period = period_data["period"]
    natal = period_data["natal_summary"]
    label = period["label_tr"]
    start = period["start_date"]
    end = period["end_date"]
    detail_mode = period.get("detail_mode", "core")
    node_type = period.get("node_type", "mean")

    fm_lines = [
        "---",
        f'title: "{person_name} - {label} Transit {start} - {end}"',
        'type: "transit_pack"',
        'source: "western_api_v2_transit"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'period: "{period["type"]}"',
        f'range_start: "{start}"',
        f'range_end: "{end}"',
        f'cadence: "{period["cadence"]}"',
        f'day_count: {period["day_count"]}',
        f'transit_hour: {period["transit_hour"]}',
        f'transit_timezone: "{period["transit_timezone"]}"',
        f'detail_mode: "{detail_mode}"',
        f'node_type: "{node_type}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    if house_system:
        fm_lines.append(f'house_system: "{house_system}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append('engine_version: "0.6.0"')
    fm_lines.append("---")
    fm_lines.append("")

    intro = [
        f"# {person_name} - {label} Transit {start} - {end}",
        "",
        "## Teknik Kullanım Notu",
        "",
        "- Bu dosya API tarafından üretilmiş teknik transit veri paketidir.",
        "- Bu çıktı ham teknik veri paketidir; yorum veya öngörü metni değildir.",
        "- Kullanıcı belirli gün sayısı isterse sadece ilgili tarih satırları ve detayları kullanılmalıdır.",
        "- Veri yoksa veya sınırlı ise açıkça belirtilmelidir.",
        "",
    ]

    sun_summary = natal.get("sun") or {}
    moon_summary = natal.get("moon") or {}
    period_overview = [
        "## Dönem Özeti",
        "",
        f"- Dönem tipi: {period['type']} ({label})",
        f"- Tarih aralığı: {start} → {end}",
        f"- Örnekleme: {period['cadence']}",
        f"- Kayıt/snapshot sayısı: {period['day_count']}",
        f"- Transit saati: {period['transit_hour']:02d}:00",
        f"- Transit saat dilimi: {period['transit_timezone']}",
        f"- Ev sistemi: {natal.get('house_system', '-')}",
        f"- Düğüm tipi: {node_type}",
        f"- Ayrıntı modu: {detail_mode} ("
        + ("düğüm + açı + transit-transit dahil" if detail_mode == "full" else "sadece transit-natal gezegen")
        + ")",
        f"- Natal Yükselen: {natal.get('ascendant_sign_tr', '-')}",
        f"- Natal MC: {natal.get('midheaven_sign_tr', '-')}",
        (
            f"- Natal Güneş: {sun_summary.get('sign_tr', '-')} "
            f"{sun_summary.get('degree_str', '')}, ev "
            f"{sun_summary.get('house', '-')}"
        ),
        (
            f"- Natal Ay: {moon_summary.get('sign_tr', '-')} "
            f"{moon_summary.get('degree_str', '')}, ev "
            f"{moon_summary.get('house', '-')}"
        ),
        f"- Doğum tarihi: {natal.get('birth_date', '-')}",
        "",
    ]

    guide = [
        "## Transit Veri Paketi Kılavuzu",
        "",
        "### Teknik Okuma Sınırı",
        "",
        "- Bu dosya hesaplama kaynağıdır; ek transit veya gezegen konumu üretmez.",
        "- Kullanıcı bir tarih aralığı verirse yalnızca o aralıktaki Günlük Özet satırları kullanılmalıdır.",
        "- Analiz dili ilişki/iş/para/sağlık gibi konuya göre değişebilir; veri kullanım sırası değişmez.",
        "",
        "### Kullanım Sırası",
        "",
        "1. Önce Dönem Özeti'nden tarih aralığı, snapshot sayısı, transit saati ve saat dilimini oku.",
        "2. Sonra istenen tarih veya tarih aralığı için Günlük Özet Tablosu'ndaki satırları seç.",
        "3. Ana zaman çerçevesi için Profection kolonunu kullan: aktif ev + lord + lordun natal konumu.",
        "4. Yavaş gezegenleri (Jüpiter, Satürn, Uranüs, Neptün, Plüton) trendi belirleyici olarak oku.",
        "5. Hızlı gezegenleri (Güneş, Merkür, Venüs, Mars) tetik olarak; Ay günlük zamanlama olarak oku.",
        "6. Natal Temaslar kolonu orb eşiği bağlama göre değişir: gezegen↔gezegen 2°, gezegen↔angle/düğüm 3°, yavaş gezegen↔angle/düğüm 5°. "
        "Yavaş gezegen (J/S/U/N/P) transitleri ★ ile işaretlenir; uzun süre etkilidir. "
        "Full modda transit düğümler + natal düğümler + ASC/DSC/MC/IC dahil; core modda sadece transit gezegen ↔ natal gezegen "
        "artı Jüpiter ve Satürn'ün natal ASC + MC ile temasları.",
        "7. Full modda ek bir Transit-Transit kolonu vardır; o günkü transit body çiftleri arası orb ≤2° majör açılar.",
        "8. Önemli Olaylar bölümünde burç geçişleri, retrograd/direkt stations, ev geçişleri, profection değişimleri ve ay fazları (Yeni Ay/İlk Dördün/Dolunay/Son Dördün) toplu listelenir.",
        "9. Yoğun Açı Günleri tablosu aynı güne düşen 2+ exact açıları ve yavaş tetik varını gösterir; yorum için en öncelikli günlerdir.",
        "10. Aktif Pattern Pencereleri tablosu transit+natal kompozit şekilleri (Büyük Üçgen, Uçurtma, T-Kare, Yod, Büyük Haç) ve aktif oldukları tarih aralıklarını gösterir; orb 8°, minimum süre 3 gün (kısa Ay-tetikli kalıplar dışlanmış).",
        "11. Yıl Dönüm Haritaları (Solar Return) bölümü dönem boyunca aktif SR harita(lar)ını içerir. SR Yükselen/MC'nin natal evi yılın vurgusu, SR gezegenlerinin natal evlere düşüşü yıl boyunca aktif natal alanları gösterir.",
        "",
        "### Hüküm Kuralları",
        "",
        "- Tek göstergeyle kesin hüküm verme; profection, transit yavaş gezegen ve sıkı temas birlikte destekliyorsa daha net konuş.",
        "- Profection ana yıllık çerçevedir; transitler bu çerçeveyi zamanlar ve görünür hale getirir.",
        "- Yavaş gezegenler aylık ve uzun dönem yorumda; Ay ve hızlılar günlük yorumda daha ağırlıklıdır.",
        "- Eksik veri varsa açıkça söyle; dosyada olmayan kuralı veya hesaplamayı uydurma.",
        "",
    ]

    daily_headers = [
        "Tarih",
        "Profection",
        "Ay",
        "Güneş",
        "Merkür",
        "Venüs",
        "Mars",
        "Jüpiter",
        "Satürn",
        "Uranüs",
        "Neptün",
        "Plüton",
        "Natal Temaslar (orb ≤2°)",
    ]
    if detail_mode == "full":
        daily_headers.append("Transit-Transit (orb ≤2°)")
    daily_table = _md_table(daily_headers, _daily_table_rows(period_data))
    daily_section = [
        "## Günlük Özet Tablosu",
        "",
        daily_table,
        "",
    ]

    events_rows = _events_table_rows(period_data)
    if events_rows:
        events_table = _md_table(
            ["Tarih", "Tip", "Açıklama"],
            events_rows,
        )
    else:
        events_table = "_Bu aralıkta tespit edilen önemli olay yok._"
    events_section = [
        "## Önemli Transit Olayları",
        "",
        events_table,
        "",
    ]

    exact_rows = _exact_aspects_rows(period_data)
    if exact_rows:
        exact_table = _md_table(
            ["Tarih", "Transit", "Açı", "Natal", "Min Orb", "Natal Konum"],
            exact_rows,
        )
    else:
        exact_table = "_Bu aralıkta exact'e yaklaşan (orb <1°) majör açı tespit edilmedi._"
    exact_aspects_section = [
        "## Exact Açı Tarihleri",
        "",
        f"_Transit-natal majör açıların orb minimum'a düştüğü (yaklaşık exact) gün(ler). Ay hariç. Toplam: {len(exact_rows)}._",
        "",
        exact_table,
        "",
    ]

    intensity_rows = _intensity_windows_rows(period_data)
    if intensity_rows:
        intensity_table = _md_table(
            ["Tarih", "Exact Sayısı", "Yavaş Tetik", "Açı Özeti"],
            intensity_rows,
        )
    else:
        intensity_table = "_Bu aralıkta 2+ exact içeren yoğun gün tespit edilmedi._"
    intensity_section = [
        "## Yoğun Açı Günleri (2+ Exact)",
        "",
        "_Aynı güne düşen birden fazla exact majör açı; yavaş gezegen (J/S/U/N/P) tetiklediğinde belirleyici kabul edilir._",
        "",
        intensity_table,
        "",
    ]

    pattern_rows = _pattern_windows_rows(period_data)
    if pattern_rows:
        pattern_table = _md_table(
            ["Pattern", "Üyeler", "Apex", "Başlangıç", "Bitiş", "Süre (gün)"],
            pattern_rows,
        )
    else:
        pattern_table = "_Bu aralıkta karışık (transit + natal) pattern tespit edilmedi._"
    pattern_section = [
        "## Aktif Transit-Natal Pattern Pencereleri",
        "",
        "_Major kompozit şekiller (Büyük Üçgen / Uçurtma / T-Kare / Yod / Büyük Haç), orb toleransı 8°. "
        "Sadece karışık (transit + natal) kalıplar ve en az 3 gün sürenler; saf natal pattern'lar natal raporda var. "
        "Transit Ay hızlı olduğu için pattern hesabından dışlanmıştır. "
        "Süre kolonu uzunsa yavaş gezegen tetiklemiş olabilir; uzun-süreli kalıplar yorum için öncelikli.",
        "",
        pattern_table,
        "",
    ]

    sr_list = period_data.get("solar_returns") or []
    sr_section: list[str] = []
    if sr_list:
        sr_section = [
            "## Yıl Dönüm Haritaları (Solar Return)",
            "",
            f"_Dönem boyunca aktif {len(sr_list)} Solar Return harita(sı). "
            "Her SR'nın natal Yükselen/MC ile kavuşumdaki gezegenleri yılın baş temasıdır. "
            "Transit ile birlikte okunur; tek başına kullanılmaz._",
            "",
        ]
        for sr_data in sr_list:
            sr_section.append(
                build_solar_return_markdown(sr_data, embedded=True).rstrip()
            )
            sr_section.append("")

    limitations = period_data.get("limitations") or []
    limit_section = []
    if limitations:
        limit_section = [
            "## Sınırlamalar",
            "",
            *[f"- {item}" for item in limitations],
            "",
        ]

    return "\n".join([
        *fm_lines,
        *intro,
        *period_overview,
        *guide,
        *daily_section,
        *events_section,
        *exact_aspects_section,
        *intensity_section,
        *pattern_section,
        *sr_section,
        *limit_section,
    ])
