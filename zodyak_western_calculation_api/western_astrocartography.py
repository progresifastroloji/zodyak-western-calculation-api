#!/usr/bin/env python3
"""Astrocartography (ACG) calculations.

Her gezegenin doğum anındaki konumuna göre dünya üzerinde dört hat türü:
- MC hattı: gezegenin culminate ettiği boylam (dikey çizgi)
- IC hattı: anti-culminate boylamı (MC + 180°)
- ASC hattı: gezegenin doğduğu (rising) noktaların eğrisi
- DSC hattı: gezegenin battığı (setting) noktaların eğrisi

Hesap yöntemi (standart ACG matematiği):
- MC hattı boylamı: gezegenin RA'sı ile GST'den λ = RA - GST (derece)
- IC hattı: MC + 180°
- ASC/DSC hatları: her enlem için gezegenin ufukta olduğu boylam çözülür:
  cos(H) = -tan(φ) * tan(δ)  →  H bulunur, boylam λ = RA ± H - GST
  (+H batış, -H doğuş; kutup bölgelerinde |tan φ tan δ| > 1 ise hat yoktur)

Çıktı:
- Her gezegen için MC/IC boylamları (sabit meridyenler)
- Her gezegen için ASC/DSC eğrileri (enlem -66..+66, 2° adım, boylam listesi)
- Kullanıcının verdiği ilgi konumlarına (interest_points) en yakın hatlar

Bu bir veri paketidir; yorum içermez.
"""

from __future__ import annotations

import json
import math
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


ACG_VERSION = "1.0.0"

