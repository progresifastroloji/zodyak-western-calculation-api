#!/usr/bin/env python3
"""Secondary progressions calculations and markdown render.

Secondary progressions ilkesi: 1 gün = 1 yıl. Doğum anından N yıl sonrası
için doğumdan N gün sonraki ephemeris konumları progressed chart'ı oluşturur.

Hesap akışı:
- progressed_jd_ut = birth_jd_ut + age_in_solar_years (gün cinsinden eklenir).
- Progressed gezegen konumları progressed_jd_ut'da Swiss Ephemeris ile hesaplanır.
- Progressed evler ve açı kavşakları aynı doğum koordinatı + aynı ev sistemi
  için progressed_jd_ut'da yeniden hesaplanır (natural secondary).
- Progressed → Natal majör açılar sıkı orb ile listelenir.
- Progressed Sun-Moon arası faz Rudhyar tarzı 8 evreli secondary lunation
  döngüsüyle etiketlenir.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart yardımcılarını
ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    PLANETS,
    SIGNS,
    _body_position,
    _calculate_houses,
    _degree_fields,
    _house_number,
    _julian_day,
    _shortest_separation,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


PROGRESSION_ASPECTS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

# Progressed teknikte transit'ten çok daha sıkı orb kullanılır; klasik değer 1°.
PROGRESSED_ORB_MAJOR = 1.0
PROGRESSED_ORB_LUMINARY_BONUS = 0.5  # Sun/Moon için ek tolerans

SECONDARY_LUNATION_PHASES = [
    (0.0, 45.0, "new_moon", "Yeni Ay Fazı"),
    (45.0, 90.0, "crescent", "Hilal Fazı"),
    (90.0, 135.0, "first_quarter", "İlk Dördün Fazı"),
    (135.0, 180.0, "gibbous", "Şişkin Faz"),
    (180.0, 225.0, "full_moon", "Dolunay Fazı"),
    (225.0, 270.0, "disseminating", "Yayılma Fazı"),
    (270.0, 315.0, "last_quarter", "Son Dördün Fazı"),
    (315.0, 360.0, "balsamic", "Balsamic Fazı"),
]

ASPECT_TR = {
    "conjunction": "Kavuşum",
    "opposition": "Karşıt",
    "square": "Kare",
    "trine": "Üçgen",
    "sextile": "Sekstil",
}

DEFAULT_REFERENCE_TIMEZONE = "Europe/Istanbul"
TROPICAL_YEAR_DAYS = 365.2422  # ortalama tropik yıl

LUMINARIES = {"sun", "moon"}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class ProgressionsInputError(ValueError):
    """Progressions hesaplama için geçersiz input."""


class ProgressionsCalculationError(RuntimeError):
    """Progressions hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _parse_target_date(value: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise ProgressionsInputError(
            f"Geçersiz tarih (YYYY-MM-DD bekleniyor): {value}"
        ) from exc


def _validate_progressions_input(payload: dict) -> tuple[date, str]:
    if not isinstance(payload, dict):
        raise ProgressionsInputError("JSON gövdesi nesne olmalıdır")
    prog = payload.get("progressions") or {}
    if not isinstance(prog, dict):
        raise ProgressionsInputError("progressions alanı nesne olmalıdır")

    target_value = prog.get("target_date")
    if not target_value:
        target_date = date.today()
    else:
        target_date = _parse_target_date(target_value)

    reference_tz = str(prog.get("reference_timezone") or DEFAULT_REFERENCE_TIMEZONE)
    try:
        ZoneInfo(reference_tz)
    except ZoneInfoNotFoundError as exc:
        raise ProgressionsInputError(
            f"Geçersiz progressions.reference_timezone: {reference_tz}"
        ) from exc

    return target_date, reference_tz


def _compute_age_years(birth_utc: datetime, target_local: date, reference_tz: str) -> float:
    """Doğum UTC'sinden hedef tarihin yerel öğlesine kadar geçen tropik yıl sayısı."""
    tz = ZoneInfo(reference_tz)
    target_dt_local = datetime(
        target_local.year, target_local.month, target_local.day,
        12, 0, 0, tzinfo=tz,
    )
    target_dt_utc = target_dt_local.astimezone(timezone.utc)
    elapsed_seconds = (target_dt_utc - birth_utc).total_seconds()
    return elapsed_seconds / (TROPICAL_YEAR_DAYS * 86400.0)


def _body_longitude(jd_ut: float, swe_id: int) -> tuple[float, float]:
    try:
        values, _ = swe.calc_ut(jd_ut, swe_id, swe.FLG_SWIEPH | swe.FLG_SPEED)
    except swe.Error as exc:
        raise ProgressionsCalculationError(
            "Progressed gezegen konumu hesaplanamadı"
        ) from exc
    longitude, _lat, _dist, speed_long, _spd_lat, _spd_dist = values
    return longitude % 360.0, speed_long


def _lunation_phase(progressed_sun_lon: float, progressed_moon_lon: float) -> dict:
    """Progressed Sun-Moon arası elongasyon ve Rudhyar 8 evre etiketi."""
    elongation = (progressed_moon_lon - progressed_sun_lon) % 360.0
    label_key = "balsamic"
    label_tr = "Balsamic Fazı"
    for start, end, key, name_tr in SECONDARY_LUNATION_PHASES:
        if start <= elongation < end:
            label_key = key
            label_tr = name_tr
            break
    return {
        "elongation_degrees": round(elongation, 6),
        "phase": label_key,
        "phase_tr": label_tr,
    }


def _project_next_sign_change(
    current_longitude: float,
    daily_speed: float,
    age_years: float,
    birth_utc: datetime,
) -> dict:
    """Progressed gezegenin bir sonraki burç sınırına yaklaşık ulaşma tarihi.

    Progressed harekette gün cinsinden hız, yıl cinsinden hıza eşittir
    (1 gün = 1 yıl). Bu nedenle daily_speed (°/gün) doğrudan °/yıl olarak
    sembolik birime çevrilir; ulaşma süresi yıl cinsinden bulunur.
    """
    if abs(daily_speed) < 1e-9:
        return {"status": "indeterminate", "reason": "speed_too_low"}

    current_sign_index = int(current_longitude // 30.0)
    if daily_speed > 0:
        next_boundary = (current_sign_index + 1) * 30.0
        delta_deg = (next_boundary - current_longitude) % 30.0
        if delta_deg < 1e-6:
            delta_deg = 30.0
        new_sign_index = (current_sign_index + 1) % 12
    else:
        next_boundary = current_sign_index * 30.0
        delta_deg = (current_longitude - next_boundary) % 30.0
        if delta_deg < 1e-6:
            delta_deg = 30.0
        new_sign_index = (current_sign_index - 1) % 12

    years_to_change = delta_deg / abs(daily_speed)
    total_years_from_birth = age_years + years_to_change
    target_dt_utc = birth_utc + timedelta(
        days=total_years_from_birth * TROPICAL_YEAR_DAYS
    )
    sign_en, sign_tr = SIGNS[new_sign_index]
    return {
        "status": "available",
        "estimated_date_utc": target_dt_utc.date().isoformat(),
        "estimated_years_from_now": round(years_to_change, 3),
        "new_sign_index": new_sign_index,
        "new_sign": sign_en,
        "new_sign_tr": sign_tr,
    }


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_progressions(payload: dict, chart: dict | None = None) -> dict:
    """Secondary progressions için tek tarih anlık görüntüsü hesaplar."""

    target_date, reference_tz = _validate_progressions_input(payload)
    natal_chart = chart or calculate_core_chart(payload)

    birth = natal_chart["birth"]
    birth_utc = datetime.fromisoformat(
        birth["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)
    jd_birth_ut = _julian_day(birth_utc)

    latitude = float(birth["latitude"])
    longitude_geo = float(birth["longitude"])
    house_system = natal_chart["meta"]["house_system"]

    age_years = _compute_age_years(birth_utc, target_date, reference_tz)
    if age_years < 0:
        raise ProgressionsInputError(
            "Hedef tarih doğum tarihinden önce olamaz"
        )

    progressed_jd_ut = jd_birth_ut + age_years
    progressed_dt_utc = birth_utc + timedelta(
        days=age_years * TROPICAL_YEAR_DAYS
    )

    # Progressed evler ve açı kavşakları
    progressed_cusps, progressed_ascmc = _calculate_houses(
        progressed_jd_ut,
        latitude,
        longitude_geo,
        house_system,
    )
    progressed_ascendant = float(progressed_ascmc[0]) % 360.0
    progressed_midheaven = float(progressed_ascmc[1]) % 360.0

    progressed_angles = {
        "ascendant": _degree_fields(progressed_ascendant),
        "descendant": _degree_fields(progressed_ascendant + 180.0),
        "midheaven": _degree_fields(progressed_midheaven),
        "imum_coeli": _degree_fields(progressed_midheaven + 180.0),
    }

    # Progressed gezegen konumları
    natal_planets_by_id = {p["id"]: p for p in natal_chart["planets"]["items"]}
    natal_cusps_longitudes = [
        h["longitude"] for h in natal_chart["houses"]["items"]
    ]

    progressed_planets = []
    for swe_id, body_id, name, name_tr in PLANETS:
        try:
            row, _ = _body_position(
                progressed_jd_ut,
                swe_id,
                body_id,
                name,
                name_tr,
                progressed_cusps,
            )
        except ChartCalculationError:
            if body_id == "chiron":
                continue
            raise
        # Natal evdeki yerleşim de eklensin (progressed gezegenin natal harita
        # üzerindeki ev konumu klasik yorum için kritik)
        row["natal_house"] = _house_number(
            row["longitude"], natal_cusps_longitudes
        )
        progressed_planets.append(row)

    progressed_houses = []
    for index, cusp in enumerate(progressed_cusps):
        progressed_houses.append({
            "house": index + 1,
            **_degree_fields(cusp),
        })

    # Progressed → Natal majör açılar (sıkı orb)
    progressed_to_natal_aspects = []
    for prog_planet in progressed_planets:
        prog_id = prog_planet["id"]
        prog_lon = prog_planet["longitude"]
        for natal_planet in natal_chart["planets"]["items"]:
            natal_id = natal_planet["id"]
            natal_lon = natal_planet["longitude"]
            separation = _shortest_separation(prog_lon, natal_lon)
            best = None
            for aspect_type, exact_angle in PROGRESSION_ASPECTS.items():
                orb = abs(separation - exact_angle)
                threshold = PROGRESSED_ORB_MAJOR
                if prog_id in LUMINARIES or natal_id in LUMINARIES:
                    threshold += PROGRESSED_ORB_LUMINARY_BONUS
                if orb <= threshold and (best is None or orb < best[1]):
                    best = (aspect_type, orb, threshold)
            if best:
                aspect_type, orb, threshold = best
                progressed_to_natal_aspects.append({
                    "progressed": prog_id,
                    "natal": natal_id,
                    "type": aspect_type,
                    "orb": round(orb, 4),
                    "orb_threshold": threshold,
                    "natal_sign_tr": natal_planet["sign_tr"],
                    "natal_house": natal_planet["house"],
                    "progressed_sign_tr": prog_planet["sign_tr"],
                    "progressed_natal_house": prog_planet["natal_house"],
                })
    progressed_to_natal_aspects.sort(key=lambda r: r["orb"])

    # Progressed Moon paneli
    prog_moon = next(p for p in progressed_planets if p["id"] == "moon")
    prog_moon_speed = float(prog_moon.get("speed_longitude", 0.0))
    prog_moon_panel = {
        "sign_tr": prog_moon["sign_tr"],
        "degree_str": prog_moon["degree_str"],
        "natal_house": prog_moon["natal_house"],
        "retrograde": prog_moon["retrograde"],
        "daily_speed": round(prog_moon_speed, 6),
        "next_sign_change": _project_next_sign_change(
            prog_moon["longitude"], prog_moon_speed, age_years, birth_utc,
        ),
    }

    # Progressed Sun paneli
    prog_sun = next(p for p in progressed_planets if p["id"] == "sun")
    prog_sun_speed = float(prog_sun.get("speed_longitude", 0.0))
    prog_sun_panel = {
        "sign_tr": prog_sun["sign_tr"],
        "degree_str": prog_sun["degree_str"],
        "natal_house": prog_sun["natal_house"],
        "retrograde": prog_sun["retrograde"],
        "daily_speed": round(prog_sun_speed, 6),
        "next_sign_change": _project_next_sign_change(
            prog_sun["longitude"], prog_sun_speed, age_years, birth_utc,
        ),
    }

    secondary_lunation = _lunation_phase(
        prog_sun["longitude"], prog_moon["longitude"]
    )

    natal_summary = {
        "birth_date": birth["date"],
        "birth_time": birth["time"],
        "house_system": house_system,
        "ascendant_sign_tr": natal_chart["angles"]["ascendant"]["sign_tr"],
        "midheaven_sign_tr": natal_chart["angles"]["midheaven"]["sign_tr"],
        "natal_sun_sign_tr": natal_planets_by_id["sun"]["sign_tr"],
        "natal_moon_sign_tr": natal_planets_by_id["moon"]["sign_tr"],
    }

    limitations = []
    time_confidence = natal_chart["data_quality"].get("birth_time_confidence")
    if time_confidence in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; progressed evler ve açı kavşakları "
            "ciddi belirsizlik taşır."
        )

    return {
        "status": "available",
        "version": "1.0.0",
        "method": "secondary_progressions_one_day_one_year",
        "target_date": target_date.isoformat(),
        "reference_timezone": reference_tz,
        "age_years": round(age_years, 6),
        "progressed_jd_ut": round(progressed_jd_ut, 6),
        "progressed_datetime_utc": progressed_dt_utc.isoformat().replace(
            "+00:00", "Z"
        ),
        "natal_summary": natal_summary,
        "progressed": {
            "angles": progressed_angles,
            "planets": progressed_planets,
            "houses": progressed_houses,
        },
        "progressed_to_natal_aspects": progressed_to_natal_aspects,
        "progressed_moon": prog_moon_panel,
        "progressed_sun": prog_sun_panel,
        "secondary_lunation": secondary_lunation,
        "limitations": limitations,
    }


# ---------------------------------------------------------------------------
# Markdown çıktısı
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


def _aspect_tr(name: str) -> str:
    return ASPECT_TR.get(name, name)


def build_progressions_markdown(
    progressions: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    """Progressed harita için Markdown çıktısı."""

    target_date = progressions["target_date"]
    natal_summary = progressions["natal_summary"]
    age_years = progressions["age_years"]
    angles = progressions["progressed"]["angles"]
    planets = progressions["progressed"]["planets"]
    houses = progressions["progressed"]["houses"]
    aspects = progressions["progressed_to_natal_aspects"]
    prog_moon = progressions["progressed_moon"]
    prog_sun = progressions["progressed_sun"]
    lunation = progressions["secondary_lunation"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Secondary Progressed Harita {target_date}"',
        'type: "progressions_pack"',
        'source: "western_api_v2_progressions"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'target_date: "{target_date}"',
        f'age_years: {age_years}',
        f'method: "{progressions["method"]}"',
        f'house_system: "{natal_summary["house_system"]}"',
        f'reference_timezone: "{progressions["reference_timezone"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append('engine_version: "1.0.0"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Secondary Progressed Harita {target_date}",
        "",
        "## Kullanım Notu",
        "",
        "- Bu dosya secondary progressions için API tarafından üretilen teknik veri paketidir.",
        "- 1 gün = 1 yıl prensibiyle hesaplanmıştır; yorum içermez.",
        "- Progressed Sun ve Moon ana iç gelişim göstergeleridir; burç değişimleri belirleyici eşiklerdir.",
        "- Progressed açıların orb'u sıkıdır (1° ana, 1.5° aydınlatıcılarla).",
        "- Transit ile birlikte okunur; tek başına kullanılmaz.",
        "",
        "## Dönem Özeti",
        "",
        f"- Hedef tarih: {target_date}",
        f"- Doğumdan beri geçen yıl: {age_years:.4f}",
        f"- Doğum: {natal_summary['birth_date']} {natal_summary['birth_time']}",
        f"- Ev sistemi: {natal_summary['house_system']}",
        f"- Natal Yükselen: {natal_summary['ascendant_sign_tr']}",
        f"- Natal MC: {natal_summary['midheaven_sign_tr']}",
        f"- Natal Güneş: {natal_summary['natal_sun_sign_tr']}",
        f"- Natal Ay: {natal_summary['natal_moon_sign_tr']}",
        "",
    ]

    angle_rows = [
        ("ASC", angles["ascendant"]["sign_tr"], angles["ascendant"]["degree_str"]),
        ("DSC", angles["descendant"]["sign_tr"], angles["descendant"]["degree_str"]),
        ("MC", angles["midheaven"]["sign_tr"], angles["midheaven"]["degree_str"]),
        ("IC", angles["imum_coeli"]["sign_tr"], angles["imum_coeli"]["degree_str"]),
    ]
    angles_section = [
        "## Progressed Açılar",
        "",
        _md_table(["Nokta", "Burç", "Derece"], angle_rows),
        "",
    ]

    planet_rows = [
        (
            p["name_tr"],
            p["sign_tr"],
            p["degree_str"],
            p["natal_house"],
            "R" if p["retrograde"] else "-",
            f'{p["speed_longitude"]:.6f}',
        )
        for p in planets
    ]
    planets_section = [
        "## Progressed Gezegenler",
        "",
        _md_table(
            ["Gezegen", "Burç", "Derece", "Natal Ev", "Retro", "Günlük Hız"],
            planet_rows,
        ),
        "",
    ]

    house_rows = [
        (h["house"], h["sign_tr"], h["degree_str"])
        for h in houses
    ]
    houses_section = [
        "## Progressed Evler",
        "",
        _md_table(["Ev", "Burç", "Derece"], house_rows),
        "",
    ]

    if aspects:
        aspect_rows = [
            (
                a["progressed"],
                _aspect_tr(a["type"]),
                a["natal"],
                f'{a["orb"]:.2f}°',
                a["natal_sign_tr"],
                a["natal_house"],
                a["progressed_natal_house"],
            )
            for a in aspects
        ]
        aspect_table = _md_table(
            [
                "Progressed",
                "Açı",
                "Natal",
                "Orb",
                "Natal Burç",
                "Natal Ev",
                "Progressed → Natal Ev",
            ],
            aspect_rows,
        )
    else:
        aspect_table = "_Bu tarihte sıkı orb içinde progressed-natal majör açı bulunmuyor._"

    aspects_section = [
        "## Progressed → Natal Majör Açılar",
        "",
        f"_Orb eşiği: gezegen ↔ gezegen 1°, Sun/Moon dahil çiftler için 1.5°. Toplam: {len(aspects)}._",
        "",
        aspect_table,
        "",
    ]

    sun_next = prog_sun["next_sign_change"]
    moon_next = prog_moon["next_sign_change"]
    sun_next_str = (
        f'{sun_next["estimated_date_utc"]} ({sun_next["new_sign_tr"]})'
        if sun_next.get("status") == "available"
        else "-"
    )
    moon_next_str = (
        f'{moon_next["estimated_date_utc"]} ({moon_next["new_sign_tr"]})'
        if moon_next.get("status") == "available"
        else "-"
    )

    panels_section = [
        "## İç Gelişim Panelleri",
        "",
        _md_table(
            ["Cisim", "Burç", "Derece", "Natal Ev", "Sonraki Burç Geçişi"],
            [
                (
                    "Progressed Güneş",
                    prog_sun["sign_tr"],
                    prog_sun["degree_str"],
                    prog_sun["natal_house"],
                    sun_next_str,
                ),
                (
                    "Progressed Ay",
                    prog_moon["sign_tr"],
                    prog_moon["degree_str"],
                    prog_moon["natal_house"],
                    moon_next_str,
                ),
            ],
        ),
        "",
        f"- Secondary lunation faz: **{lunation['phase_tr']}** "
        f"(Sun-Moon elongasyon {lunation['elongation_degrees']:.2f}°)",
        "",
    ]

    limitations = progressions.get("limitations") or []
    limit_section = []
    if limitations:
        limit_section = [
            "## Sınırlamalar",
            "",
            *[f"- {item}" for item in limitations],
            "",
        ]

    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "```json",
        json.dumps(progressions, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *angles_section,
        *planets_section,
        *houses_section,
        *aspects_section,
        *panels_section,
        *limit_section,
        *technical_section,
    ])
