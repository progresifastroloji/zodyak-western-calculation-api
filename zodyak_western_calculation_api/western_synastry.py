#!/usr/bin/env python3
"""Synastry (ilişki astrolojisi) calculations.

İki natal harita arasındaki etkileşim analizi:
- Inter-aspect matrisi: A'nın gezegenleri × B'nin gezegenleri (majör + minör)
- Ev overlay: A'nın gezegenleri B'nin evlerinde (ve tersi)
- Angle temasları: bir tarafın gezegeni diğerinin ASC/DSC/MC/IC'sine değiyor mu
- Node temasları: karşılıklı düğüm kavuşumları
- Element/nitelik uyumu: iki haritanın dağılım karşılaştırması
- Özet skorlama YOK — bu bir teknik veri paketidir, yorum katmanı dışarıdadır

Synastry orbları natal orblardan daha sıkıdır (klasik pratik):
majör açılar için 6°, luminary bonusu +1°, minör açılar 2°.

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


SYNASTRY_VERSION = "1.0.0"

# Synastry orb profili (natal'dan sıkı — klasik pratik)
SYNASTRY_ORBS = {
    "conjunction": 6.0,
    "opposition": 6.0,
    "square": 5.0,
    "trine": 5.0,
    "sextile": 4.0,
    "quincunx": 2.5,
    "semisextile": 1.5,
    "semisquare": 1.5,
    "quintile": 1.5,
    "sesquiquadrate": 1.5,
    "biquintile": 1.5,
}
SYNASTRY_LUMINARY_BONUS = 1.0

# Aspect tanımları: (id, exact, group, nature, tr)
SYNASTRY_ASPECTS = [
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

# Synastry'ye katılan noktalar
SYNASTRY_PLANET_IDS = [
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto", "chiron",
]
SYNASTRY_NODE_IDS = ["mean_node", "true_node", "south_node"]

# Angle teması orbu
ANGLE_CONTACT_ORB = 3.0

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
    "mean_node": "Kuzey Ay Düğümü",
    "true_node": "Kuzey Ay Düğümü",
    "south_node": "Güney Ay Düğümü",
}

ANGLE_TR = {
    "ascendant": "ASC",
    "descendant": "DSC",
    "midheaven": "MC",
    "imum_coeli": "IC",
}

# Klasik önem sıralaması: kişisel gezegen etkileşimleri önce listelensin
PERSONAL_PLANETS = {"sun", "moon", "mercury", "venus", "mars"}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class SynastryInputError(ValueError):
    """Synastry için geçersiz input."""


class SynastryCalculationError(RuntimeError):
    """Synastry hesaplama hatası."""


# ---------------------------------------------------------------------------
# Input doğrulama
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> tuple[dict, dict]:
    """payload.person_a ve payload.person_b nesnelerini doğrular.

    Her biri şu yapıda olmalı:
    {
      "name": "...",             (opsiyonel; markdown için)
      "birth": { ...natal birth payload... },
      "options": { ... }         (opsiyonel; zodiac/house_system)
    }
    """
    if not isinstance(payload, dict):
        raise SynastryInputError("JSON gövdesi nesne olmalıdır")

    person_a = payload.get("person_a")
    person_b = payload.get("person_b")
    if not isinstance(person_a, dict) or not isinstance(person_b, dict):
        raise SynastryInputError(
            "person_a ve person_b nesneleri zorunludur; her biri "
            "{name, birth, options} yapısında olmalıdır"
        )
    if not isinstance(person_a.get("birth"), dict):
        raise SynastryInputError("person_a.birth zorunludur")
    if not isinstance(person_b.get("birth"), dict):
        raise SynastryInputError("person_b.birth zorunludur")

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


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _collect_synastry_points(chart: dict) -> list[dict]:
    """Synastry'ye katılan noktaları topla (gezegenler + düğümler)."""
    points = []
    for planet in chart["planets"]["items"]:
        if planet["id"] in SYNASTRY_PLANET_IDS:
            points.append({
                "id": planet["id"],
                "name_tr": planet.get("name_tr") or PLANET_TR.get(planet["id"]),
                "longitude": planet["longitude"],
                "sign_tr": planet.get("sign_tr"),
                "degree_str": planet.get("degree_str"),
                "house": planet.get("house"),
                "retrograde": planet.get("retrograde", False),
                "kind": "planet",
            })
    seen_node = False
    for node in chart["nodes"]["items"]:
        if node["id"] in SYNASTRY_NODE_IDS:
            # north node tekilleştirme (mean veya true, hangisi varsa ilki)
            if node["id"] in ("mean_node", "true_node"):
                if seen_node:
                    continue
                seen_node = True
                normalized_id = "north_node"
            else:
                normalized_id = node["id"]
            points.append({
                "id": normalized_id,
                "name_tr": PLANET_TR.get(node["id"], node["id"]),
                "longitude": node["longitude"],
                "sign_tr": node.get("sign_tr"),
                "degree_str": node.get("degree_str"),
                "house": node.get("house"),
                "retrograde": node.get("retrograde", False),
                "kind": "node",
            })
    return points