ACG_PLANETS: list[tuple[int, str, str]] = [
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

# ASC/DSC eğrileri için enlem taraması
CURVE_LAT_MIN = -66.0
CURVE_LAT_MAX = 66.0
CURVE_LAT_STEP = 2.0

# İlgi noktası yakınlık eşiği (derece cinsinden boylam farkı)
INTEREST_ORB_DEG = 5.0


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class AstrocartographyInputError(ValueError):
    """ACG için geçersiz input."""


class AstrocartographyCalculationError(RuntimeError):
    """ACG hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> list[dict]:
    if not isinstance(payload, dict):
        raise AstrocartographyInputError("JSON gövdesi nesne olmalıdır")
    if not isinstance(payload.get("birth"), dict):
        raise AstrocartographyInputError("birth (natal doğum verisi) zorunludur")

    acg = payload.get("astrocartography") or {}
    if not isinstance(acg, dict):
        raise AstrocartographyInputError("astrocartography alanı nesne olmalıdır")

    interest_points = acg.get("interest_points") or []
    if not isinstance(interest_points, list):
        raise AstrocartographyInputError(
            "astrocartography.interest_points liste olmalıdır"
        )
    validated_points = []
    for i, pt in enumerate(interest_points[:20]):  # max 20 nokta
        if not isinstance(pt, dict) or "lat" not in pt or "lon" not in pt:
            raise AstrocartographyInputError(
                f"interest_points[{i}] için lat ve lon zorunludur"
            )
        try:
            validated_points.append({
                "name": str(pt.get("name") or f"Nokta-{i + 1}"),
                "lat": float(pt["lat"]),
                "lon": float(pt["lon"]),
            })
        except (TypeError, ValueError) as exc:
            raise AstrocartographyInputError(
                f"interest_points[{i}].lat/lon sayı olmalıdır"
            ) from exc
    return validated_points


def _normalize_lon(lon: float) -> float:
    """Boylamı -180..+180 aralığına getir."""
    return ((lon + 540.0) % 360.0) - 180.0


def _gst_degrees(jd_ut: float) -> float:
    """Greenwich Sidereal Time (derece)."""
    return (swe.sidtime(jd_ut) * 15.0) % 360.0


def _planet_ra_decl(jd_ut: float, planet_id: int) -> tuple[float, float] | None:
    """Gezegenin RA ve declination'ı (derece)."""
    try:
        values, _ = swe.calc_ut(
            jd_ut, planet_id,
            swe.FLG_SWIEPH | swe.FLG_EQUATORIAL,
        )
    except swe.Error:
        return None
    return float(values[0]), float(values[1])


def _mc_line_longitude(ra_deg: float, gst_deg: float) -> float:
    """MC hattının coğrafi boylamı."""
    return _normalize_lon(ra_deg - gst_deg)


def _horizon_curve(
    ra_deg: float,
    decl_deg: float,
    gst_deg: float,
    rising: bool,
) -> list[dict]:
    """ASC (rising=True) veya DSC (rising=False) eğrisi.

    Her enlem için gezegenin ufukta olduğu boylamı çözer.
    cos(H) = -tan(φ) tan(δ). Rising için hour angle -H, setting için +H.
    Boylam: λ = normalize(RA ∓ H - GST)  (λ doğu pozitif)
    """
    curve = []
    decl_rad = math.radians(decl_deg)
    lat = CURVE_LAT_MIN
    while lat <= CURVE_LAT_MAX + 1e-9:
        lat_rad = math.radians(lat)
        cos_h = -math.tan(lat_rad) * math.tan(decl_rad)
        if -1.0 <= cos_h <= 1.0:
            h_deg = math.degrees(math.acos(cos_h))
            hour_angle = -h_deg if rising else h_deg
            lon = _normalize_lon(ra_deg + hour_angle - gst_deg)
            curve.append({
                "lat": round(lat, 2),
                "lon": round(lon, 4),
            })
        lat += CURVE_LAT_STEP
    return curve


def _nearest_lines_for_point(
    point: dict,
    lines: list[dict],
) -> list[dict]:
    """Bir ilgi noktasına INTEREST_ORB_DEG içinde geçen hatlar."""
    matches = []
    for line in lines:
        if line["line_type"] in ("MC", "IC"):
            # Dikey hat: boylam farkı yeterli
            diff = abs(_normalize_lon(point["lon"] - line["longitude"]))
            if diff <= INTEREST_ORB_DEG:
                matches.append({
                    "planet": line["planet"],
                    "planet_tr": line["planet_tr"],
                    "line_type": line["line_type"],
                    "distance_deg": round(diff, 4),
                })
        else:
            # Eğri: noktanın enlemine en yakın eğri noktasının boylam farkı
            curve = line["curve"]
            if not curve:
                continue
            closest = min(curve, key=lambda c: abs(c["lat"] - point["lat"]))
            if abs(closest["lat"] - point["lat"]) > CURVE_LAT_STEP:
                continue
            diff = abs(_normalize_lon(point["lon"] - closest["lon"]))
            if diff <= INTEREST_ORB_DEG:
                matches.append({
                    "planet": line["planet"],
                    "planet_tr": line["planet_tr"],
                    "line_type": line["line_type"],
                    "distance_deg": round(diff, 4),
                })
    matches.sort(key=lambda m: m["distance_deg"])
    return matches


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_astrocartography(payload: dict) -> dict:
    """ACG hat hesabı."""

    interest_points = _validate_input(payload)

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
    gst = _gst_degrees(jd_ut)

    lines: list[dict] = []
    skipped: list[dict] = []
    for planet_id, body_id, name_tr in ACG_PLANETS:
        ra_decl = _planet_ra_decl(jd_ut, planet_id)
        if ra_decl is None:
            skipped.append({"planet": body_id, "reason": "ephemeris_error"})
            continue
        ra, decl = ra_decl

        mc_lon = _mc_line_longitude(ra, gst)
        ic_lon = _normalize_lon(mc_lon + 180.0)

        lines.append({
            "planet": body_id,
            "planet_tr": name_tr,
            "line_type": "MC",
            "longitude": round(mc_lon, 4),
            "declination": round(decl, 4),
        })
        lines.append({
            "planet": body_id,
            "planet_tr": name_tr,
            "line_type": "IC",
            "longitude": round(ic_lon, 4),
            "declination": round(decl, 4),
        })
        lines.append({
            "planet": body_id,
            "planet_tr": name_tr,
            "line_type": "ASC",
            "curve": _horizon_curve(ra, decl, gst, rising=True),
            "declination": round(decl, 4),
        })
        lines.append({
            "planet": body_id,
            "planet_tr": name_tr,
            "line_type": "DSC",
            "curve": _horizon_curve(ra, decl, gst, rising=False),
            "declination": round(decl, 4),
        })

    # İlgi noktaları analizi
    interest_analysis = []
    for point in interest_points:
        nearby = _nearest_lines_for_point(point, lines)
        interest_analysis.append({
            "name": point["name"],
            "lat": point["lat"],
            "lon": point["lon"],
            "nearby_lines": nearby,
        })

    limitations = [
        "ASC/DSC eğrileri -66..+66 enlem aralığında 2° adımla örneklenir.",
        f"İlgi noktası yakınlık eşiği {INTEREST_ORB_DEG}° boylam farkıdır (yaklaşık; enleme göre km karşılığı değişir).",
        "Parans hatları (crossing latitudes) ayrı Parans modülündedir.",
        "Kutup bölgelerinde (|lat| > 66°) circumpolar gezegenler için ASC/DSC hattı olmayabilir.",
        "Bu veri paketi yorum içermez.",
    ]
    conf = natal_chart["data_quality"].get("birth_time_confidence")
    if conf in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; 4 dakika saat hatası tüm hatları ~1° kaydırır."
        )

    return {
        "status": "available",
        "version": ACG_VERSION,
        "method": "astrocartography_ra_gst_v1",
        "birth_utc": natal_chart["birth"]["utc_datetime"],
        "gst_degrees": round(gst, 6),
        "planets_count": len(ACG_PLANETS) - len(skipped),
        "skipped": skipped,
        "lines": lines,
        "interest_points": interest_analysis,
        "curve_sampling": {
            "lat_min": CURVE_LAT_MIN,
            "lat_max": CURVE_LAT_MAX,
            "lat_step": CURVE_LAT_STEP,
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


def build_astrocartography_markdown(
    data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    lines = data["lines"]
    interest = data["interest_points"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Astrocartography"',
        'type: "astrocartography_pack"',
        'source: "western_api_v2_astrocartography"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'method: "{data["method"]}"',
        f'birth_utc: "{data["birth_utc"]}"',
        f'planets_count: {data["planets_count"]}',
        f'interest_points_count: {len(interest)}',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{ACG_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Astrocartography",
        "",
        "## Kullanım Notu",
        "",
        "- Her gezegen için 4 hat: MC (culminate), IC (anti-culminate), ASC (rise), DSC (set).",
        "- MC/IC dikey meridyenlerdir; ASC/DSC enleme bağlı eğrilerdir.",
        "- İlgi noktaları verilen konumlara 5° boylam yakınlığındaki hatları listeler.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
    ]

    mc_ic_rows = [
        (
            line["planet_tr"],
            line["line_type"],
            f'{line["longitude"]:+.2f}°',
        )
        for line in lines if line["line_type"] in ("MC", "IC")
    ]
    mc_section = [
        "## MC / IC Meridyenleri",
        "",
        _md_table(["Gezegen", "Hat", "Boylam"], mc_ic_rows),
        "",
    ]

    interest_sections = []
    if interest:
        interest_sections.append("## İlgi Noktaları Analizi")
        interest_sections.append("")
        for pt in interest:
            interest_sections.append(
                f"### {pt['name']} ({pt['lat']:.2f}, {pt['lon']:.2f})"
            )
            interest_sections.append("")
            if pt["nearby_lines"]:
                rows = [
                    (
                        m["planet_tr"],
                        m["line_type"],
                        f'{m["distance_deg"]:.2f}°',
                    )
                    for m in pt["nearby_lines"]
                ]
                interest_sections.append(
                    _md_table(["Gezegen", "Hat", "Boylam Farkı"], rows)
                )
            else:
                interest_sections.append("_5° içinde hat yok._")
            interest_sections.append("")

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in data.get("limitations", [])],
        "",
    ]

    # Eğri verileri çok uzun; teknik JSON'da curve'leri kısalt
    technical_data = {
        **{k: v for k, v in data.items() if k != "lines"},
        "lines": [
            {
                **{k: v for k, v in line.items() if k != "curve"},
                "curve_points": len(line.get("curve", [])) if "curve" in line else None,
            }
            for line in lines
        ],
    }
    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "ASC/DSC eğri koordinatları gömülmez (boyut); /astrocartography/preview endpoint'i tam veriyi döner.",
        "",
        "```json",
        json.dumps(technical_data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *mc_section,
        *interest_sections,
        *limit_section,
        *technical_section,
    ])
