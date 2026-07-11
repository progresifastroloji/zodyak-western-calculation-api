#!/usr/bin/env python3
"""Midpoints calculation (Cosmobiology / Uranian style).

14 natal nokta (10 gezegen + 2 ay düğümü + ASC + MC) arasındaki 91
ikili midpoint hesaplanır. Her midpoint için doğrudan ve karşı
(180°) konum, ev yerleşimi ve orb içinde olan natal noktalar
(occupied_by) listelenir. 45° dial (8. harmonik) ile Cosmobiology
çekirdek katmanı eklenir.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
from itertools import combinations

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    SIGNS,
    _degree_fields,
    _house_number,
    _shortest_separation,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


MIDPOINTS_VERSION = "1.0.0"

# Klasik Cosmobiology orbu 1.5°; sıkı kullanım için 1.0° opsiyonel
DEFAULT_OCCUPIED_ORB = 1.5
DEFAULT_DIAL_ORB = 1.5
MIN_ORB = 0.5
MAX_ORB = 3.0

# 14 standart Cosmobiology noktası
MIDPOINT_PLANET_IDS = [
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
]
MIDPOINT_NODE_IDS = ["north_node", "south_node"]
MIDPOINT_ANGLE_IDS = ["ascendant", "midheaven"]

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
    "north_node": "Kuzey Ay Düğümü",
    "south_node": "Güney Ay Düğümü",
    "ascendant": "ASC",
    "midheaven": "MC",
}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class MidpointsInputError(ValueError):
    """Midpoints için geçersiz input."""


class MidpointsCalculationError(RuntimeError):
    """Midpoints hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> tuple[float, float]:
    if not isinstance(payload, dict):
        raise MidpointsInputError("JSON gövdesi nesne olmalıdır")
    m = payload.get("midpoints") or {}
    if not isinstance(m, dict):
        raise MidpointsInputError("midpoints alanı nesne olmalıdır")

    try:
        occupied_orb = float(m.get("occupied_orb") or DEFAULT_OCCUPIED_ORB)
    except (TypeError, ValueError) as exc:
        raise MidpointsInputError("midpoints.occupied_orb sayı olmalıdır") from exc
    if not MIN_ORB <= occupied_orb <= MAX_ORB:
        raise MidpointsInputError(
            f"midpoints.occupied_orb {MIN_ORB}-{MAX_ORB} aralığında olmalıdır"
        )

    try:
        dial_orb = float(m.get("dial_orb") or DEFAULT_DIAL_ORB)
    except (TypeError, ValueError) as exc:
        raise MidpointsInputError("midpoints.dial_orb sayı olmalıdır") from exc
    if not MIN_ORB <= dial_orb <= MAX_ORB:
        raise MidpointsInputError(
            f"midpoints.dial_orb {MIN_ORB}-{MAX_ORB} aralığında olmalıdır"
        )

    return occupied_orb, dial_orb


def _shortest_midpoint(lon_a: float, lon_b: float) -> float:
    """İki boylamın kısa yay ortalaması (signed delta yöntemi)."""
    signed_diff = ((lon_b - lon_a + 180.0) % 360.0) - 180.0
    return (lon_a + signed_diff / 2.0) % 360.0


def _natal_points(chart: dict) -> dict[str, dict]:
    """Midpoint için kullanılacak 14 noktayı id → {longitude, kind} olarak topla."""
    points: dict[str, dict] = {}
    for planet in chart["planets"]["items"]:
        if planet["id"] in MIDPOINT_PLANET_IDS:
            points[planet["id"]] = {
                "id": planet["id"],
                "longitude": planet["longitude"],
                "kind": "planet",
                "name_tr": planet.get("name_tr") or PLANET_TR.get(planet["id"]),
                "sign_tr": planet.get("sign_tr"),
                "house": planet.get("house"),
                "retrograde": planet.get("retrograde", False),
            }
    for node in chart["nodes"]["items"]:
        if node["id"] in MIDPOINT_NODE_IDS:
            points[node["id"]] = {
                "id": node["id"],
                "longitude": node["longitude"],
                "kind": "node",
                "name_tr": node.get("name_tr") or PLANET_TR.get(node["id"]),
                "sign_tr": node.get("sign_tr"),
                "house": node.get("house"),
                "retrograde": node.get("retrograde", False),
            }
    for angle_id in MIDPOINT_ANGLE_IDS:
        a = chart["angles"][angle_id]
        points[angle_id] = {
            "id": angle_id,
            "longitude": a["longitude"],
            "kind": "angle",
            "name_tr": PLANET_TR.get(angle_id, angle_id),
            "sign_tr": a.get("sign_tr"),
            "house": None,
            "retrograde": False,
        }
    return points