def _orb_for_aspect(aspect_id: str, id_a: str, id_b: str) -> float:
    base = SYNASTRY_ORBS.get(aspect_id, 1.5)
    if id_a in LUMINARIES or id_b in LUMINARIES:
        return base + SYNASTRY_LUMINARY_BONUS
    return base


def _find_interaspects(points_a: list[dict], points_b: list[dict]) -> list[dict]:
    """A × B tüm çiftler için en yakın açıyı bul."""
    results = []
    for pa in points_a:
        for pb in points_b:
            sep = _shortest_separation(pa["longitude"], pb["longitude"])
            best = None
            for aspect_id, exact, group, nature, tr in SYNASTRY_ASPECTS:
                orb_allowed = _orb_for_aspect(aspect_id, pa["id"], pb["id"])
                diff = abs(sep - exact)
                if diff <= orb_allowed and (best is None or diff < best["orb"]):
                    best = {
                        "a_point": pa["id"],
                        "a_point_tr": pa["name_tr"],
                        "a_position": f'{pa["sign_tr"]} {pa["degree_str"]}',
                        "b_point": pb["id"],
                        "b_point_tr": pb["name_tr"],
                        "b_position": f'{pb["sign_tr"]} {pb["degree_str"]}',
                        "aspect": aspect_id,
                        "aspect_tr": tr,
                        "group": group,
                        "nature": nature,
                        "exact_angle": exact,
                        "orb": round(diff, 4),
                        "orb_allowed": round(orb_allowed, 4),
                        "is_personal_pair": (
                            pa["id"] in PERSONAL_PLANETS
                            and pb["id"] in PERSONAL_PLANETS
                        ),
                    }
            if best:
                results.append(best)
    # Sıralama: kişisel çiftler önce, sonra orb
    results.sort(key=lambda r: (not r["is_personal_pair"], r["orb"]))
    return results


def _house_number_for(longitude: float, cusps: list[float]) -> int:
    for i in range(12):
        start = cusps[i]
        end = cusps[(i + 1) % 12]
        if start <= end:
            if start <= longitude < end:
                return i + 1
        else:
            if longitude >= start or longitude < end:
                return i + 1
    return 1


def _house_overlay(points: list[dict], other_chart: dict, direction_label: str) -> list[dict]:
    """Bir tarafın gezegenlerinin diğer tarafın evlerine yerleşimi."""
    cusps = [h["longitude"] for h in other_chart["houses"]["items"]]
    overlay = []
    for p in points:
        house = _house_number_for(p["longitude"], cusps)
        overlay.append({
            "point": p["id"],
            "point_tr": p["name_tr"],
            "position": f'{p["sign_tr"]} {p["degree_str"]}',
            "falls_in_house": house,
            "direction": direction_label,
        })
    overlay.sort(key=lambda r: r["falls_in_house"])
    return overlay


