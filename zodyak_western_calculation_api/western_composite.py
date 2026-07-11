#!/usr/bin/env python3
"""Composite chart (midpoint yöntemi) calculations.

İki natal haritanın gezegen ve eksen midpoint'lerinden "ilişkinin kendi
haritası" oluşturulur:

- Composite nokta = kısa yay midpoint(A.nokta, B.nokta)
- Composite ASC ve MC de midpoint yöntemiyle hesaplanır
- Ev sistemi: composite ASC'tan Equal House (midpoint composite'te
  standart pratik; Placidus benzeri sistemler referans yer gerektirir)
- Composite haritanın kendi iç açıları natal orblarla hesaplanır

Bu bir veri paketidir; yorum içermez.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json

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


COMPOSITE_VERSION = "1.0.0"

COMPOSITE_PLANET_IDS = [
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto", "chiron",
]

# Composite iç açıları için natal standart orblar
COMPOSITE_ORBS = {
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
COMPOSITE_LUMINARY_BONUS = 1.0

COMPOSITE_ASPECTS = [
    ("conjunction", 0.0, "major", "neutral", "Kavuşum"),
    ("semisextile", 30.0, "minor", "neutral", "Yarım Sekstil"),
    ("semisquare", 45.0, "minor", "challenging", "Yarım Kare"),
    ("sextile", 60.0, "major", "harmonious", "Sekstil"),
    ("quintile", 72.0, "minor", "harmonious", "Kentil"),
    ("square", 90.0, "major", "challenging", "Kare"),
    ("trine", 120.0, "major", "harmonious", "Üçgen"),
    ("sesquiquadrate", 135.0, "minor", "challenging", "Seskikare"),
    ("biquintile", 144.0, "minor", "harmonious", "Bikentil"),
    ("quincunx", 150.0, "minor", "adjustment", "Kuinkunks"),
    ("opposition", 180.0, "major", "challenging", "Karşıt"),
]

LUMINARIES = {"sun", "moon"}

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
    "north_node": "Kuzey Ay Düğümü",
}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class CompositeInputError(ValueError):
    """Composite için geçersiz input."""


class CompositeCalculationError(RuntimeError):
    """Composite hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise CompositeInputError("JSON gövdesi nesne olmalıdır")
    person_a = payload.get("person_a")
    person_b = payload.get("person_b")
    if not isinstance(person_a, dict) or not isinstance(person_b, dict):
        raise CompositeInputError(
            "person_a ve person_b nesneleri zorunludur; her biri "
            "{name, birth, options} yapısında olmalıdır"
        )
    if not isinstance(person_a.get("birth"), dict):
        raise CompositeInputError("person_a.birth zorunludur")
    if not isinstance(person_b.get("birth"), dict):
        raise CompositeInputError("person_b.birth zorunludur")
    return person_a, person_b


def _chart_payload_for(person: dict, shared_options: dict | None) -> dict:
    options = {}
    if isinstance(shared_options, dict):
        options.update(shared_options)
    if isinstance(person.get("options"), dict):
        options.update(person["options"])
    return {
        "birth": person["birth"],
        "options": options or {"zodiac": "tropical", "house_system": "placidus"},
    }


def _shortest_midpoint(lon_a: float, lon_b: float) -> float:
    """İki boylamın kısa yay ortalaması."""
    signed_diff = ((lon_b - lon_a + 180.0) % 360.0) - 180.0
    return (lon_a + signed_diff / 2.0) % 360.0


