#!/usr/bin/env python3
"""Relocation chart calculations.

Relocation (taşınma) haritası: aynı UTC doğum anının FARKLI bir konum
için yeniden kurulmasıdır. Gezegen boylamları değişmez (aynı an), ama
ASC/MC/evler yeni konuma göre tamamen değişir.

Çıktı:
- Relocated harita (tam core chart)
- Natal ↔ relocated karşılaştırma: ASC/MC kayması, gezegenlerin ev değişimleri
- Angular hale gelen / angularlığı kaybolan gezegenler

Bu bir veri paketidir; yorum içermez.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


RELOCATION_VERSION = "1.0.0"

ANGULAR_HOUSES = {1, 4, 7, 10}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class RelocationInputError(ValueError):
    """Relocation için geçersiz input."""


class RelocationCalculationError(RuntimeError):
    """Relocation hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise RelocationInputError("JSON gövdesi nesne olmalıdır")
    if not isinstance(payload.get("birth"), dict):
        raise RelocationInputError("birth (natal doğum verisi) zorunludur")

    reloc = payload.get("relocation") or {}
    if not isinstance(reloc, dict):
        raise RelocationInputError("relocation alanı nesne olmalıdır")

    if "lat" not in reloc or "lon" not in reloc:
        raise RelocationInputError("relocation.lat ve relocation.lon zorunludur")
    try:
        lat = float(reloc["lat"])
        lon = float(reloc["lon"])
    except (TypeError, ValueError) as exc:
        raise RelocationInputError("relocation.lat/lon sayı olmalıdır") from exc
    if not -90.0 <= lat <= 90.0:
        raise RelocationInputError("relocation.lat -90 ile 90 arasında olmalıdır")
    if not -180.0 <= lon <= 180.0:
        raise RelocationInputError("relocation.lon -180 ile 180 arasında olmalıdır")

    tz_id = reloc.get("timezone_id")
    if tz_id:
        try:
            ZoneInfo(str(tz_id))
        except ZoneInfoNotFoundError as exc:
            raise RelocationInputError(
                f"Geçersiz relocation.timezone_id: {tz_id}"
            ) from exc

    return {
        "lat": lat,
        "lon": lon,
        "timezone_id": str(tz_id) if tz_id else "UTC",
        "place": reloc.get("place"),
    }


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_relocation(payload: dict) -> dict:
    """Relocation haritası + natal karşılaştırma."""

    reloc = _validate_input(payload)

    # 1) Natal harita (orijinal konum)
    natal_options = payload.get("options") or {}
    natal_chart = calculate_core_chart({
        "birth": payload["birth"],
        "options": natal_options,
    })

    # 2) Relocated harita: aynı UTC an, yeni konum
    birth_utc = datetime.fromisoformat(
        natal_chart["birth"]["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)

    reloc_payload = {
        "birth": {
            "year": birth_utc.year,
            "month": birth_utc.month,
            "day": birth_utc.day,
            "hour": birth_utc.hour,
            "minute": birth_utc.minute,
            "second": birth_utc.second,
            "lat": reloc["lat"],
            "lon": reloc["lon"],
            "timezone_id": "UTC",
            "utc": True,
            "place": reloc.get("place") or "Relocation",
            "time_confidence": payload["birth"].get("time_confidence", "high"),
        },
        "options": natal_options,
    }
    relocated_chart = calculate_core_chart(reloc_payload)

    # 3) Karşılaştırma
    natal_angles = natal_chart["angles"]
    reloc_angles = relocated_chart["angles"]

    angle_comparison = {}
    for angle_id in ("ascendant", "midheaven", "descendant", "imum_coeli"):
        na = natal_angles.get(angle_id)
        ra = reloc_angles.get(angle_id)
        if not na or not ra:
            continue
        shift = ((ra["longitude"] - na["longitude"] + 180.0) % 360.0) - 180.0
        angle_comparison[angle_id] = {
            "natal": f'{na["sign_tr"]} {na["degree_str"]}',
            "relocated": f'{ra["sign_tr"]} {ra["degree_str"]}',
            "shift_degrees": round(shift, 4),
            "sign_changed": na["sign_tr"] != ra["sign_tr"],
        }

    # Gezegen ev değişimleri
    natal_houses = {
        p["id"]: p.get("house") for p in natal_chart["planets"]["items"]
    }
    house_changes = []
    newly_angular = []
    lost_angular = []
    for p in relocated_chart["planets"]["items"]:
        natal_house = natal_houses.get(p["id"])
        reloc_house = p.get("house")
        if natal_house is None or reloc_house is None:
            continue
        if natal_house != reloc_house:
            house_changes.append({
                "planet": p["id"],
                "planet_tr": p.get("name_tr"),
                "position": f'{p["sign_tr"]} {p["degree_str"]}',
                "natal_house": natal_house,
                "relocated_house": reloc_house,
            })
        was_angular = natal_house in ANGULAR_HOUSES
        is_angular = reloc_house in ANGULAR_HOUSES
        if is_angular and not was_angular:
            newly_angular.append({
                "planet": p["id"],
                "planet_tr": p.get("name_tr"),
                "relocated_house": reloc_house,
            })
        elif was_angular and not is_angular:
            lost_angular.append({
                "planet": p["id"],
                "planet_tr": p.get("name_tr"),
                "natal_house": natal_house,
                "relocated_house": reloc_house,
            })

    limitations = [
        "Relocation gezegen boylamlarını değiştirmez; yalnızca ASC/MC ve ev yerleşimleri değişir.",
        "Relocated harita UTC referanslıdır; yerel saat gösterimi için relocation.timezone_id bilgilendirme amaçlıdır.",
        "Bu veri paketi yorum içermez.",
    ]
    conf = natal_chart["data_quality"].get("birth_time_confidence")
    if conf in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; hem natal hem relocated ASC/MC/evler belirsizlik taşır."
        )

    return {
        "status": "available",
        "version": RELOCATION_VERSION,
        "method": "relocation_same_utc_new_location_v1",
        "natal_location": {
            "lat": float(natal_chart["birth"]["latitude"]),
            "lon": float(natal_chart["birth"]["longitude"]),
            "place": natal_chart["birth"].get("place"),
        },
        "relocation_location": reloc,
        "angle_comparison": angle_comparison,
        "house_changes": house_changes,
        "newly_angular": newly_angular,
        "lost_angular": lost_angular,
        "relocated_chart": relocated_chart,
        "natal_chart": natal_chart,
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


def build_relocation_markdown(
    data: dict,
    person_name: str,
    group_name: str,
    place_slug: str,
    generated_at: str | None = None,
) -> str:
    reloc = data["relocation_location"]
    angle_cmp = data["angle_comparison"]
    chart = data["relocated_chart"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Relocation {place_slug}"',
        'type: "relocation_pack"',
        'source: "western_api_v2_relocation"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'method: "{data["method"]}"',
        f'relocation_place: "{reloc.get("place") or place_slug}"',
        f'relocation_lat: {reloc["lat"]}',
        f'relocation_lon: {reloc["lon"]}',
        f'relocated_asc: "{chart["angles"]["ascendant"]["sign_tr"]} {chart["angles"]["ascendant"]["degree_str"]}"',
        f'relocated_mc: "{chart["angles"]["midheaven"]["sign_tr"]} {chart["angles"]["midheaven"]["degree_str"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{RELOCATION_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Relocation: {reloc.get('place') or place_slug}",
        "",
        "## Kullanım Notu",
        "",
        "- Relocation, aynı doğum anının farklı konum için yeniden kurulmasıdır.",
        "- Gezegen boylamları değişmez; ASC/MC ve evler yeni konuma göre değişir.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Konum",
        "",
        f"- Natal: {data['natal_location'].get('place') or '-'} ({data['natal_location']['lat']:.4f}, {data['natal_location']['lon']:.4f})",
        f"- Relocation: **{reloc.get('place') or place_slug}** ({reloc['lat']:.4f}, {reloc['lon']:.4f})",
        "",
    ]

    angle_rows = [
        (
            angle_id.upper().replace("ANT", "").replace("_", " ")[:3],
            cmp_data["natal"],
            cmp_data["relocated"],
            f'{cmp_data["shift_degrees"]:+.2f}°',
            "Evet" if cmp_data["sign_changed"] else "-",
        )
        for angle_id, cmp_data in angle_cmp.items()
    ]
    angles_section = [
        "## Eksen Karşılaştırması",
        "",
        _md_table(
            ["Eksen", "Natal", "Relocated", "Kayma", "Burç Değişti"],
            angle_rows,
        ),
        "",
    ]

    house_rows = [
        (
            h["planet_tr"] or h["planet"],
            h["position"],
            f'e{h["natal_house"]}',
            f'e{h["relocated_house"]}',
        )
        for h in data["house_changes"]
    ]
    changes_section = [
        "## Ev Değişimleri",
        "",
        _md_table(
            ["Gezegen", "Konum", "Natal Ev", "Relocated Ev"],
            house_rows,
        ) if house_rows else "_Ev değişimi yok._",
        "",
    ]

    angular_lines = ["## Angular Değişimler", ""]
    if data["newly_angular"]:
        angular_lines.append("**Angular hale gelenler:**")
        angular_lines.extend(
            f"- {a['planet_tr'] or a['planet']} → e{a['relocated_house']}"
            for a in data["newly_angular"]
        )
        angular_lines.append("")
    if data["lost_angular"]:
        angular_lines.append("**Angularlığı kaybolanlar:**")
        angular_lines.extend(
            f"- {a['planet_tr'] or a['planet']}: e{a['natal_house']} → e{a['relocated_house']}"
            for a in data["lost_angular"]
        )
        angular_lines.append("")
    if not data["newly_angular"] and not data["lost_angular"]:
        angular_lines.append("_Angular değişim yok._")
        angular_lines.append("")

    planet_rows = [
        (
            p.get("name_tr") or p["id"],
            f'{p["sign_tr"]} {p["degree_str"]}',
            f'e{p["house"]}' if p.get("house") else "-",
            "R" if p.get("retrograde") else "-",
        )
        for p in chart["planets"]["items"]
    ]
    planets_section = [
        "## Relocated Gezegen Konumları",
        "",
        _md_table(["Gezegen", "Konum", "Ev", "Retro"], planet_rows),
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in data.get("limitations", [])],
        "",
    ]

    technical_data = {
        k: v for k, v in data.items()
        if k not in ("relocated_chart", "natal_chart")
    }
    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "Tam harita JSON'ları gömülmez (boyut); karşılaştırma katmanı aşağıdadır.",
        "",
        "```json",
        json.dumps(technical_data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *angles_section,
        *changes_section,
        *angular_lines,
        *planets_section,
        *limit_section,
        *technical_section,
    ])
