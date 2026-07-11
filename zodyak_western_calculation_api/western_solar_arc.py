#!/usr/bin/env python3
"""Solar Arc directions calculations and markdown render.

Solar arc directions: tüm natal noktalar (gezegenler + ay düğümleri +
açı kavşakları) doğum tarihinden hedef tarihe kadar progressed Sun'ın
ilerlediği yay (solar arc) kadar ileri taşınır.

solar_arc = progressed_sun_longitude − natal_sun_longitude
(progressed = secondary, 1 gün = 1 yıl)

Aritmetik olarak ~1°/yıl olduğundan SA Sun, SA Moon, SA MC ve SA ASC
keskin eşik göstergeleridir. SA → Natal majör açılar sıkı orb ile
listelenir; bu modül yorum içermez.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    SIGNS,
    _degree_fields,
    _house_number,
    _julian_day,
    _shortest_separation,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


SOLAR_ARC_VERSION = "1.0.0"
TROPICAL_YEAR_DAYS = 365.2422
DEFAULT_REFERENCE_TIMEZONE = os.environ.get(
    "WESTERN_ASTROLOGY_DEFAULT_TIMEZONE", "Europe/Istanbul",
)

SA_ASPECTS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

SA_ORB_MAJOR = 1.0
SA_ORB_LUMINARY_BONUS = 0.5

ASPECT_TR = {
    "conjunction": "Kavuşum",
    "opposition": "Karşıt",
    "square": "Kare",
    "trine": "Üçgen",
    "sextile": "Sekstil",
}

LUMINARIES = {"sun", "moon"}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class SolarArcInputError(ValueError):
    """Solar arc directions için geçersiz input."""


class SolarArcCalculationError(RuntimeError):
    """Solar arc directions hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _parse_target_date(value: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise SolarArcInputError(
            f"Geçersiz tarih (YYYY-MM-DD bekleniyor): {value}"
        ) from exc


def _validate_solar_arc_input(payload: dict) -> tuple[date, str]:
    if not isinstance(payload, dict):
        raise SolarArcInputError("JSON gövdesi nesne olmalıdır")
    sa = payload.get("solar_arc") or {}
    if not isinstance(sa, dict):
        raise SolarArcInputError("solar_arc alanı nesne olmalıdır")

    target_value = sa.get("target_date")
    if target_value:
        target_date = _parse_target_date(target_value)
    else:
        target_date = date.today()

    reference_tz = str(sa.get("reference_timezone") or DEFAULT_REFERENCE_TIMEZONE)
    try:
        ZoneInfo(reference_tz)
    except ZoneInfoNotFoundError as exc:
        raise SolarArcInputError(
            f"Geçersiz solar_arc.reference_timezone: {reference_tz}"
        ) from exc

    return target_date, reference_tz


def _compute_age_years(
    birth_utc: datetime, target_local: date, reference_tz: str,
) -> float:
    tz = ZoneInfo(reference_tz)
    target_dt_local = datetime(
        target_local.year, target_local.month, target_local.day,
        12, 0, 0, tzinfo=tz,
    )
    target_dt_utc = target_dt_local.astimezone(timezone.utc)
    elapsed_seconds = (target_dt_utc - birth_utc).total_seconds()
    return elapsed_seconds / (TROPICAL_YEAR_DAYS * 86400.0)


def _sun_longitude_at(jd_ut: float) -> float:
    try:
        values, _ = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)
    except swe.Error as exc:
        raise SolarArcCalculationError(
            "Solar arc Sun konumu hesaplanamadı"
        ) from exc
    return float(values[0]) % 360.0


def _build_sa_point(
    natal_point: dict,
    solar_arc: float,
    natal_cusps: list[float],
    extra: dict | None = None,
) -> dict:
    """Bir natal nokta için SA pozisyonu üret."""
    natal_lon = natal_point["longitude"]
    sa_lon = (natal_lon + solar_arc) % 360.0
    row = {
        "id": natal_point.get("id"),
        "natal_longitude": natal_lon,
        **_degree_fields(sa_lon),
        "natal_house": _house_number(sa_lon, natal_cusps),
        "solar_arc_applied": round(solar_arc, 6),
    }
    if extra:
        row.update(extra)
    return row