def _make_point_summary(longitude: float, cusps: list[float]) -> dict:
    return {
        **_degree_fields(longitude),
        "house": _house_number(longitude, cusps),
    }


def _find_occupied_by(
    midpoint_lon: float,
    midpoint_pair_ids: tuple[str, str],
    natal_points: dict[str, dict],
    orb: float,
) -> list[dict]:
    """Direct veya opposite midpoint'e orb içinde olan natal noktaları döner."""
    direct_lon = midpoint_lon
    opposite_lon = (midpoint_lon + 180.0) % 360.0

    matches = []
    for point_id, point in natal_points.items():
        if point_id in midpoint_pair_ids:
            continue  # bir nokta kendi midpoint'inde "occupied" sayılmaz
        for side, target_lon in (("direct", direct_lon), ("opposite", opposite_lon)):
            sep = _shortest_separation(point["longitude"], target_lon)
            if sep <= orb:
                matches.append({
                    "point": point_id,
                    "point_tr": point["name_tr"],
                    "side": side,
                    "orb": round(sep, 4),
                    "natal_sign_tr": point.get("sign_tr"),
                    "natal_house": point.get("house"),
                })
    matches.sort(key=lambda r: r["orb"])
    return matches


def _build_45_dial(
    natal_points: dict[str, dict],
    midpoints: list[dict],
    dial_orb: float,
) -> dict:
    """8. harmonik (45° dial) eksenleri ve orb içindeki kümeleri."""
    # Her natal noktanın 45° dial konumu (0-45° arası)
    dial_items = []
    for point_id, point in natal_points.items():
        pos = point["longitude"] % 45.0
        dial_items.append({
            "id": point_id,
            "name_tr": point["name_tr"],
            "kind": point["kind"],
            "natal_longitude": round(point["longitude"], 6),
            "dial_position": round(pos, 6),
        })
    dial_items.sort(key=lambda r: r["dial_position"])

    # Midpoint noktalarının dial konumu
    midpoint_dial_items = []
    for mp in midpoints:
        pos = mp["direct"]["longitude"] % 45.0
        midpoint_dial_items.append({
            "pair": mp["pair"],
            "dial_position": round(pos, 6),
        })

    # Eksenler: dial üzerinde orb içinde olan natal nokta kümeleri
    # Basit yöntem: dial_position'a göre sırala, ardışık orb içindekileri grupla
    sorted_items = sorted(dial_items, key=lambda r: r["dial_position"])
    axes = []
    current_axis = []
    for item in sorted_items:
        if not current_axis:
            current_axis.append(item)
            continue
        last_pos = current_axis[-1]["dial_position"]
        if item["dial_position"] - last_pos <= dial_orb:
            current_axis.append(item)
        else:
            if len(current_axis) >= 2:
                axes.append({
                    "members": [m["id"] for m in current_axis],
                    "members_tr": [m["name_tr"] for m in current_axis],
                    "dial_center": round(
                        sum(m["dial_position"] for m in current_axis) / len(current_axis),
                        6,
                    ),
                    "span": round(
                        current_axis[-1]["dial_position"] - current_axis[0]["dial_position"],
                        6,
                    ),
                })
            current_axis = [item]
    if len(current_axis) >= 2:
        axes.append({
            "members": [m["id"] for m in current_axis],
            "members_tr": [m["name_tr"] for m in current_axis],
            "dial_center": round(
                sum(m["dial_position"] for m in current_axis) / len(current_axis),
                6,
            ),
            "span": round(
                current_axis[-1]["dial_position"] - current_axis[0]["dial_position"],
                6,
            ),
        })

    # Circular wrap: 45° döngüsü olduğundan dial_position=0 ile 45'e yakın olanlar
    # da aynı eksende olabilir; ilk ve son grup birleşebilir
    if len(sorted_items) >= 2:
        wrap_distance = (45.0 - sorted_items[-1]["dial_position"]) + sorted_items[0]["dial_position"]
        if wrap_distance <= dial_orb:
            # Wrap olduğunda son ekseni ilkine ekle (eğer her ikisi de varsa)
            if axes and sorted_items[0]["id"] in axes[0]["members"] and sorted_items[-1]["id"] in axes[-1]["members"]:
                if axes[0] is not axes[-1]:
                    merged_ids = list(set(axes[-1]["members"]) | set(axes[0]["members"]))
                    axes[-1]["members"] = merged_ids
                    axes[-1]["members_tr"] = [PLANET_TR.get(i, i) for i in merged_ids]
                    axes[-1]["wrap_around"] = True
                    axes.pop(0)

    return {
        "status": "available",
        "harmonic": 8,
        "dial_degrees": 45.0,
        "orb": dial_orb,
        "items": dial_items,
        "midpoint_dial_items": midpoint_dial_items,
        "occupied_axes": axes,
    }


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_midpoints(payload: dict, chart: dict | None = None) -> dict:
    """Midpoints (Cosmobiology) ana hesabı."""

    occupied_orb, dial_orb = _validate_input(payload)
    natal_chart = chart or calculate_core_chart(payload)

    natal_points = _natal_points(natal_chart)
    cusps = [h["longitude"] for h in natal_chart["houses"]["items"]]

    midpoints: list[dict] = []
    bodies = sorted(natal_points.keys())

    for a_id, b_id in combinations(bodies, 2):
        a = natal_points[a_id]
        b = natal_points[b_id]
        direct_lon = _shortest_midpoint(a["longitude"], b["longitude"])
        opposite_lon = (direct_lon + 180.0) % 360.0
        direct_info = _make_point_summary(direct_lon, cusps)
        opposite_info = _make_point_summary(opposite_lon, cusps)
        occupied = _find_occupied_by(
            direct_lon, (a_id, b_id), natal_points, occupied_orb,
        )
        midpoints.append({
            "pair": f"{a_id}/{b_id}",
            "from": a_id,
            "from_tr": a["name_tr"],
            "to": b_id,
            "to_tr": b["name_tr"],
            "from_longitude": round(a["longitude"], 6),
            "to_longitude": round(b["longitude"], 6),
            "direct": direct_info,
            "opposite": opposite_info,
            "occupied_by": occupied,
            "occupied_count": len(occupied),
        })

    midpoints.sort(key=lambda r: r["pair"])

    # 45° dial (8. harmonik)
    dial = _build_45_dial(natal_points, midpoints, dial_orb)

    # Özet: occupied midpoint sayısı
    occupied_midpoints = [m for m in midpoints if m["occupied_count"] > 0]
    occupied_midpoints.sort(
        key=lambda m: (-m["occupied_count"], m["occupied_by"][0]["orb"]),
    )

    natal_summary = {
        "birth_date": natal_chart["birth"]["date"],
        "birth_time": natal_chart["birth"]["time"],
        "house_system": natal_chart["meta"]["house_system"],
        "ascendant_sign_tr": natal_chart["angles"]["ascendant"]["sign_tr"],
        "midheaven_sign_tr": natal_chart["angles"]["midheaven"]["sign_tr"],
    }

    limitations = [
        "Midpoints natal harita üzerinde sabittir; tarih bağımlı değildir.",
        "Hipotetik gezegenler (Cupido, Hades, Zeus, Kronos, Apollon, Admetos, "
        "Vulkanus, Poseidon) v1'de yoktur.",
        "90° dial görselleştirme v2'ye bırakıldı; bu sürüm 45° dial ile sınırlı.",
        "Antiscia ve diğer simetrik nokta katmanları v1'de yoktur.",
    ]
    time_confidence = natal_chart["data_quality"].get("birth_time_confidence")
    if time_confidence in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; ASC/MC midpoint'leri ve ev yerleşimleri "
            "ciddi belirsizlik taşır."
        )

    return {
        "status": "available",
        "version": MIDPOINTS_VERSION,
        "method": "midpoints_cosmobiology_v1",
        "occupied_orb": occupied_orb,
        "dial_orb": dial_orb,
        "bodies_included": bodies,
        "bodies_count": len(bodies),
        "midpoints_count": len(midpoints),
        "occupied_midpoints_count": len(occupied_midpoints),
        "natal_summary": natal_summary,
        "midpoints": midpoints,
        "occupied_midpoints_summary": occupied_midpoints,
        "dial_45": dial,
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


def build_midpoints_markdown(
    data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    natal_summary = data["natal_summary"]
    midpoints = data["midpoints"]
    occupied = data["occupied_midpoints_summary"]
    dial = data["dial_45"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Midpoints"',
        'type: "midpoints_pack"',
        'source: "western_api_v2_midpoints"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'method: "{data["method"]}"',
        f'occupied_orb: {data["occupied_orb"]}',
        f'dial_orb: {data["dial_orb"]}',
        f'bodies_count: {data["bodies_count"]}',
        f'midpoints_count: {data["midpoints_count"]}',
        f'occupied_count: {data["occupied_midpoints_count"]}',
        f'house_system: "{natal_summary["house_system"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{MIDPOINTS_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Midpoints",
        "",
        "## Kullanım Notu",
        "",
        "- Midpoints Cosmobiology / Uranian katmanıdır; 14 natal nokta arasındaki 91 ikili midpoint.",
        "- Her midpoint hem doğrudan hem karşı (180°) ekseniyle birlikte sunulur.",
        f"- Orb {data['occupied_orb']}° (klasik Cosmobiology). 'occupied_by' bir natal noktanın midpoint'e teması.",
        "- 45° dial (8. harmonik) ek katman olarak eklenmiştir; aynı dial pozisyonundaki noktalar 'eksen' oluşturur.",
        "- Midpoints natal sabittir; tarih bağımsız.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Özet",
        "",
        f"- Doğum: {natal_summary['birth_date']} {natal_summary['birth_time']}",
        f"- Ev sistemi: {natal_summary['house_system']}",
        f"- Yükselen: {natal_summary['ascendant_sign_tr']}",
        f"- MC: {natal_summary['midheaven_sign_tr']}",
        f"- Hesaplanan midpoint sayısı: {data['midpoints_count']}",
        f"- Occupied midpoint sayısı: {data['occupied_midpoints_count']}",
        f"- Occupied orb: {data['occupied_orb']}°",
        f"- 45° dial axe sayısı: {len(dial['occupied_axes'])}",
        "",
    ]

    if occupied:
        occupied_rows = [
            (
                m["pair"],
                f'{m["direct"]["sign_tr"]} {m["direct"]["degree_str"]}',
                f'e{m["direct"]["house"]}',
                m["occupied_count"],
                ", ".join(
                    f'{o["point"]}({o["side"][:3]},{o["orb"]:.2f}°)'
                    for o in m["occupied_by"][:5]
                ),
            )
            for m in occupied
        ]
        occupied_table = _md_table(
            ["Çift", "Direct Konum", "Direct Ev", "Sayı", "Occupied (ilk 5)"],
            occupied_rows,
        )
    else:
        occupied_table = "_Orb içinde occupied midpoint bulunmuyor._"

    occupied_section = [
        "## Occupied Midpoints (Doğrudan + Karşı, Orb İçinde)",
        "",
        occupied_table,
        "",
    ]

    all_rows = [
        (
            m["pair"],
            f'{m["direct"]["sign_tr"]} {m["direct"]["degree_str"]}',
            f'e{m["direct"]["house"]}',
            f'{m["opposite"]["sign_tr"]} {m["opposite"]["degree_str"]}',
            f'e{m["opposite"]["house"]}',
            m["occupied_count"],
        )
        for m in midpoints
    ]
    all_section = [
        "## Tüm Midpointler",
        "",
        _md_table(
            [
                "Çift",
                "Direct Konum",
                "Direct Ev",
                "Opposite Konum",
                "Opposite Ev",
                "Occupied",
            ],
            all_rows,
        ),
        "",
    ]

    if dial["occupied_axes"]:
        axis_rows = [
            (
                i + 1,
                ", ".join(axis["members_tr"]),
                f'{axis["dial_center"]:.4f}°',
                f'{axis["span"]:.4f}°',
                "Evet" if axis.get("wrap_around") else "Hayır",
            )
            for i, axis in enumerate(dial["occupied_axes"])
        ]
        axes_table = _md_table(
            ["#", "Üyeler", "Dial Merkezi", "Yayılım", "Wrap"],
            axis_rows,
        )
    else:
        axes_table = "_45° dial üzerinde orb içinde eksen bulunmuyor._"

    dial_section = [
        "## 45° Dial (8. Harmonik) Eksenleri",
        "",
        f"_Orb: {data['dial_orb']}°. Aynı dial pozisyonunda kümelenen natal noktalar eksen oluşturur._",
        "",
        axes_table,
        "",
        "### 45° Dial — Natal Nokta Konumları",
        "",
        _md_table(
            ["Nokta", "Natal Boylam", "Dial Konum (0-45°)"],
            [
                (item["name_tr"], f'{item["natal_longitude"]:.4f}°', f'{item["dial_position"]:.4f}°')
                for item in dial["items"]
            ],
        ),
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
        "Aşağıdaki JSON tüm midpoint datasının makine-okunur kopyasıdır.",
        "",
        "```json",
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *occupied_section,
        *dial_section,
        *all_section,
        *limit_section,
        *technical_section,
    ])