def _angle_contacts(points: list[dict], other_chart: dict, direction_label: str) -> list[dict]:
    """Bir tarafın gezegenlerinin diğer tarafın eksenlerine kavuşumu (orb 3°)."""
    contacts = []
    angles = other_chart["angles"]
    for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
        angle = angles.get(angle_id)
        if not angle:
            continue
        for p in points:
            sep = _shortest_separation(p["longitude"], angle["longitude"])
            if sep <= ANGLE_CONTACT_ORB:
                contacts.append({
                    "point": p["id"],
                    "point_tr": p["name_tr"],
                    "position": f'{p["sign_tr"]} {p["degree_str"]}',
                    "angle": angle_id,
                    "angle_tr": ANGLE_TR.get(angle_id, angle_id),
                    "angle_position": f'{angle.get("sign_tr")} {angle.get("degree_str")}',
                    "orb": round(sep, 4),
                    "direction": direction_label,
                })
    contacts.sort(key=lambda r: r["orb"])
    return contacts


def _distribution_comparison(chart_a: dict, chart_b: dict) -> dict:
    """Element ve nitelik dağılımlarını yan yana koy."""
    def _extract(chart):
        dist = chart.get("distributions") or {}
        return {
            "elements": dist.get("elements") or {},
            "modalities": dist.get("modalities") or dist.get("qualities") or {},
        }
    return {
        "a": _extract(chart_a),
        "b": _extract(chart_b),
    }