def _project_next_sign_change(
    current_longitude: float,
    age_years: float,
    arc_rate_per_year: float,
    birth_utc: datetime,
) -> dict:
    """SA noktanın bir sonraki burç sınırına ulaşma tahmini.

    arc_rate_per_year: solar arc miktarının yıllık ortalama değişimi
    (SA Sun'ın yıllık hareketi, ~0.985°/yıl civarı).
    """
    if arc_rate_per_year <= 1e-9:
        return {"status": "indeterminate", "reason": "arc_rate_too_low"}

    current_sign_index = int(current_longitude // 30.0)
    next_boundary = (current_sign_index + 1) * 30.0
    delta_deg = (next_boundary - current_longitude) % 30.0
    if delta_deg < 1e-6:
        delta_deg = 30.0
    new_sign_index = (current_sign_index + 1) % 12

    years_to_change = delta_deg / arc_rate_per_year
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


def calculate_solar_arc(payload: dict, chart: dict | None = None) -> dict:
    """Verilen hedef tarih için solar arc directions anlık görüntüsü."""

    target_date, reference_tz = _validate_solar_arc_input(payload)
    natal_chart = chart or calculate_core_chart(payload)

    birth = natal_chart["birth"]
    birth_utc = datetime.fromisoformat(
        birth["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)
    jd_birth_ut = _julian_day(birth_utc)

    natal_sun = next(
        p for p in natal_chart["planets"]["items"] if p["id"] == "sun"
    )
    natal_sun_long = natal_sun["longitude"]

    age_years = _compute_age_years(birth_utc, target_date, reference_tz)
    if age_years < 0:
        raise SolarArcInputError(
            "Hedef tarih doğum tarihinden önce olamaz"
        )

    # Progressed Sun (secondary): jd_birth + age_years gün
    progressed_jd_ut = jd_birth_ut + age_years
    progressed_sun_long = _sun_longitude_at(progressed_jd_ut)

    # Solar arc miktarı: signed difference. Sun zodyak boyunca daima ileri
    # gittiği için arc pozitif çıkar; yine de 360° atlama olmasın diye
    # mod alıp en yakın ileri farkı kullan.
    solar_arc = (progressed_sun_long - natal_sun_long) % 360.0
    # SA için negatif beklenmez; ama anomali kontrolü:
    if solar_arc > 180.0 and age_years < 1.0:
        # Çok küçük yaşlarda numeric anomali — pozitif tut.
        solar_arc -= 360.0

    # Bir önceki yıla göre arc rate (SA Sun'ın yıllık hareketi)
    one_year_earlier_jd = jd_birth_ut + max(age_years - 1.0, 0.0)
    one_year_earlier_sun = _sun_longitude_at(one_year_earlier_jd)
    arc_rate_per_year = (progressed_sun_long - one_year_earlier_sun) % 360.0
    if arc_rate_per_year > 180.0:
        arc_rate_per_year -= 360.0
    if age_years < 1.0:
        # Yıl başına ortalama: 360°/yaklaşık 365 gün progresyon → ~0.985°/yıl
        arc_rate_per_year = 360.0 / 365.25

    # Natal ev cusps (SA noktalarının natal evlerini bulmak için)
    natal_cusps = [h["longitude"] for h in natal_chart["houses"]["items"]]

    # SA gezegen noktaları
    sa_planets = []
    for natal_planet in natal_chart["planets"]["items"]:
        sa_point = _build_sa_point(
            natal_planet,
            solar_arc,
            natal_cusps,
            extra={
                "kind": "planet",
                "name": natal_planet.get("name"),
                "name_tr": natal_planet.get("name_tr"),
                "retrograde_at_birth": natal_planet.get("retrograde"),
            },
        )
        sa_planets.append(sa_point)

    # SA düğümler
    sa_nodes = []
    for natal_node in natal_chart["nodes"]["items"]:
        sa_point = _build_sa_point(
            natal_node,
            solar_arc,
            natal_cusps,
            extra={
                "kind": "node",
                "name": natal_node.get("name"),
                "name_tr": natal_node.get("name_tr"),
                "node_type": natal_node.get("node_type"),
            },
        )
        sa_nodes.append(sa_point)

    # SA açı kavşakları (ASC/DSC/MC/IC)
    sa_angles = {}
    for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
        natal_angle = natal_chart["angles"][angle_id]
        sa_angles[angle_id] = _build_sa_point(
            {"id": angle_id, "longitude": natal_angle["longitude"]},
            solar_arc,
            natal_cusps,
            extra={"kind": "angle"},
        )

    # SA → Natal majör açılar (sıkı orb)
    sa_to_natal_aspects = []
    natal_points_for_aspect = [
        *natal_chart["planets"]["items"],
        *natal_chart["nodes"]["items"],
    ]
    for natal_angle_id in ("ascendant", "midheaven"):
        a = natal_chart["angles"][natal_angle_id]
        natal_points_for_aspect.append({
            "id": natal_angle_id,
            "longitude": a["longitude"],
            "sign_tr": a["sign_tr"],
            "house": None,
        })

    for sa_point in [*sa_planets, *sa_nodes]:
        sa_id = sa_point["id"]
        sa_lon = sa_point["longitude"]
        for natal_point in natal_points_for_aspect:
            natal_id = natal_point["id"]
            # SA noktanın kendi natal karşılığıyla conjunction'ını
            # bir "geri dönüş" olarak ayıralım; çoğunlukla gözlenmez
            # ama formal olarak listelenebilir.
            separation = _shortest_separation(sa_lon, natal_point["longitude"])
            best = None
            for aspect_type, exact in SA_ASPECTS.items():
                orb = abs(separation - exact)
                threshold = SA_ORB_MAJOR
                if sa_id in LUMINARIES or natal_id in LUMINARIES:
                    threshold += SA_ORB_LUMINARY_BONUS
                if orb <= threshold and (best is None or orb < best[1]):
                    best = (aspect_type, orb, threshold)
            if best:
                aspect_type, orb, threshold = best
                sa_to_natal_aspects.append({
                    "sa": sa_id,
                    "natal": natal_id,
                    "type": aspect_type,
                    "orb": round(orb, 4),
                    "orb_threshold": threshold,
                    "sa_sign_tr": sa_point["sign_tr"],
                    "sa_natal_house": sa_point["natal_house"],
                    "natal_sign_tr": natal_point.get("sign_tr"),
                    "natal_house": natal_point.get("house"),
                })
    sa_to_natal_aspects.sort(key=lambda r: r["orb"])

    # Eşik panelleri: SA Sun, SA Moon, SA MC, SA ASC için sonraki burç geçişi
    sa_sun = next(p for p in sa_planets if p["id"] == "sun")
    sa_moon = next(p for p in sa_planets if p["id"] == "moon")
    threshold_panels = {
        "sa_sun": {
            "sign_tr": sa_sun["sign_tr"],
            "degree_str": sa_sun["degree_str"],
            "natal_house": sa_sun["natal_house"],
            "next_sign_change": _project_next_sign_change(
                sa_sun["longitude"], age_years, arc_rate_per_year, birth_utc,
            ),
        },
        "sa_moon": {
            "sign_tr": sa_moon["sign_tr"],
            "degree_str": sa_moon["degree_str"],
            "natal_house": sa_moon["natal_house"],
            "next_sign_change": _project_next_sign_change(
                sa_moon["longitude"], age_years, arc_rate_per_year, birth_utc,
            ),
        },
        "sa_ascendant": {
            "sign_tr": sa_angles["ascendant"]["sign_tr"],
            "degree_str": sa_angles["ascendant"]["degree_str"],
            "natal_house": sa_angles["ascendant"]["natal_house"],
            "next_sign_change": _project_next_sign_change(
                sa_angles["ascendant"]["longitude"], age_years,
                arc_rate_per_year, birth_utc,
            ),
        },
        "sa_midheaven": {
            "sign_tr": sa_angles["midheaven"]["sign_tr"],
            "degree_str": sa_angles["midheaven"]["degree_str"],
            "natal_house": sa_angles["midheaven"]["natal_house"],
            "next_sign_change": _project_next_sign_change(
                sa_angles["midheaven"]["longitude"], age_years,
                arc_rate_per_year, birth_utc,
            ),
        },
    }

    natal_summary = {
        "birth_date": birth["date"],
        "birth_time": birth["time"],
        "house_system": natal_chart["meta"]["house_system"],
        "ascendant_sign_tr": natal_chart["angles"]["ascendant"]["sign_tr"],
        "midheaven_sign_tr": natal_chart["angles"]["midheaven"]["sign_tr"],
        "natal_sun_sign_tr": natal_sun["sign_tr"],
    }

    limitations = []
    time_confidence = natal_chart["data_quality"].get("birth_time_confidence")
    if time_confidence in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; SA ASC/MC ve angle-tabanlı eşikler "
            "ciddi belirsizlik taşır."
        )

    return {
        "status": "available",
        "version": SOLAR_ARC_VERSION,
        "method": "solar_arc_directions_naibod_secondary_sun",
        "target_date": target_date.isoformat(),
        "reference_timezone": reference_tz,
        "age_years": round(age_years, 6),
        "solar_arc_degrees": round(solar_arc, 6),
        "arc_rate_degrees_per_year": round(arc_rate_per_year, 6),
        "natal_sun_longitude": round(natal_sun_long, 6),
        "progressed_sun_longitude": round(progressed_sun_long, 6),
        "natal_summary": natal_summary,
        "sa_points": {
            "planets": sa_planets,
            "nodes": sa_nodes,
            "angles": sa_angles,
        },
        "sa_to_natal_aspects": sa_to_natal_aspects,
        "threshold_panels": threshold_panels,
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


def build_solar_arc_markdown(
    sa_data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    """Solar arc directions için Markdown çıktısı."""

    target_date = sa_data["target_date"]
    natal_summary = sa_data["natal_summary"]
    age_years = sa_data["age_years"]
    solar_arc = sa_data["solar_arc_degrees"]
    arc_rate = sa_data["arc_rate_degrees_per_year"]
    sa_planets = sa_data["sa_points"]["planets"]
    sa_nodes = sa_data["sa_points"]["nodes"]
    sa_angles = sa_data["sa_points"]["angles"]
    aspects = sa_data["sa_to_natal_aspects"]
    panels = sa_data["threshold_panels"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Solar Arc Directions {target_date}"',
        'type: "solar_arc_pack"',
        'source: "western_api_v2_solar_arc"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'target_date: "{target_date}"',
        f'age_years: {age_years}',
        f'solar_arc_degrees: {solar_arc}',
        f'method: "{sa_data["method"]}"',
        f'house_system: "{natal_summary["house_system"]}"',
        f'reference_timezone: "{sa_data["reference_timezone"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{SOLAR_ARC_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Solar Arc Directions {target_date}",
        "",
        "## Kullanım Notu",
        "",
        "- Solar arc directions: tüm natal noktalar progressed Sun'ın katettiği yay kadar ileri taşınır.",
        "- Yaklaşık 1°/yıl olduğundan SA noktanın burç ve ev geçişi keskin eşik göstergesidir.",
        "- Orb sıkıdır (1° major, luminary için 1.5°); transit'ten daha az ama secondary progressions'tan daha keskin.",
        "- Transit, progressions ve SR ile birlikte okunur; tek başına kullanılmaz.",
        "",
        "## Dönem Özeti",
        "",
        f"- Hedef tarih: {target_date}",
        f"- Doğumdan beri geçen yıl: {age_years:.4f}",
        f"- **Solar arc miktarı: {solar_arc:.4f}°**",
        f"- Yıllık arc hızı: {arc_rate:.4f}°/yıl",
        f"- Doğum: {natal_summary['birth_date']} {natal_summary['birth_time']}",
        f"- Ev sistemi: {natal_summary['house_system']}",
        f"- Natal Yükselen: {natal_summary['ascendant_sign_tr']}",
        f"- Natal MC: {natal_summary['midheaven_sign_tr']}",
        f"- Natal Güneş: {natal_summary['natal_sun_sign_tr']}",
        "",
    ]

    angles_rows = []
    for label, key in (
        ("SA ASC", "ascendant"),
        ("SA DSC", "descendant"),
        ("SA MC", "midheaven"),
        ("SA IC", "imum_coeli"),
    ):
        a = sa_angles[key]
        angles_rows.append((label, a["sign_tr"], a["degree_str"], a["natal_house"]))
    angles_section = [
        "## SA Açı Kavşakları",
        "",
        _md_table(["Nokta", "Burç", "Derece", "Natal Ev"], angles_rows),
        "",
    ]

    planet_rows = [
        (
            p.get("name_tr") or p["id"],
            p["sign_tr"],
            p["degree_str"],
            p["natal_house"],
        )
        for p in sa_planets
    ]
    planets_section = [
        "## SA Gezegenler",
        "",
        _md_table(
            ["Gezegen", "Burç", "Derece", "Natal Ev"],
            planet_rows,
        ),
        "",
    ]

    node_rows = [
        (
            n.get("name_tr") or n["id"],
            n["sign_tr"],
            n["degree_str"],
            n["natal_house"],
        )
        for n in sa_nodes
    ]
    nodes_section = [
        "## SA Ay Düğümleri",
        "",
        _md_table(
            ["Düğüm", "Burç", "Derece", "Natal Ev"],
            node_rows,
        ),
        "",
    ]

    if aspects:
        aspect_rows = [
            (
                f"SA {a['sa']}",
                _aspect_tr(a["type"]),
                f"n.{a['natal']}",
                f'{a["orb"]:.2f}°',
                a["natal_sign_tr"] or "-",
                a["natal_house"] if a["natal_house"] else "-",
                a["sa_natal_house"],
            )
            for a in aspects
        ]
        aspect_table = _md_table(
            ["SA", "Açı", "Natal", "Orb", "Natal Burç", "Natal Ev", "SA → Natal Ev"],
            aspect_rows,
        )
    else:
        aspect_table = "_Bu tarihte sıkı orb içinde SA-natal majör açı bulunmuyor._"

    aspects_section = [
        "## SA → Natal Majör Açılar",
        "",
        f"_Orb eşiği: 1°, Sun/Moon dahil çiftler için 1.5°. Toplam: {len(aspects)}._",
        "",
        aspect_table,
        "",
    ]

    def _panel_next(panel):
        n = panel["next_sign_change"]
        if n.get("status") != "available":
            return "-"
        return f'{n["estimated_date_utc"]} → {n["new_sign_tr"]}'

    panels_section = [
        "## Eşik Panelleri (Sonraki Burç Geçişleri)",
        "",
        _md_table(
            ["Nokta", "Burç", "Derece", "Natal Ev", "Sonraki Burç Geçişi"],
            [
                (
                    "SA Güneş",
                    panels["sa_sun"]["sign_tr"],
                    panels["sa_sun"]["degree_str"],
                    panels["sa_sun"]["natal_house"],
                    _panel_next(panels["sa_sun"]),
                ),
                (
                    "SA Ay",
                    panels["sa_moon"]["sign_tr"],
                    panels["sa_moon"]["degree_str"],
                    panels["sa_moon"]["natal_house"],
                    _panel_next(panels["sa_moon"]),
                ),
                (
                    "SA ASC",
                    panels["sa_ascendant"]["sign_tr"],
                    panels["sa_ascendant"]["degree_str"],
                    panels["sa_ascendant"]["natal_house"],
                    _panel_next(panels["sa_ascendant"]),
                ),
                (
                    "SA MC",
                    panels["sa_midheaven"]["sign_tr"],
                    panels["sa_midheaven"]["degree_str"],
                    panels["sa_midheaven"]["natal_house"],
                    _panel_next(panels["sa_midheaven"]),
                ),
            ],
        ),
        "",
    ]

    limitations = sa_data.get("limitations") or []
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
        json.dumps(sa_data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *angles_section,
        *planets_section,
        *nodes_section,
        *aspects_section,
        *panels_section,
        *limit_section,
        *technical_section,
    ])