def _degree_fields(longitude: float) -> dict:
    lon = longitude % 360.0
    sign_index = int(lon // 30)
    in_sign = lon % 30.0
    degrees = int(in_sign)
    minutes_float = (in_sign - degrees) * 60.0
    minutes = int(minutes_float)
    seconds = int(round((minutes_float - minutes) * 60.0))
    if seconds == 60:
        seconds = 0
        minutes += 1
    if minutes == 60:
        minutes = 0
        degrees += 1
    return {
        "longitude": round(lon, 6),
        "sign": SIGNS[sign_index][0],
        "sign_tr": SIGNS[sign_index][1],
        "sign_index": sign_index,
        "degree_str": f"{degrees}°{minutes:02d}'{seconds:02d}\"",
    }


def _equal_house_cusps(asc_lon: float) -> list[dict]:
    """Composite ASC'tan Equal House cusps."""
    cusps = []
    for i in range(12):
        lon = (asc_lon + i * 30.0) % 360.0
        cusps.append({
            "house": i + 1,
            **_degree_fields(lon),
        })
    return cusps


def _house_number_equal(longitude: float, asc_lon: float) -> int:
    offset = (longitude - asc_lon) % 360.0
    return int(offset // 30.0) + 1


def _planet_by_id(chart: dict, planet_id: str) -> dict | None:
    for p in chart["planets"]["items"]:
        if p["id"] == planet_id:
            return p
    return None


def _north_node_of(chart: dict) -> dict | None:
    for node in chart["nodes"]["items"]:
        if node["id"] in ("mean_node", "true_node"):
            return node
    return None


def _composite_points(chart_a: dict, chart_b: dict, asc_lon: float) -> list[dict]:
    """Gezegen + kuzey düğüm composite noktaları."""
    points = []
    for pid in COMPOSITE_PLANET_IDS:
        pa = _planet_by_id(chart_a, pid)
        pb = _planet_by_id(chart_b, pid)
        if not pa or not pb:
            continue
        mid = _shortest_midpoint(pa["longitude"], pb["longitude"])
        fields = _degree_fields(mid)
        points.append({
            "id": pid,
            "name_tr": PLANET_TR.get(pid, pid),
            **fields,
            "house": _house_number_equal(mid, asc_lon),
            "source_a": f'{pa["sign_tr"]} {pa["degree_str"]}',
            "source_b": f'{pb["sign_tr"]} {pb["degree_str"]}',
            "kind": "planet",
        })
    node_a = _north_node_of(chart_a)
    node_b = _north_node_of(chart_b)
    if node_a and node_b:
        mid = _shortest_midpoint(node_a["longitude"], node_b["longitude"])
        fields = _degree_fields(mid)
        points.append({
            "id": "north_node",
            "name_tr": PLANET_TR["north_node"],
            **fields,
            "house": _house_number_equal(mid, asc_lon),
            "source_a": f'{node_a["sign_tr"]} {node_a["degree_str"]}',
            "source_b": f'{node_b["sign_tr"]} {node_b["degree_str"]}',
            "kind": "node",
        })
    return points


def _orb_for(aspect_id: str, id_a: str, id_b: str) -> float:
    base = COMPOSITE_ORBS.get(aspect_id, 2.0)
    if id_a in LUMINARIES or id_b in LUMINARIES:
        return base + COMPOSITE_LUMINARY_BONUS
    return base


def _composite_internal_aspects(points: list[dict]) -> list[dict]:
    """Composite haritanın kendi iç açıları."""
    results = []
    n = len(points)
    for i in range(n):
        for j in range(i + 1, n):
            pa, pb = points[i], points[j]
            sep = _shortest_separation(pa["longitude"], pb["longitude"])
            best = None
            for aspect_id, exact, group, nature, tr in COMPOSITE_ASPECTS:
                orb_allowed = _orb_for(aspect_id, pa["id"], pb["id"])
                diff = abs(sep - exact)
                if diff <= orb_allowed and (best is None or diff < best["orb"]):
                    best = {
                        "from": pa["id"],
                        "from_tr": pa["name_tr"],
                        "to": pb["id"],
                        "to_tr": pb["name_tr"],
                        "aspect": aspect_id,
                        "aspect_tr": tr,
                        "group": group,
                        "nature": nature,
                        "orb": round(diff, 4),
                        "orb_allowed": round(orb_allowed, 4),
                    }
            if best:
                results.append(best)
    results.sort(key=lambda r: r["orb"])
    return results


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_composite(payload: dict) -> dict:
    """Composite (midpoint) haritası ana hesabı."""

    person_a, person_b = _validate_input(payload)
    shared_options = payload.get("options")

    chart_a = calculate_core_chart(_chart_payload_for(person_a, shared_options))
    chart_b = calculate_core_chart(_chart_payload_for(person_b, shared_options))

    name_a = str(person_a.get("name") or "A")
    name_b = str(person_b.get("name") or "B")

    # Composite angles (midpoint yöntemi)
    asc_a = chart_a["angles"]["ascendant"]["longitude"]
    asc_b = chart_b["angles"]["ascendant"]["longitude"]
    mc_a = chart_a["angles"]["midheaven"]["longitude"]
    mc_b = chart_b["angles"]["midheaven"]["longitude"]

    composite_asc = _shortest_midpoint(asc_a, asc_b)
    composite_mc = _shortest_midpoint(mc_a, mc_b)

    angles = {
        "ascendant": {**_degree_fields(composite_asc)},
        "descendant": {**_degree_fields((composite_asc + 180.0) % 360.0)},
        "midheaven": {**_degree_fields(composite_mc)},
        "imum_coeli": {**_degree_fields((composite_mc + 180.0) % 360.0)},
    }

    houses = _equal_house_cusps(composite_asc)
    points = _composite_points(chart_a, chart_b, composite_asc)
    aspects = _composite_internal_aspects(points)

    harmonious = sum(1 for a in aspects if a["nature"] == "harmonious")
    challenging = sum(1 for a in aspects if a["nature"] == "challenging")

    def _birth_summary(chart, name):
        birth = chart["birth"]
        return {
            "name": name,
            "date": birth["date"],
            "time": birth["time"],
            "place": birth.get("place"),
            "birth_time_confidence": chart["data_quality"].get("birth_time_confidence"),
        }

    limitations = [
        "Bu veri paketi yorum içermez; composite haritanın okunması danışmana aittir.",
        "Composite ASC/MC midpoint yöntemiyle hesaplanır (referans yer yöntemi v1'de yoktur).",
        "Ev sistemi Equal House'tur (composite ASC'tan); Placidus benzeri sistemler referans konum gerektirir.",
        "Composite haritalar sembolik yapılardır; gerçek gökyüzü anına karşılık gelmez.",
    ]
    conf_a = chart_a["data_quality"].get("birth_time_confidence")
    conf_b = chart_b["data_quality"].get("birth_time_confidence")
    if conf_a in {"low", "unknown"} or conf_b in {"low", "unknown"}:
        limitations.append(
            "En az bir tarafın doğum saati güveni düşük; composite ASC/MC ve "
            "ev yerleşimleri ciddi belirsizlik taşır."
        )

    return {
        "status": "available",
        "version": COMPOSITE_VERSION,
        "method": "composite_midpoint_equal_house_v1",
        "person_a": _birth_summary(chart_a, name_a),
        "person_b": _birth_summary(chart_b, name_b),
        "angles": angles,
        "houses": {"system": "equal_from_composite_asc", "items": houses},
        "points": points,
        "aspects": aspects,
        "aspect_stats": {
            "total": len(aspects),
            "harmonious": harmonious,
            "challenging": challenging,
            "neutral_or_adjustment": len(aspects) - harmonious - challenging,
        },
        "orb_profile": {
            "orbs": COMPOSITE_ORBS,
            "luminary_bonus": COMPOSITE_LUMINARY_BONUS,
        },
        "limitations": limitations,
    }


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
    if not rows:
        return ""
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_value(v) for v in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def build_composite_markdown(
    data: dict,
    pair_label: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    pa = data["person_a"]
    pb = data["person_b"]
    angles = data["angles"]
    points = data["points"]
    aspects = data["aspects"]
    stats = data["aspect_stats"]

    fm_lines = [
        "---",
        f'title: "Composite - {pa["name"]} & {pb["name"]}"',
        'type: "composite_pack"',
        'source: "western_api_v2_composite"',
        f'pair: "{pair_label}"',
        f'group: "{group_name}"',
        f'person_a: "{pa["name"]}"',
        f'person_b: "{pb["name"]}"',
        f'method: "{data["method"]}"',
        f'composite_asc: "{angles["ascendant"]["sign_tr"]} {angles["ascendant"]["degree_str"]}"',
        f'composite_mc: "{angles["midheaven"]["sign_tr"]} {angles["midheaven"]["degree_str"]}"',
        f'aspect_count: {stats["total"]}',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{COMPOSITE_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# Composite: {pa['name']} & {pb['name']}",
        "",
        "## Kullanım Notu",
        "",
        "- Composite, midpoint yöntemiyle üretilen 'ilişkinin kendi haritası'dır.",
        "- Sembolik bir yapıdır; gerçek gökyüzü anına karşılık gelmez.",
        "- Ev sistemi: composite ASC'tan Equal House.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Taraflar",
        "",
        f"- **{pa['name']}**: {pa['date']} {pa['time']} — {pa.get('place') or '-'}",
        f"- **{pb['name']}**: {pb['date']} {pb['time']} — {pb.get('place') or '-'}",
        "",
        "## Composite Eksenler",
        "",
        f"- ASC: **{angles['ascendant']['sign_tr']} {angles['ascendant']['degree_str']}**",
        f"- DSC: {angles['descendant']['sign_tr']} {angles['descendant']['degree_str']}",
        f"- MC: **{angles['midheaven']['sign_tr']} {angles['midheaven']['degree_str']}**",
        f"- IC: {angles['imum_coeli']['sign_tr']} {angles['imum_coeli']['degree_str']}",
        "",
    ]

    point_rows = [
        (
            p["name_tr"],
            f'{p["sign_tr"]} {p["degree_str"]}',
            f'e{p["house"]}',
            p["source_a"],
            p["source_b"],
        )
        for p in points
    ]
    points_section = [
        "## Composite Noktalar",
        "",
        _md_table(
            ["Nokta", "Composite Konum", "Ev", f'{pa["name"]} Kaynak', f'{pb["name"]} Kaynak'],
            point_rows,
        ),
        "",
    ]

    aspect_rows = [
        (
            a["from_tr"],
            a["aspect_tr"],
            a["to_tr"],
            f'{a["orb"]:.2f}°',
            a["group"],
            a["nature"],
        )
        for a in aspects
    ]
    aspects_section = [
        "## Composite İç Açılar",
        "",
        f"Toplam {stats['total']} açı (uyumlu {stats['harmonious']}, zorlayıcı {stats['challenging']}).",
        "",
        _md_table(
            ["Nokta A", "Açı", "Nokta B", "Orb", "Grup", "Doğa"],
            aspect_rows,
        ) if aspect_rows else "_Orb içinde açı bulunmuyor._",
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in data.get("limitations", [])],
        "",
    ]

    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "```json",
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *points_section,
        *aspects_section,
        *limit_section,
        *technical_section,
    ])
