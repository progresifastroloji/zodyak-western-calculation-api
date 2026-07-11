#!/usr/bin/env python3
"""Primary Directions calculation (Placidus semi-arc, mundane, direct).

Klasik öngörünün en eski tekniği. Promissor (hareket eden) ile
significator (sabit hedef) arasındaki birincil (günlük) rotasyona
dayalı yöneltim.

Bu modül v1 olarak şu kısıtlarla teslim edilir:

- Yöntem: Placidus semi-arc (semi-arc proportional)
- Direction: yalnızca DIRECT (canlı dönüş); converse v2'ye bırakılır
- Aspect alanı: mundane (kürede); zodiacal v2'ye bırakılır
- Aspect set: Ptolemaik 5 (conjunction, sextile, square, trine, opposition)
- Key seçenekleri: Ptolemaic (1°/yıl) default, Naibod (0.9856°/yıl) opsiyonel
- Significator alfabesi: klasik 7 ışık + asc + mc
  (Sun, Moon, Mercury, Venus, Mars, ASC, MC)
- Promissor alfabesi: 10 gezegen + 2 düğüm + 4 açı (toplam 16)

Hesap doğruluğu: Placidus mundane PD'nin klasik formülasyonu (Hand,
Bonatti, Ptolemy çizgisi). Promissor'un yarı-yayı yönelim boyunca
sabit kabul edilir — yatay-üstü/altı sınırı geçen uzun yönelimlerde
hata payı vardır. Üretim öncesinde Solar Fire / Janus / Morinus
referansıyla karşılaştırma önerilir.

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
import math
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import swisseph as swe

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    SIGNS,
    _degree_fields,
    _julian_day,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


PD_VERSION = "1.0.0"
TROPICAL_YEAR_DAYS = 365.2422
DEFAULT_REFERENCE_TIMEZONE = os.environ.get(
    "WESTERN_ASTROLOGY_DEFAULT_TIMEZONE", "Europe/Istanbul",
)
DEFAULT_WINDOW_YEARS = 5.0
MAX_WINDOW_YEARS = 100.0

PD_ASPECTS_OFFSETS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

ASPECT_TR = {
    "conjunction": "Kavuşum",
    "sextile": "Sekstil",
    "square": "Kare",
    "trine": "Üçgen",
    "opposition": "Karşıt",
}

# Key (yıl başına ark dönüşümü)
KEYS = {
    "ptolemaic": 1.0,
    "naibod": 0.9856,
}

# Significator (sabit hedef) alfabesi: klasik 7 ışık + iki açı
SIGNIFICATOR_IDS = {
    "sun", "moon", "mercury", "venus", "mars",
    "ascendant", "midheaven",
}

# Promissor (hareket eden) alfabesi: 10 gezegen + 2 düğüm + 4 açı
PROMISSOR_PLANET_IDS = {
    "sun", "moon", "mercury", "venus", "mars",
    "jupiter", "saturn", "uranus", "neptune", "pluto",
}
PROMISSOR_NODE_IDS = {"mean_node", "south_node", "true_node"}
PROMISSOR_ANGLE_IDS = {"ascendant", "descendant", "midheaven", "imum_coeli"}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class PrimaryDirectionsInputError(ValueError):
    """Primary directions için geçersiz input."""


class PrimaryDirectionsCalculationError(RuntimeError):
    """Primary directions hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _parse_target_date(value: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise PrimaryDirectionsInputError(
            f"Geçersiz tarih (YYYY-MM-DD bekleniyor): {value}"
        ) from exc


def _validate_input(payload: dict) -> tuple[date, str, float, str]:
    if not isinstance(payload, dict):
        raise PrimaryDirectionsInputError("JSON gövdesi nesne olmalıdır")
    pd = payload.get("primary_directions") or {}
    if not isinstance(pd, dict):
        raise PrimaryDirectionsInputError(
            "primary_directions alanı nesne olmalıdır"
        )

    target_value = pd.get("target_date")
    if target_value:
        target_date = _parse_target_date(target_value)
    else:
        target_date = date.today()

    key = str(pd.get("key") or "ptolemaic").lower()
    if key not in KEYS:
        raise PrimaryDirectionsInputError(
            f"Geçersiz key: {key}. Geçerli: {sorted(KEYS.keys())}"
        )

    try:
        window_years = float(pd.get("window_years") or DEFAULT_WINDOW_YEARS)
    except (TypeError, ValueError) as exc:
        raise PrimaryDirectionsInputError(
            "window_years sayısal olmalıdır"
        ) from exc
    if window_years <= 0 or window_years > MAX_WINDOW_YEARS:
        raise PrimaryDirectionsInputError(
            f"window_years 0 < x ≤ {MAX_WINDOW_YEARS} aralığında olmalıdır"
        )

    reference_tz = str(pd.get("reference_timezone") or DEFAULT_REFERENCE_TIMEZONE)
    try:
        ZoneInfo(reference_tz)
    except ZoneInfoNotFoundError as exc:
        raise PrimaryDirectionsInputError(
            f"Geçersiz primary_directions.reference_timezone: {reference_tz}"
        ) from exc

    return target_date, key, window_years, reference_tz


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


# ---------------------------------------------------------------------------
# Trigonometrik temel
# ---------------------------------------------------------------------------


def _ecl_to_eq_lat0(ecl_lon_deg: float, obliquity_deg: float) -> tuple[float, float]:
    """Ekliptik enlemi 0 kabul ederek (RA, decl) hesaplar.

    Gezegenler için ekliptik enlemleri küçüktür (< ~7°); açı kavşakları
    ve düğümler tam olarak 0'dır. v1 için bu basitleştirme tutulur.
    """
    lon = math.radians(ecl_lon_deg)
    eps = math.radians(obliquity_deg)
    sin_lon, cos_lon = math.sin(lon), math.cos(lon)
    sin_eps, cos_eps = math.sin(eps), math.cos(eps)

    ra_rad = math.atan2(sin_lon * cos_eps, cos_lon)
    ra = math.degrees(ra_rad) % 360.0

    sin_decl = sin_eps * sin_lon
    decl = math.degrees(math.asin(max(-1.0, min(1.0, sin_decl))))
    return ra, decl


def _ascensional_difference(decl_deg: float, lat_deg: float) -> float:
    """AD = asin(tan(δ) × tan(φ)). Sirkumpolar durumlar ±90° kırpılır."""
    decl = math.radians(decl_deg)
    lat = math.radians(lat_deg)
    arg = math.tan(decl) * math.tan(lat)
    if arg > 1.0:
        return 90.0
    if arg < -1.0:
        return -90.0
    return math.degrees(math.asin(arg))


def _mundane_position(
    ra: float, decl: float, ramc: float, lat: float,
) -> tuple[float, float, float, bool]:
    """Cismin Placidus mundane F konumunu, DSA/NSA değerlerini döner.

    F konvansiyonu (primary motion yönünde artar):
        F =   0  → MC (üst meridyen)
        F =  90  → DSC (batı ufku)
        F = 180  → IC (alt meridyen)
        F = 270  → ASC (doğu ufku)

    Aynı zamanda DSA, NSA ve `above_horizon` bilgisi de döner.
    """
    AD = _ascensional_difference(decl, lat)
    DSA = 90.0 + AD  # diurnal semi-arc; ufkun üstünde geçen ark
    NSA = 90.0 - AD  # nocturnal semi-arc

    # MD = RA - RAMC, [0, 360) aralığında
    MD = (ra - ramc) % 360.0

    if MD <= DSA:
        # Üst yarımküre, MC ile DSC arası
        F = (MD / DSA) * 90.0
        above = True
    elif MD <= 180.0:
        # Alt yarımküre, DSC ile IC arası
        F = 90.0 + ((MD - DSA) / NSA) * 90.0
        above = False
    elif MD <= 360.0 - DSA:
        # Alt yarımküre, IC ile ASC arası
        F = 180.0 + ((MD - 180.0) / NSA) * 90.0
        above = False
    else:
        # Üst yarımküre, ASC ile MC arası
        F = 270.0 + ((MD - (360.0 - DSA)) / DSA) * 90.0
        above = True

    return F % 360.0, DSA, NSA, above


def _F_to_RA_arc(
    arc_in_F: float,
    F_promissor: float,
    DSA_P: float,
    NSA_P: float,
) -> float:
    """Mundane F-cinsinden arkı promissor'un yarı-yayına oranlayarak RA'ya çevir.

    Promissor'un mevcut konumunda hangi semi-arc'ta olduğunu kullanır
    (yarı yay sabit kabul edilir). Bu Placidus'un standart
    "semi-arc proportional" yaklaşımının basit halidir; yatay
    eşiğini geçen uzun yönelimlerde piecewise daha doğrudur ancak
    v1 için bu basitleştirme tutulur.
    """
    # F ∈ [0,90] veya [270,360] → üst yarımküre → DSA
    # F ∈ [90,180] veya [180,270] → alt yarımküre → NSA
    if F_promissor < 90.0 or F_promissor >= 270.0:
        sa = DSA_P
    else:
        sa = NSA_P
    return arc_in_F * sa / 90.0


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_primary_directions(
    payload: dict,
    chart: dict | None = None,
) -> dict:
    """Primary directions için aktif yönelim listesi üretir."""

    target_date, key, window_years, reference_tz = _validate_input(payload)
    natal_chart = chart or calculate_core_chart(payload)

    birth = natal_chart["birth"]
    birth_utc = datetime.fromisoformat(
        birth["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)
    lat = float(birth["latitude"])

    age_years = _compute_age_years(birth_utc, target_date, reference_tz)
    if age_years < 0:
        raise PrimaryDirectionsInputError(
            "Hedef tarih doğum tarihinden önce olamaz"
        )

    # Obliquity (gerçek + nutation)
    jd_birth = _julian_day(birth_utc)
    try:
        ecl_nut, _ = swe.calc_ut(jd_birth, swe.ECL_NUT)
        obliquity = float(ecl_nut[0])  # true obliquity
    except swe.Error as exc:
        raise PrimaryDirectionsCalculationError(
            "Obliquity hesaplanamadı"
        ) from exc

    # RAMC: MC'nin doğru asansiyonu
    mc_lon = natal_chart["angles"]["midheaven"]["longitude"]
    ramc, _ = _ecl_to_eq_lat0(mc_lon, obliquity)

    # Natal noktaların mundane konumları
    natal_points: dict[str, dict] = {}

    def _register(point_id, lon, name_tr=None, sign_tr=None, house=None, kind="planet"):
        ra, decl = _ecl_to_eq_lat0(lon, obliquity)
        F, DSA, NSA, above = _mundane_position(ra, decl, ramc, lat)
        natal_points[point_id] = {
            "id": point_id,
            "kind": kind,
            "longitude": lon,
            "ra": ra,
            "decl": decl,
            "F": F,
            "DSA": DSA,
            "NSA": NSA,
            "above_horizon": above,
            "name_tr": name_tr or point_id,
            "sign_tr": sign_tr,
            "house": house,
        }

    for planet in natal_chart["planets"]["items"]:
        _register(
            planet["id"], planet["longitude"],
            name_tr=planet.get("name_tr"),
            sign_tr=planet.get("sign_tr"),
            house=planet.get("house"),
            kind="planet",
        )
    for node in natal_chart["nodes"]["items"]:
        _register(
            node["id"], node["longitude"],
            name_tr=node.get("name_tr"),
            sign_tr=node.get("sign_tr"),
            house=node.get("house"),
            kind="node",
        )
    for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
        a = natal_chart["angles"][angle_id]
        _register(
            angle_id, a["longitude"],
            name_tr=angle_id,
            sign_tr=a.get("sign_tr"),
            house=None,
            kind="angle",
        )

    # Yönelim hesabı
    key_rate = KEYS[key]
    window_lo = age_years - window_years
    window_hi = age_years + window_years

    active_directions = []
    total_computed = 0
    excluded_circumpolar = 0

    for sig_id in SIGNIFICATOR_IDS:
        if sig_id not in natal_points:
            continue
        S = natal_points[sig_id]
        # Sirkumpolar significator atla (DSA = 180 veya 0 anlamlı yönelim üretmez)
        if S["DSA"] >= 179.999 or S["DSA"] <= 0.001:
            excluded_circumpolar += 1
            continue
        for prom_id in (PROMISSOR_PLANET_IDS | PROMISSOR_NODE_IDS | PROMISSOR_ANGLE_IDS):
            if prom_id not in natal_points or prom_id == sig_id:
                continue
            P = natal_points[prom_id]
            if P["DSA"] >= 179.999 or P["DSA"] <= 0.001:
                excluded_circumpolar += 1
                continue

            for aspect_name, offset in PD_ASPECTS_OFFSETS.items():
                target_F = (S["F"] + offset) % 360.0
                arc_F = (target_F - P["F"]) % 360.0
                total_computed += 1

                # Direct: arc ∈ (0, 180]; converse v2'de
                if arc_F == 0.0 or arc_F > 180.0:
                    continue

                arc_RA = _F_to_RA_arc(arc_F, P["F"], P["DSA"], P["NSA"])
                if arc_RA <= 0.0:
                    continue
                event_age = arc_RA / key_rate
                if event_age < 0:
                    continue

                event_dt_utc = birth_utc + timedelta(
                    days=event_age * TROPICAL_YEAR_DAYS
                )

                direction = {
                    "promissor": prom_id,
                    "promissor_tr": P["name_tr"],
                    "significator": sig_id,
                    "significator_tr": S["name_tr"],
                    "aspect": aspect_name,
                    "aspect_tr": ASPECT_TR.get(aspect_name, aspect_name),
                    "arc_in_F_degrees": round(arc_F, 4),
                    "arc_of_direction_degrees": round(arc_RA, 4),
                    "event_age": round(event_age, 4),
                    "estimated_date_utc": event_dt_utc.date().isoformat(),
                    "direction": "direct",
                    "promissor_sign_tr": P.get("sign_tr"),
                    "significator_sign_tr": S.get("sign_tr"),
                    "promissor_natal_house": P.get("house"),
                    "significator_natal_house": S.get("house"),
                }
                if window_lo <= event_age <= window_hi:
                    active_directions.append(direction)

    active_directions.sort(key=lambda d: d["event_age"])

    limitations = [
        "Yalnızca DIRECT yönelimler hesaplanır; CONVERSE v1'de yoktur.",
        "Yalnızca MUNDANE yönelimler; ZODIACAL v1'de yoktur.",
        "Placidus semi-arc method (semi-arc proportional). "
        "Regiomontanus yöntemi opsiyonu v1'de yoktur.",
        "Promissor'un yarı-yayı yönelim boyunca sabit kabul edilir; "
        "yatay eşiğini geçen uzun yönelimlerde hata payı vardır.",
        "Üretim öncesi Solar Fire / Janus / Morinus referansıyla "
        "karşılaştırma önerilir.",
    ]
    time_confidence = natal_chart["data_quality"].get("birth_time_confidence")
    if time_confidence in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; primary directions doğum saatine "
            "ekstrem duyarlıdır (1 dakika ≈ 1 ay direkt yönelimde)."
        )
    if excluded_circumpolar:
        limitations.append(
            f"Sirkumpolar significator/promissor sayısı (atlandı): {excluded_circumpolar}"
        )

    return {
        "status": "available",
        "version": PD_VERSION,
        "method": "primary_directions_placidus_semi_arc_mundane_direct",
        "key": key,
        "key_rate_degrees_per_year": key_rate,
        "target_date": target_date.isoformat(),
        "reference_timezone": reference_tz,
        "age_years": round(age_years, 6),
        "window_years": window_years,
        "obliquity_degrees": round(obliquity, 6),
        "ramc_degrees": round(ramc, 6),
        "natal_summary": {
            "birth_date": birth["date"],
            "birth_time": birth["time"],
            "house_system": natal_chart["meta"]["house_system"],
            "ascendant_sign_tr": natal_chart["angles"]["ascendant"]["sign_tr"],
            "midheaven_sign_tr": natal_chart["angles"]["midheaven"]["sign_tr"],
            "latitude": lat,
            "longitude": float(birth["longitude"]),
        },
        "active_directions_count": len(active_directions),
        "active_directions": active_directions,
        "total_computed": total_computed,
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


def build_primary_directions_markdown(
    pd_data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    """Primary directions için Markdown çıktısı."""

    target_date = pd_data["target_date"]
    natal_summary = pd_data["natal_summary"]
    age_years = pd_data["age_years"]
    window_years = pd_data["window_years"]
    actives = pd_data["active_directions"]
    key = pd_data["key"]
    key_rate = pd_data["key_rate_degrees_per_year"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Primary Directions {target_date}"',
        'type: "primary_directions_pack"',
        'source: "western_api_v2_primary_directions"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'target_date: "{target_date}"',
        f'age_years: {age_years}',
        f'window_years: {window_years}',
        f'key: "{key}"',
        f'method: "{pd_data["method"]}"',
        f'house_system: "{natal_summary["house_system"]}"',
        f'reference_timezone: "{pd_data["reference_timezone"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{PD_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Primary Directions {target_date}",
        "",
        "## Kullanım Notu",
        "",
        "- Primary directions klasik öngörünün en eski tekniğidir; günlük rotasyona dayalı yöneltim.",
        "- Bu versiyon: Placidus semi-arc, mundane, DIRECT yönelimler.",
        "- Aktif yönelimler hedef yaşın ±{:.1f} yıl penceresinde gerçekleşenlerdir.".format(window_years),
        "- 1° = 1 yıl (Ptolemaic) veya 0.9856°/yıl (Naibod) key kullanılır.",
        "- Doğum saatine ekstrem duyarlıdır; saat güveni düşükse sonuçlar bağlayıcı değildir.",
        "- Diğer öngörü teknikleriyle (transit, SR, progressions, SA) birlikte okunur.",
        "",
        "## Dönem Özeti",
        "",
        f"- Hedef tarih: {target_date}",
        f"- Doğumdan beri geçen yıl: {age_years:.4f}",
        f"- Pencere: ±{window_years:.1f} yıl",
        f"- Aktif yönelim sayısı: {len(actives)}",
        f"- Key: **{key}** ({key_rate}°/yıl)",
        f"- Yöntem: Placidus semi-arc, mundane, direct",
        "",
        "## Natal Özet",
        "",
        f"- Doğum: {natal_summary['birth_date']} {natal_summary['birth_time']}",
        f"- Ev sistemi: {natal_summary['house_system']}",
        f"- Enlem: {natal_summary['latitude']:.4f}, Boylam: {natal_summary['longitude']:.4f}",
        f"- Yükselen: {natal_summary['ascendant_sign_tr']}",
        f"- MC: {natal_summary['midheaven_sign_tr']}",
        f"- Obliquity: {pd_data['obliquity_degrees']:.4f}°",
        f"- RAMC: {pd_data['ramc_degrees']:.4f}°",
        "",
    ]

    if actives:
        rows = [
            (
                f'{a["estimated_date_utc"]}',
                f'{a["event_age"]:.2f}',
                a["promissor_tr"],
                a["aspect_tr"],
                a["significator_tr"],
                f'{a["arc_of_direction_degrees"]:.3f}°',
                a.get("promissor_sign_tr") or "-",
                a.get("significator_sign_tr") or "-",
            )
            for a in actives
        ]
        active_table = _md_table(
            [
                "Tahmini Tarih (UTC)",
                "Yaş",
                "Promissor",
                "Açı",
                "Significator",
                "Ark",
                "Promissor Burcu",
                "Significator Burcu",
            ],
            rows,
        )
    else:
        active_table = (
            "_Bu pencerede aktif primary direction bulunmuyor. "
            "window_years değerini artırarak daha geniş aralık deneyebilirsiniz._"
        )

    active_section = [
        "## Aktif Yönelimler",
        "",
        active_table,
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in pd_data.get("limitations", [])],
        "",
    ]

    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "```json",
        json.dumps(pd_data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *active_section,
        *limit_section,
        *technical_section,
    ])
