#!/usr/bin/env python3
"""Davison relationship chart calculations.

Davison haritası: iki doğum anının TAM ORTA ZAMANI ve iki doğum yerinin
ORTA NOKTASI (great-circle midpoint) için kurulan GERÇEK bir haritadır.
Composite'ten farkı: Davison gerçek bir gökyüzü anına karşılık gelir,
dolayısıyla tüm natal teknikler (transitler dahil) uygulanabilir.

Hesap:
- Orta zaman: iki UTC doğum anının aritmetik ortası
- Orta yer: iki koordinatın küresel (great-circle) orta noktası
- Harita: calculate_core_chart ile normal natal hesap (tüm paketler kullanılabilir)

Bu bir veri paketidir; yorum içermez.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone, timedelta
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


DAVISON_VERSION = "1.0.0"
DEFAULT_TZ = "UTC"


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class DavisonInputError(ValueError):
    """Davison için geçersiz input."""


class DavisonCalculationError(RuntimeError):
    """Davison hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> tuple[dict, dict]:
    if not isinstance(payload, dict):
        raise DavisonInputError("JSON gövdesi nesne olmalıdır")
    person_a = payload.get("person_a")
    person_b = payload.get("person_b")
    if not isinstance(person_a, dict) or not isinstance(person_b, dict):
        raise DavisonInputError(
            "person_a ve person_b nesneleri zorunludur; her biri "
            "{name, birth, options} yapısında olmalıdır"
        )
    if not isinstance(person_a.get("birth"), dict):
        raise DavisonInputError("person_a.birth zorunludur")
    if not isinstance(person_b.get("birth"), dict):
        raise DavisonInputError("person_b.birth zorunludur")
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


def _birth_utc(chart: dict) -> datetime:
    birth = chart["birth"]
    dt = datetime.fromisoformat(birth["utc_datetime"].replace("Z", "+00:00"))
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def _midpoint_datetime(dt_a: datetime, dt_b: datetime) -> datetime:
    """İki UTC anın aritmetik ortası."""
    delta = dt_b - dt_a
    return dt_a + delta / 2


