#!/usr/bin/env python3
"""Local Space chart calculations.

Local Space: doğum anında doğum yerinden bakıldığında her gezegenin
UFUK KOORDİNATLARI (azimut + yükseklik). Azimut, gezegenin pusula
yönünü verir (0°=Kuzey, 90°=Doğu, 180°=Güney, 270°=Batı).

Local space haritası yön astrolojisidir: ev içinde yön seçimi, şehir
içinde semt yönü, yeryüzünde hedef yönü gibi kullanımlar için gezegen
azimut hatları verir.

Hesap: swe.azalt ile ekvatoryal → ufuk koordinat dönüşümü.

Çıktı:
- Her gezegen için azimut (0-360, kuzeyden saat yönü), yükseklik (altitude)
- Pusula yönü etiketi (K, KD, D, GD, G, GB, B, KB — 16 yön)
- Ufuk üstü/altı bilgisi

Bu bir veri paketidir; yorum içermez.
"""

from __future__ import annotations

import json
from datetime import datetime, timezone

import swisseph as swe

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    _julian_day,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


LOCAL_SPACE_VERSION = "1.0.0"

LS_PLANETS: list[tuple[int, str, str]] = [
    (swe.SUN, "sun", "Güneş"),
    (swe.MOON, "moon", "Ay"),
    (swe.MERCURY, "mercury", "Merkür"),
    (swe.VENUS, "venus", "Venüs"),
    (swe.MARS, "mars", "Mars"),
    (swe.JUPITER, "jupiter", "Jüpiter"),
    (swe.SATURN, "saturn", "Satürn"),
    (swe.URANUS, "uranus", "Uranüs"),
    (swe.NEPTUNE, "neptune", "Neptün"),
    (swe.PLUTO, "pluto", "Plüton"),
]

# 16 pusula yönü (22.5° dilimler, K = 348.75..11.25)
COMPASS_16 = [
    "K", "KKD", "KD", "DKD", "D", "DGD", "GD", "GGD",
    "G", "GGB", "GB", "BGB", "B", "BKB", "KB", "KKB",
]
COMPASS_16_TR = {
    "K": "Kuzey", "KKD": "Kuzey-Kuzeydoğu", "KD": "Kuzeydoğu", "DKD": "Doğu-Kuzeydoğu",
    "D": "Doğu", "DGD": "Doğu-Güneydoğu", "GD": "Güneydoğu", "GGD": "Güney-Güneydoğu",
    "G": "Güney", "GGB": "Güney-Güneybatı", "GB": "Güneybatı", "BGB": "Batı-Güneybatı",
    "B": "Batı", "BKB": "Batı-Kuzeybatı", "KB": "Kuzeybatı", "KKB": "Kuzey-Kuzeybatı",
}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class LocalSpaceInputError(ValueError):
    """Local space için geçersiz input."""