def _interaspect_stats(interaspects: list[dict]) -> dict:
    total = len(interaspects)
    harmonious = sum(1 for a in interaspects if a["nature"] == "harmonious")
    challenging = sum(1 for a in interaspects if a["nature"] == "challenging")
    neutral = total - harmonious - challenging
    major = sum(1 for a in interaspects if a["group"] == "major")
    personal = sum(1 for a in interaspects if a["is_personal_pair"])
    tight = sum(1 for a in interaspects if a["orb"] <= 1.0)
    return {
        "total": total,
        "major": major,
        "minor": total - major,
        "harmonious": harmonious,
        "challenging": challenging,
        "neutral_or_adjustment": neutral,
        "personal_pairs": personal,
        "tight_under_1deg": tight,
    }


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_synastry(payload: dict) -> dict:
    """Synastry ana hesabı: iki natal haritanın etkileşim veri paketi."""

    person_a, person_b = _validate_input(payload)
    shared_options = payload.get("options")

    chart_a = calculate_core_chart(_chart_payload_for(person_a, shared_options))
    chart_b = calculate_core_chart(_chart_payload_for(person_b, shared_options))

    name_a = str(person_a.get("name") or "A")
    name_b = str(person_b.get("name") or "B")

    points_a = _collect_synastry_points(chart_a)
    points_b = _collect_synastry_points(chart_b)

    interaspects = _find_interaspects(points_a, points_b)
    stats = _interaspect_stats(interaspects)

    overlay_a_in_b = _house_overlay(points_a, chart_b, "a_in_b_houses")
    overlay_b_in_a = _house_overlay(points_b, chart_a, "b_in_a_houses")

    angle_contacts_a_to_b = _angle_contacts(points_a, chart_b, "a_to_b_angles")
    angle_contacts_b_to_a = _angle_contacts(points_b, chart_a, "b_to_a_angles")

    distributions = _distribution_comparison(chart_a, chart_b)

    def _birth_summary(chart, name):
        birth = chart["birth"]
        return {
            "name": name,
            "date": birth["date"],
            "time": birth["time"],
            "place": birth.get("place"),
            "ascendant_sign_tr": chart["angles"]["ascendant"]["sign_tr"],
            "sun_sign_tr": next(
                (p["sign_tr"] for p in chart["planets"]["items"] if p["id"] == "sun"),
                None,
            ),
            "moon_sign_tr": next(
                (p["sign_tr"] for p in chart["planets"]["items"] if p["id"] == "moon"),
                None,
            ),
            "house_system": chart["meta"]["house_system"],
            "birth_time_confidence": chart["data_quality"].get("birth_time_confidence"),
        }

    limitations = [
        "Bu veri paketi yorum içermez; etkileşimlerin ağırlıklandırılması danışmana aittir.",
        "Synastry orbları natal'dan sıkıdır (kavuşum/karşıt 6°, luminary +1°).",
        "Composite ve Davison haritaları ayrı endpoint'lerdir.",
        "Ev overlay ve angle temasları her iki doğum saatinin güvenilirliğine bağlıdır.",
    ]
    conf_a = chart_a["data_quality"].get("birth_time_confidence")
    conf_b = chart_b["data_quality"].get("birth_time_confidence")
    if conf_a in {"low", "unknown"} or conf_b in {"low", "unknown"}:
        limitations.append(
            "En az bir tarafın doğum saati güveni düşük; ev overlay ve angle "
            "temasları ciddi belirsizlik taşır. Inter-aspect matrisi (Ay hariç) etkilenmez."
        )

    return {
        "status": "available",
        "version": SYNASTRY_VERSION,
        "method": "synastry_interaspects_overlay_v1",
        "orb_profile": {
            "orbs": SYNASTRY_ORBS,
            "luminary_bonus": SYNASTRY_LUMINARY_BONUS,
            "angle_contact_orb": ANGLE_CONTACT_ORB,
        },
        "person_a": _birth_summary(chart_a, name_a),
        "person_b": _birth_summary(chart_b, name_b),
        "interaspects": interaspects,
        "interaspect_stats": stats,
        "house_overlay": {
            "a_planets_in_b_houses": overlay_a_in_b,
            "b_planets_in_a_houses": overlay_b_in_a,
        },
        "angle_contacts": {
            "a_to_b": angle_contacts_a_to_b,
            "b_to_a": angle_contacts_b_to_a,
        },
        "distribution_comparison": distributions,
        "chart_a": chart_a,
        "chart_b": chart_b,
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


def build_synastry_markdown(
    data: dict,
    pair_label: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    pa = data["person_a"]
    pb = data["person_b"]
    stats = data["interaspect_stats"]
    interaspects = data["interaspects"]
    overlay = data["house_overlay"]
    contacts = data["angle_contacts"]

    fm_lines = [
        "---",
        f'title: "Synastry - {pa["name"]} & {pb["name"]}"',
        'type: "synastry_pack"',
        'source: "western_api_v2_synastry"',
        f'pair: "{pair_label}"',
        f'group: "{group_name}"',
        f'person_a: "{pa["name"]}"',
        f'person_b: "{pb["name"]}"',
        f'method: "{data["method"]}"',
        f'interaspect_count: {stats["total"]}',
        f'harmonious: {stats["harmonious"]}',
        f'challenging: {stats["challenging"]}',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{SYNASTRY_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# Synastry: {pa['name']} & {pb['name']}",
        "",
        "## Kullanım Notu",
        "",
        "- Bu dosya iki natal haritanın etkileşim veri paketidir; yorum içermez.",
        "- Inter-aspect matrisi kişisel gezegen çiftleri önce olmak üzere orb'a göre sıralıdır.",
        "- Ev overlay: bir tarafın gezegenleri diğerinin evlerinde nereye düşüyor.",
        "- Angle temasları 3° orb ile sınırlıdır.",
        "",
        "## Taraflar",
        "",
        _md_table(
            ["", "Doğum", "Yer", "Güneş", "Ay", "ASC", "Saat güveni"],
            [
                (
                    pa["name"], f'{pa["date"]} {pa["time"]}', pa.get("place") or "-",
                    pa["sun_sign_tr"], pa["moon_sign_tr"], pa["ascendant_sign_tr"],
                    pa.get("birth_time_confidence") or "-",
                ),
                (
                    pb["name"], f'{pb["date"]} {pb["time"]}', pb.get("place") or "-",
                    pb["sun_sign_tr"], pb["moon_sign_tr"], pb["ascendant_sign_tr"],
                    pb.get("birth_time_confidence") or "-",
                ),
            ],
        ),
        "",
        "## İstatistik",
        "",
        f"- Toplam inter-aspect: **{stats['total']}** (majör {stats['major']}, minör {stats['minor']})",
        f"- Uyumlu: {stats['harmonious']} | Zorlayıcı: {stats['challenging']} | Nötr/uyum: {stats['neutral_or_adjustment']}",
        f"- Kişisel gezegen çifti: {stats['personal_pairs']}",
        f"- 1° altı sıkı açı: {stats['tight_under_1deg']}",
        "",
    ]

    aspect_rows = [
        (
            f'{a["a_point_tr"]} ({pa["name"]})',
            a["a_position"],
            a["aspect_tr"],
            f'{a["b_point_tr"]} ({pb["name"]})',
            a["b_position"],
            f'{a["orb"]:.2f}°',
            "Kişisel" if a["is_personal_pair"] else "-",
            a["nature"],
        )
        for a in interaspects
    ]
    aspects_section = [
        "## Inter-Aspect Matrisi",
        "",
        _md_table(
            ["A Noktası", "A Konum", "Açı", "B Noktası", "B Konum", "Orb", "Kişisel", "Doğa"],
            aspect_rows,
        ) if aspect_rows else "_Orb içinde inter-aspect bulunmuyor._",
        "",
    ]

    overlay_a_rows = [
        (o["point_tr"], o["position"], f'e{o["falls_in_house"]}')
        for o in overlay["a_planets_in_b_houses"]
    ]
    overlay_b_rows = [
        (o["point_tr"], o["position"], f'e{o["falls_in_house"]}')
        for o in overlay["b_planets_in_a_houses"]
    ]
    overlay_section = [
        f"## Ev Overlay — {pa['name']} gezegenleri {pb['name']} evlerinde",
        "",
        _md_table(["Gezegen", "Konum", "Ev"], overlay_a_rows),
        "",
        f"## Ev Overlay — {pb['name']} gezegenleri {pa['name']} evlerinde",
        "",
        _md_table(["Gezegen", "Konum", "Ev"], overlay_b_rows),
        "",
    ]

    contact_rows = []
    for c in contacts["a_to_b"]:
        contact_rows.append((
            f'{c["point_tr"]} ({pa["name"]})',
            c["position"],
            f'{c["angle_tr"]} ({pb["name"]})',
            c["angle_position"],
            f'{c["orb"]:.2f}°',
        ))
    for c in contacts["b_to_a"]:
        contact_rows.append((
            f'{c["point_tr"]} ({pb["name"]})',
            c["position"],
            f'{c["angle_tr"]} ({pa["name"]})',
            c["angle_position"],
            f'{c["orb"]:.2f}°',
        ))
    contacts_section = [
        "## Angle Temasları (3° orb)",
        "",
        _md_table(
            ["Gezegen", "Konum", "Eksen", "Eksen Konumu", "Orb"],
            contact_rows,
        ) if contact_rows else "_Orb içinde angle teması bulunmuyor._",
        "",
    ]

    dist = data["distribution_comparison"]
    dist_section = [
        "## Element / Nitelik Karşılaştırması",
        "",
        "```json",
        json.dumps(dist, ensure_ascii=False, indent=2),
        "```",
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in data.get("limitations", [])],
        "",
    ]

    # Teknik veri: chart_a/chart_b tam JSON'ları çok büyük; sadece synastry
    # katmanını gömelim (chartlar hariç).
    technical_data = {
        k: v for k, v in data.items() if k not in ("chart_a", "chart_b")
    }
    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "Natal haritaların tam JSON'u bu dosyaya gömülmez (boyut); synastry katmanı aşağıdadır.",
        "",
        "```json",
        json.dumps(technical_data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *aspects_section,
        *overlay_section,
        *contacts_section,
        *dist_section,
        *limit_section,
        *technical_section,
    ])