def _great_circle_midpoint(
    lat1_deg: float, lon1_deg: float,
    lat2_deg: float, lon2_deg: float,
) -> tuple[float, float]:
    """İki koordinatın great-circle orta noktası (standart formül)."""
    lat1 = math.radians(lat1_deg)
    lon1 = math.radians(lon1_deg)
    lat2 = math.radians(lat2_deg)
    lon2 = math.radians(lon2_deg)

    d_lon = lon2 - lon1
    bx = math.cos(lat2) * math.cos(d_lon)
    by = math.cos(lat2) * math.sin(d_lon)

    lat_mid = math.atan2(
        math.sin(lat1) + math.sin(lat2),
        math.sqrt((math.cos(lat1) + bx) ** 2 + by ** 2),
    )
    lon_mid = lon1 + math.atan2(by, math.cos(lat1) + bx)

    # Normalize
    lat_mid_deg = math.degrees(lat_mid)
    lon_mid_deg = ((math.degrees(lon_mid) + 540.0) % 360.0) - 180.0
    return round(lat_mid_deg, 6), round(lon_mid_deg, 6)


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_davison(payload: dict) -> dict:
    """Davison haritası ana hesabı."""

    person_a, person_b = _validate_input(payload)
    shared_options = payload.get("options")

    chart_a = calculate_core_chart(_chart_payload_for(person_a, shared_options))
    chart_b = calculate_core_chart(_chart_payload_for(person_b, shared_options))

    name_a = str(person_a.get("name") or "A")
    name_b = str(person_b.get("name") or "B")

    # Orta zaman
    dt_a = _birth_utc(chart_a)
    dt_b = _birth_utc(chart_b)
    dt_mid = _midpoint_datetime(dt_a, dt_b)

    # Orta yer (great-circle)
    lat_a = float(chart_a["birth"]["latitude"])
    lon_a = float(chart_a["birth"]["longitude"])
    lat_b = float(chart_b["birth"]["latitude"])
    lon_b = float(chart_b["birth"]["longitude"])
    lat_mid, lon_mid = _great_circle_midpoint(lat_a, lon_a, lat_b, lon_b)

    # Davison haritası: gerçek natal hesap (UTC an + orta konum)
    davison_options = {}
    if isinstance(shared_options, dict):
        davison_options.update(shared_options)
    davison_payload = {
        "birth": {
            "year": dt_mid.year,
            "month": dt_mid.month,
            "day": dt_mid.day,
            "hour": dt_mid.hour,
            "minute": dt_mid.minute,
            "second": dt_mid.second,
            "lat": lat_mid,
            "lon": lon_mid,
            "timezone_id": "UTC",
            "utc": True,
            "place": f"Davison midpoint ({name_a} & {name_b})",
            "time_confidence": "high",
        },
        "options": davison_options or {"zodiac": "tropical", "house_system": "placidus"},
    }
    davison_chart = calculate_core_chart(davison_payload)

    def _birth_summary(chart, name):
        birth = chart["birth"]
        return {
            "name": name,
            "date": birth["date"],
            "time": birth["time"],
            "utc_datetime": birth["utc_datetime"],
            "place": birth.get("place"),
            "lat": float(birth["latitude"]),
            "lon": float(birth["longitude"]),
            "birth_time_confidence": chart["data_quality"].get("birth_time_confidence"),
        }

    limitations = [
        "Davison gerçek bir gökyüzü anına karşılık gelir; transitler dahil natal teknikler uygulanabilir.",
        "Orta yer great-circle (küresel) yöntemle hesaplanır.",
        "Davison haritasının saat dilimi UTC referanslıdır.",
        "Bu veri paketi yorum içermez.",
    ]
    conf_a = chart_a["data_quality"].get("birth_time_confidence")
    conf_b = chart_b["data_quality"].get("birth_time_confidence")
    if conf_a in {"low", "unknown"} or conf_b in {"low", "unknown"}:
        limitations.append(
            "En az bir tarafın doğum saati güveni düşük; Davison orta anı ve "
            "buna bağlı ASC/MC/evler ciddi belirsizlik taşır."
        )

    return {
        "status": "available",
        "version": DAVISON_VERSION,
        "method": "davison_time_space_midpoint_v1",
        "person_a": _birth_summary(chart_a, name_a),
        "person_b": _birth_summary(chart_b, name_b),
        "davison_moment": {
            "utc_datetime": dt_mid.isoformat().replace("+00:00", "Z"),
            "lat": lat_mid,
            "lon": lon_mid,
        },
        "davison_chart": davison_chart,
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


def build_davison_markdown(
    data: dict,
    pair_label: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    pa = data["person_a"]
    pb = data["person_b"]
    moment = data["davison_moment"]
    chart = data["davison_chart"]
    angles = chart["angles"]

    fm_lines = [
        "---",
        f'title: "Davison - {pa["name"]} & {pb["name"]}"',
        'type: "davison_pack"',
        'source: "western_api_v2_davison"',
        f'pair: "{pair_label}"',
        f'group: "{group_name}"',
        f'person_a: "{pa["name"]}"',
        f'person_b: "{pb["name"]}"',
        f'method: "{data["method"]}"',
        f'davison_utc: "{moment["utc_datetime"]}"',
        f'davison_lat: {moment["lat"]}',
        f'davison_lon: {moment["lon"]}',
        f'davison_asc: "{angles["ascendant"]["sign_tr"]} {angles["ascendant"]["degree_str"]}"',
        f'davison_mc: "{angles["midheaven"]["sign_tr"]} {angles["midheaven"]["degree_str"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{DAVISON_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# Davison: {pa['name']} & {pb['name']}",
        "",
        "## Kullanım Notu",
        "",
        "- Davison, iki doğumun ORTA ZAMANI ve ORTA YERİ için kurulan GERÇEK bir haritadır.",
        "- Composite'ten farkı: gerçek gökyüzü anına karşılık gelir; transit/progresyon uygulanabilir.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Taraflar",
        "",
        f"- **{pa['name']}**: {pa['date']} {pa['time']} — {pa.get('place') or '-'} ({pa['lat']:.4f}, {pa['lon']:.4f})",
        f"- **{pb['name']}**: {pb['date']} {pb['time']} — {pb.get('place') or '-'} ({pb['lat']:.4f}, {pb['lon']:.4f})",
        "",
        "## Davison Anı ve Yeri",
        "",
        f"- UTC an: **{moment['utc_datetime']}**",
        f"- Orta nokta: lat **{moment['lat']:.4f}**, lon **{moment['lon']:.4f}**",
        "",
        "## Davison Eksenler",
        "",
        f"- ASC: **{angles['ascendant']['sign_tr']} {angles['ascendant']['degree_str']}**",
        f"- MC: **{angles['midheaven']['sign_tr']} {angles['midheaven']['degree_str']}**",
        f"- Ev sistemi: {chart['meta']['house_system']}",
        "",
    ]

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
        "## Davison Gezegen Konumları",
        "",
        _md_table(["Gezegen", "Konum", "Ev", "Retro"], planet_rows),
        "",
    ]

    major_aspects = (chart.get("aspects") or {}).get("major") or []
    aspect_rows = [
        (
            a["from"],
            a["type"],
            a["to"],
            f'{a["orb"]:.2f}°',
        )
        for a in major_aspects
    ]
    aspects_section = [
        "## Davison Majör Açılar",
        "",
        _md_table(["Nokta A", "Açı", "Nokta B", "Orb"], aspect_rows)
        if aspect_rows else "_Majör açı bulunmuyor._",
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in data.get("limitations", [])],
        "",
    ]

    # Davison chart tam JSON büyük; teknik veri olarak sadece özet + moment
    technical_data = {
        k: v for k, v in data.items() if k != "davison_chart"
    }
    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "Davison haritasının tam JSON'u bu dosyaya gömülmez (boyut); özet katman aşağıdadır.",
        "Tam harita için /davison/preview endpoint'i kullanılabilir.",
        "",
        "```json",
        json.dumps(technical_data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *planets_section,
        *aspects_section,
        *limit_section,
        *technical_section,
    ])