class LocalSpaceCalculationError(RuntimeError):
    """Local space hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _compass_label(azimuth_deg: float) -> str:
    """Azimut → 16 yönlü pusula etiketi (0=K, saat yönü)."""
    index = int(((azimuth_deg + 11.25) % 360.0) // 22.5)
    return COMPASS_16[index]


def _validate_input(payload: dict) -> None:
    if not isinstance(payload, dict):
        raise LocalSpaceInputError("JSON gövdesi nesne olmalıdır")
    if not isinstance(payload.get("birth"), dict):
        raise LocalSpaceInputError("birth (natal doğum verisi) zorunludur")


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_local_space(payload: dict) -> dict:
    """Local space (azimut) hesabı."""

    _validate_input(payload)

    natal_chart = calculate_core_chart({
        "birth": payload["birth"],
        "options": payload.get("options") or {},
    })

    birth_utc = datetime.fromisoformat(
        natal_chart["birth"]["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)
    jd_ut = _julian_day(birth_utc)

    lat = float(natal_chart["birth"]["latitude"])
    lon = float(natal_chart["birth"]["longitude"])
    geopos = (lon, lat, 0.0)

    items = []
    skipped = []
    for planet_id, body_id, name_tr in LS_PLANETS:
        try:
            values, _ = swe.calc_ut(
                jd_ut, planet_id,
                swe.FLG_SWIEPH | swe.FLG_EQUATORIAL,
            )
        except swe.Error:
            skipped.append({"planet": body_id, "reason": "ephemeris_error"})
            continue
        ra, decl = float(values[0]), float(values[1])

        # Ekvatoryal → ufuk (azimut/altitude). swe.azalt EQU2HOR:
        # xin = [RA, decl, distance]
        try:
            azalt = swe.azalt(
                jd_ut,
                swe.EQU2HOR,
                geopos,
                0.0,   # atmosferik basınç (0 = refraksiyon yok, true altitude)
                0.0,   # sıcaklık
                [ra, decl, 1.0],
            )
        except swe.Error:
            skipped.append({"planet": body_id, "reason": "azalt_error"})
            continue

        # swe.azalt dönüşü: [azimuth, true_altitude, apparent_altitude]
        # Swiss Ephemeris azimutu GÜNEYDEN batıya doğru ölçer;
        # pusula azimutu (kuzeyden saat yönü) = (azimuth + 180) % 360
        swe_azimuth = float(azalt[0])
        compass_azimuth = (swe_azimuth + 180.0) % 360.0
        altitude = float(azalt[1])

        compass = _compass_label(compass_azimuth)
        items.append({
            "planet": body_id,
            "planet_tr": name_tr,
            "azimuth": round(compass_azimuth, 4),
            "altitude": round(altitude, 4),
            "above_horizon": altitude > 0,
            "compass": compass,
            "compass_tr": COMPASS_16_TR[compass],
        })

    # Azimuta göre sırala
    items.sort(key=lambda r: r["azimuth"])

    limitations = [
        "Azimut pusula konvansiyonundadır: 0°=Kuzey, 90°=Doğu, saat yönü.",
        "Yükseklik (altitude) refraksiyonsuz gerçek değerdir.",
        "Local space hatları büyük daire olarak uzar; bu paket başlangıç azimutunu verir.",
        "Hedef konumlara yön analizi (bearing to target) v2'ye bırakıldı.",
        "Bu veri paketi yorum içermez.",
    ]
    conf = natal_chart["data_quality"].get("birth_time_confidence")
    if conf in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; azimutlar dakikalar içinde belirgin değişir."
        )

    return {
        "status": "available",
        "version": LOCAL_SPACE_VERSION,
        "method": "local_space_azimuth_v1",
        "birth_utc": natal_chart["birth"]["utc_datetime"],
        "location": {
            "lat": lat,
            "lon": lon,
            "place": natal_chart["birth"].get("place"),
        },
        "items": items,
        "skipped": skipped,
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


def build_local_space_markdown(
    data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    items = data["items"]
    loc = data["location"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Local Space"',
        'type: "local_space_pack"',
        'source: "western_api_v2_local_space"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'method: "{data["method"]}"',
        f'birth_utc: "{data["birth_utc"]}"',
        f'location_place: "{loc.get("place") or "-"}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{LOCAL_SPACE_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Local Space",
        "",
        "## Kullanım Notu",
        "",
        "- Local space, doğum anında doğum yerinden gezegenlerin PUSULA YÖNLERİNİ verir.",
        "- Azimut: 0°=Kuzey, 90°=Doğu, 180°=Güney, 270°=Batı (saat yönü).",
        "- Yükseklik pozitifse gezegen ufkun üstünde, negatifse altındadır.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Konum",
        "",
        f"- {loc.get('place') or '-'} ({loc['lat']:.4f}, {loc['lon']:.4f})",
        f"- UTC an: {data['birth_utc']}",
        "",
    ]

    rows = [
        (
            item["planet_tr"],
            f'{item["azimuth"]:.2f}°',
            f'{item["compass"]} ({item["compass_tr"]})',
            f'{item["altitude"]:+.2f}°',
            "Üstünde" if item["above_horizon"] else "Altında",
        )
        for item in items
    ]
    table_section = [
        "## Gezegen Yönleri (Azimuta Göre Sıralı)",
        "",
        _md_table(
            ["Gezegen", "Azimut", "Pusula", "Yükseklik", "Ufuk"],
            rows,
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
        "```json",
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *table_section,
        *limit_section,
        *technical_section,
    ])
