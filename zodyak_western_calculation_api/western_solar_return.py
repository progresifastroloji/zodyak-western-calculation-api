#!/usr/bin/env python3
"""Solar Return calculation for Western Astrology.

Verilen bir yıl için transit Güneş'in natal Güneş longitude'una tam geldiği
anı bulur, o an için tam harita üretir ve natal ile karşılaştırma analizleri
sağlar.

Default konum: doğum yeri (klasik). Opsiyonel `return_location` ile relocated SR.
"""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe

from .western_chart import (
    _house_number,
    _julian_day,
    _shortest_separation,
    _signed_delta,
    calculate_core_chart,
)


SR_VERSION = "1.0.0"

PLANET_TR = {
    "sun": "Güneş", "moon": "Ay", "mercury": "Merkür", "venus": "Venüs",
    "mars": "Mars", "jupiter": "Jüpiter", "saturn": "Satürn",
    "uranus": "Uranüs", "neptune": "Neptün", "pluto": "Plüton",
    "chiron": "Şiron",
    "north_node": "KAD", "south_node": "GAD",
    "ascendant": "Yükselen", "descendant": "Düşen",
    "midheaven": "MC", "imum_coeli": "IC",
}

ASPECT_TR = {
    "conjunction": "Kavuşum",
    "sextile": "Sekstil",
    "square": "Kare",
    "trine": "Üçgen",
    "opposition": "Karşıt",
}

MAJOR_ASPECTS = {
    "conjunction": 0.0,
    "sextile": 60.0,
    "square": 90.0,
    "trine": 120.0,
    "opposition": 180.0,
}

SR_NATAL_ORB = 3.0           # SR ↔ natal major aspect eşiği
ANGLE_THEME_ORB = 5.0        # SR ASC/MC'ye "yıl temalandırıcı" eşiği


class SolarReturnError(ValueError):
    """Solar Return input/calculation errors."""


# ---------------------------------------------------------------------------
# Exact SR datetime
# ---------------------------------------------------------------------------


def _sun_longitude_at(jd_ut: float) -> float:
    """Verilen JD'de tropikal Güneş longitude'unu döner."""
    values, _ = swe.calc_ut(jd_ut, swe.SUN, swe.FLG_SWIEPH | swe.FLG_SPEED)
    return float(values[0]) % 360.0


def _find_solar_return_exact_utc(
    natal_sun_longitude: float,
    target_year: int,
    natal_month: int,
    natal_day: int,
) -> datetime:
    """Verilen yılda transit Güneş'in natal Sun longitude'una eşit olduğu UTC anını bul.

    Arama penceresi: doğum tarihinin o yıldaki versiyonu ± 15 gün.
    Algoritma: bisection, 1 saniye hassasiyetine kadar.
    """
    try:
        center = datetime(
            target_year, natal_month, natal_day, 12, 0, 0, tzinfo=timezone.utc,
        )
    except ValueError:
        # 29 Şubat → 28 Şubat
        center = datetime(target_year, natal_month, 28, 12, 0, 0, tzinfo=timezone.utc)

    start = center - timedelta(days=15)
    end = center + timedelta(days=15)

    def diff_at(dt: datetime) -> float:
        return _signed_delta(_sun_longitude_at(_julian_day(dt)), natal_sun_longitude)

    diff_start = diff_at(start)
    diff_end = diff_at(end)

    # Pencere içinde işaret değişimi yoksa genişlet (nadiren)
    if diff_start * diff_end > 0:
        start = center - timedelta(days=30)
        end = center + timedelta(days=30)
        diff_start = diff_at(start)
        diff_end = diff_at(end)
        if diff_start * diff_end > 0:
            raise SolarReturnError(
                f"Solar Return exact anı {target_year} yılı içinde bulunamadı."
            )

    # Bisection
    for _ in range(100):
        if (end - start).total_seconds() <= 1.0:
            break
        mid = start + (end - start) / 2
        diff_mid = diff_at(mid)
        if (diff_start <= 0 <= diff_mid) or (diff_start >= 0 >= diff_mid):
            end = mid
            diff_end = diff_mid
        else:
            start = mid
            diff_start = diff_mid

    return start + (end - start) / 2


# ---------------------------------------------------------------------------
# SR payload build (chart re-use)
# ---------------------------------------------------------------------------


def _build_sr_payload(
    natal_payload: dict,
    sr_utc: datetime,
    return_location: dict | None,
) -> dict:
    """Natal payload'tan SR için yeni payload türet (UTC → local çeviri ile).

    Default konum: doğum yeri. `return_location` verilirse relocated SR.
    """
    birth = dict(natal_payload.get("birth") or {})

    if return_location:
        if "timezone_id" not in return_location:
            raise SolarReturnError(
                "return_location.timezone_id zorunludur (relocated SR için)."
            )
        location_lat = float(return_location.get("lat", birth.get("lat")))
        location_lon = float(return_location.get("lon", birth.get("lon")))
        tz_id = str(return_location["timezone_id"])
        place = return_location.get("place") or birth.get("place")
    else:
        location_lat = float(birth["lat"])
        location_lon = float(birth["lon"])
        tz_id = birth.get("timezone_id")
        place = birth.get("place")

    if not tz_id:
        raise SolarReturnError(
            "Lokasyon için timezone_id eksik (natal veya return_location)."
        )

    sr_local = sr_utc.astimezone(ZoneInfo(tz_id))

    sr_birth = {
        "year": sr_local.year,
        "month": sr_local.month,
        "day": sr_local.day,
        "hour": sr_local.hour,
        "minute": sr_local.minute,
        "second": sr_local.second,
        "lat": location_lat,
        "lon": location_lon,
        "timezone_id": tz_id,
        "place": place,
        "time_confidence": "high",  # exact hesap
    }

    return {
        "birth": sr_birth,
        "person": dict(natal_payload.get("person") or {}),
        "options": dict(natal_payload.get("options") or {}),
    }


# ---------------------------------------------------------------------------
# SR ↔ Natal karşılaştırmaları
# ---------------------------------------------------------------------------


def _collect_bodies(chart: dict) -> list[dict]:
    """Chart'tan tüm noktaları (planet + node + angle) birleşik liste döner."""
    bodies = []
    for planet in chart["planets"]["items"]:
        bodies.append({
            "id": planet["id"],
            "kind": "planet",
            "longitude": planet["longitude"],
            "sign_tr": planet["sign_tr"],
            "house": planet["house"],
        })
    for node in chart["nodes"]["items"]:
        bodies.append({
            "id": node["id"],
            "kind": "node",
            "longitude": node["longitude"],
            "sign_tr": node["sign_tr"],
            "house": node["house"],
        })
    for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
        a = chart["angles"][angle_id]
        bodies.append({
            "id": angle_id,
            "kind": "angle",
            "longitude": a["longitude"],
            "sign_tr": a["sign_tr"],
            "house": None,
        })
    return bodies


def _compute_sr_natal_aspects(
    sr_chart: dict, natal_chart: dict, orb: float = SR_NATAL_ORB,
) -> list[dict]:
    """SR ↔ natal major aspect tablosu (orb ≤ threshold)."""
    sr_bodies = _collect_bodies(sr_chart)
    natal_bodies = _collect_bodies(natal_chart)

    aspects = []
    for sb in sr_bodies:
        for nb in natal_bodies:
            sep = _shortest_separation(sb["longitude"], nb["longitude"])
            best = None
            for aspect_type, exact in MAJOR_ASPECTS.items():
                o = abs(sep - exact)
                if o <= orb and (best is None or o < best[1]):
                    best = (aspect_type, o)
            if best:
                aspects.append({
                    "sr": sb["id"],
                    "sr_kind": sb["kind"],
                    "natal": nb["id"],
                    "natal_kind": nb["kind"],
                    "type": best[0],
                    "orb": round(best[1], 4),
                    "sr_sign_tr": sb["sign_tr"],
                    "natal_sign_tr": nb["sign_tr"],
                    "natal_house": nb["house"],
                })
    aspects.sort(key=lambda a: a["orb"])
    return aspects


def _sr_in_natal_houses(sr_chart: dict, natal_chart: dict) -> list[dict]:
    """SR gezegenlerinin natal ev cusps'una göre yerleşimi."""
    natal_cusps = [h["longitude"] for h in natal_chart["houses"]["items"]]
    items = []
    for planet in sr_chart["planets"]["items"]:
        natal_house = _house_number(planet["longitude"], natal_cusps)
        items.append({
            "id": planet["id"],
            "sr_sign_tr": planet["sign_tr"],
            "sr_house": planet["house"],
            "natal_house": natal_house,
        })
    return items


def _yearly_themes(sr_chart: dict, orb: float = ANGLE_THEME_ORB) -> dict:
    """SR ASC/MC'ye orb içinde olan SR gezegenleri (yıl temalandırıcı)."""
    asc_long = sr_chart["angles"]["ascendant"]["longitude"]
    mc_long = sr_chart["angles"]["midheaven"]["longitude"]

    themes = {"ascendant": [], "midheaven": []}
    for planet in sr_chart["planets"]["items"]:
        sep_asc = _shortest_separation(planet["longitude"], asc_long)
        if sep_asc <= orb:
            themes["ascendant"].append({
                "planet": planet["id"],
                "orb": round(sep_asc, 4),
                "sign_tr": planet["sign_tr"],
            })
        sep_mc = _shortest_separation(planet["longitude"], mc_long)
        if sep_mc <= orb:
            themes["midheaven"].append({
                "planet": planet["id"],
                "orb": round(sep_mc, 4),
                "sign_tr": planet["sign_tr"],
            })

    themes["ascendant"].sort(key=lambda t: t["orb"])
    themes["midheaven"].sort(key=lambda t: t["orb"])
    return themes


def _sr_angle_in_natal_house(sr_chart: dict, natal_chart: dict, angle_id: str) -> int:
    """SR Yükselen veya MC'nin natal hangi evine düştüğü."""
    natal_cusps = [h["longitude"] for h in natal_chart["houses"]["items"]]
    return _house_number(sr_chart["angles"][angle_id]["longitude"], natal_cusps)


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------


def calculate_solar_return(
    payload: dict,
    natal_chart: dict | None = None,
) -> dict:
    """Solar Return ana hesabı.

    Payload:
        - birth: natal birth bilgisi (year, month, day, hour, minute, lat, lon, timezone_id, ...)
        - person: kişi
        - options: house_system, node_type
        - return_year: int (zorunlu)
        - return_location: {lat, lon, timezone_id, place}? (opsiyonel — relocated SR)
    """
    if "return_year" not in payload:
        raise SolarReturnError("return_year alanı zorunludur")
    try:
        return_year = int(payload["return_year"])
    except (TypeError, ValueError) as exc:
        raise SolarReturnError("return_year tam sayı olmalıdır") from exc

    return_location = payload.get("return_location")

    natal = natal_chart or calculate_core_chart(payload)

    natal_sun = next(p for p in natal["planets"]["items"] if p["id"] == "sun")
    natal_sun_long = natal_sun["longitude"]

    natal_birth_date = natal["birth"]["date"]
    natal_year, natal_month, natal_day = map(int, natal_birth_date.split("-"))

    age = return_year - natal_year

    sr_utc = _find_solar_return_exact_utc(
        natal_sun_long, return_year, natal_month, natal_day,
    )

    sr_payload = _build_sr_payload(payload, sr_utc, return_location)
    sr_chart = calculate_core_chart(sr_payload)

    sr_natal_aspects = _compute_sr_natal_aspects(sr_chart, natal)
    sr_in_natal_houses = _sr_in_natal_houses(sr_chart, natal)
    yearly_themes = _yearly_themes(sr_chart)
    sr_asc_in_natal = _sr_angle_in_natal_house(sr_chart, natal, "ascendant")
    sr_mc_in_natal = _sr_angle_in_natal_house(sr_chart, natal, "midheaven")

    natal_house_occupants = {h: [] for h in range(1, 13)}
    for item in sr_in_natal_houses:
        natal_house_occupants[item["natal_house"]].append(item["id"])

    return {
        "status": "available",
        "version": SR_VERSION,
        "return_year": return_year,
        "age_at_return": age,
        "sr_exact_utc": sr_utc.isoformat().replace("+00:00", "Z"),
        "sr_exact_local": sr_chart["birth"]["local_datetime"],
        "sr_location": {
            "lat": sr_chart["birth"]["latitude"],
            "lon": sr_chart["birth"]["longitude"],
            "timezone_id": sr_chart["birth"]["timezone_id"],
            "place": sr_chart["birth"]["place"],
            "is_relocated": bool(return_location),
        },
        "natal_summary": {
            "person_name": (natal["birth"].get("person") or {}).get("name"),
            "birth_date": natal["birth"]["date"],
            "ascendant_sign_tr": natal["angles"]["ascendant"]["sign_tr"],
            "midheaven_sign_tr": natal["angles"]["midheaven"]["sign_tr"],
            "sun_sign_tr": natal_sun["sign_tr"],
            "house_system": natal["meta"]["house_system"],
        },
        "sr_chart": sr_chart,
        "sr_in_natal_houses": sr_in_natal_houses,
        "natal_house_occupants_sr": natal_house_occupants,
        "sr_asc_in_natal_house": sr_asc_in_natal,
        "sr_mc_in_natal_house": sr_mc_in_natal,
        "yearly_themes": yearly_themes,
        "sr_natal_aspects": sr_natal_aspects,
        "limitations": [
            "Solar Return yıllık çerçevedir; transit ve profection ile birlikte okunmalıdır.",
            (
                "Konum: relocated (return_location verildi)"
                if return_location
                else "Konum: natal birthplace (klasik)"
            ),
        ],
    }


# ---------------------------------------------------------------------------
# Markdown render
# ---------------------------------------------------------------------------


def _md_table(headers: list[str], rows: list[tuple]) -> str:
    if not rows:
        return ""
    lines = ["| " + " | ".join(headers) + " |"]
    lines.append("| " + " | ".join(["---"] * len(headers)) + " |")
    for row in rows:
        cells = []
        for cell in row:
            if cell is None:
                cells.append("-")
            else:
                cells.append(str(cell).replace("|", "\\|").replace("\n", " "))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines)


def _planet_tr(planet_id: str) -> str:
    return PLANET_TR.get(planet_id, planet_id)


def _aspect_tr(aspect_type: str) -> str:
    return ASPECT_TR.get(aspect_type, aspect_type)


def _to_embedded_markdown(full: str, sr_data: dict) -> str:
    """Tam SR markdown'ından transit dosyasına gömülü versiyon üret.

    - Frontmatter (--- ... ---) atlanır
    - teknik kullanım notu bölümü atlanır
    - '# Person - Solar Return YYYY' → '## Solar Return YYYY (yaş N)'
    - Diğer '## ...' → '### ...', '### ...' → '#### ...' (bir seviye düşer)
    """
    lines = full.split("\n")

    # Frontmatter kırp
    if lines and lines[0] == "---":
        try:
            end_idx = lines.index("---", 1)
            lines = lines[end_idx + 1:]
        except ValueError:
            pass
        while lines and not lines[0].strip():
            lines.pop(0)

    # Teknik kullanım notu bölümünü kırp
    new_lines = []
    skip_section = False
    for line in lines:
        if line.startswith("## ") and "Kullanım Notu" in line:
            skip_section = True
            continue
        if skip_section:
            if line.startswith("## ") or line.startswith("# "):
                skip_section = False
            else:
                continue

        # Heading seviyelerini bir aşağı it
        if line.startswith("# ") and not line.startswith("## "):
            new_lines.append(
                f"## Solar Return {sr_data['return_year']} "
                f"(yaş {sr_data['age_at_return']})"
            )
        elif line.startswith("## "):
            new_lines.append("### " + line[3:])
        elif line.startswith("### "):
            new_lines.append("#### " + line[4:])
        else:
            new_lines.append(line)

    return "\n".join(new_lines).rstrip() + "\n"


def build_solar_return_markdown(
    sr_data: dict,
    group_name: str = "Grup-01",
    generated_at: str | None = None,
    embedded: bool = False,
) -> str:
    """SR sonucundan markdown raporu üret.

    `embedded=True` ise transit dosyasına gömülmek üzere frontmatter atlanır,
    teknik kullanım notu çıkar ve başlık seviyeleri bir basamak düşer.
    """
    sr_chart = sr_data["sr_chart"]
    natal_summary = sr_data["natal_summary"]
    person_name = natal_summary.get("person_name") or "unknown"
    return_year = sr_data["return_year"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Solar Return {return_year}"',
        'type: "solar_return_pack"',
        'source: "western_api_v2_solar_return"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'return_year: {return_year}',
        f'age_at_return: {sr_data["age_at_return"]}',
        f'sr_exact_utc: "{sr_data["sr_exact_utc"]}"',
        f'sr_exact_local: "{sr_data["sr_exact_local"]}"',
        f'sr_location_place: "{sr_data["sr_location"]["place"] or "-"}"',
        f'sr_location_tz: "{sr_data["sr_location"]["timezone_id"]}"',
        f'is_relocated: {str(sr_data["sr_location"]["is_relocated"]).lower()}',
        f'house_system: "{sr_chart["meta"]["house_system"]}"',
        f'node_type: "{sr_chart["meta"]["node_type"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{SR_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    intro = [
        f"# {person_name} - Solar Return {return_year}",
        "",
        "## Teknik Kullanım Notu",
        "",
        "- Bu dosya Solar Return (Yıl Dönüm) haritasının teknik veri paketidir.",
        "- Solar Return yıllık çerçevedir; doğum gününden bir sonraki doğum gününe kadar olan yılın temasını gösterir.",
        "- Transit ve profection ile birlikte okunmalı; tek başına kullanılmamalıdır.",
        "- Bu çıktı ham teknik veri paketidir; yorum metni değildir.",
        "",
    ]

    asc = sr_chart["angles"]["ascendant"]
    mc = sr_chart["angles"]["midheaven"]
    overview = [
        "## Solar Return Temel Bilgiler",
        "",
        f"- Kişi: {person_name}",
        f"- Doğum tarihi: {natal_summary['birth_date']}",
        f"- Yıl: {return_year} (yaş {sr_data['age_at_return']})",
        f"- SR exact (UTC): {sr_data['sr_exact_utc']}",
        f"- SR exact (yerel): {sr_data['sr_exact_local']}",
        f"- Konum: {sr_data['sr_location']['place'] or '-'} (timezone: {sr_data['sr_location']['timezone_id']})",
        f"- Relocated: {'Evet' if sr_data['sr_location']['is_relocated'] else 'Hayır (doğum yeri)'}",
        f"- Ev sistemi: {sr_chart['meta']['house_system']}",
        f"- Natal Yükselen: {natal_summary['ascendant_sign_tr']}",
        f"- Natal MC: {natal_summary['midheaven_sign_tr']}",
        f"- SR Yükselen: {asc['sign_tr']} {asc['degree_str']}",
        f"- SR MC: {mc['sign_tr']} {mc['degree_str']}",
        f"- SR Yükselen natal **e{sr_data['sr_asc_in_natal_house']}** üzerinde (yılın vurgusu)",
        f"- SR MC natal **e{sr_data['sr_mc_in_natal_house']}** üzerinde",
        "",
    ]

    guide = [
        "## SR Okuma Kılavuzu",
        "",
        "1. SR Yükselen'in natal evi yılın baş teması; orada vurgu olur.",
        "2. SR MC'nin natal evi yıl boyunca hedef/itibar/kariyer alanı.",
        "3. SR ASC/MC ile orb ≤5° kavuşumdaki SR gezegenleri 'yıl temalandırıcı'.",
        "4. SR gezegenlerinin natal evlere düşüşü hangi natal alanların aktif olduğunu gösterir.",
        "5. SR ↔ Natal major açılar (orb ≤3°) yılın net temas noktaları.",
        "6. Hızlı gezegenler (Ay/Merkür/Venüs/Mars) ay-ay zamanlama; yavaşlar yıl trendi.",
        "7. Solar Return tek başına yeterli değildir; transit ve profection ile beraber okunur.",
        "",
    ]

    chart_rows = []
    for planet in sr_chart["planets"]["items"]:
        chart_rows.append((
            _planet_tr(planet["id"]),
            f"{planet['sign_tr']} {planet['degree_str']}",
            f"e{planet['house']}",
            "R" if planet["retrograde"] else "-",
        ))
    for node in sr_chart["nodes"]["items"]:
        chart_rows.append((
            _planet_tr(node["id"]),
            f"{node['sign_tr']} {node['degree_str']}",
            f"e{node['house']}",
            "R" if node["retrograde"] else "-",
        ))
    for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
        a = sr_chart["angles"][angle_id]
        chart_rows.append((
            _planet_tr(angle_id),
            f"{a['sign_tr']} {a['degree_str']}",
            "-",
            "-",
        ))
    chart_section = [
        "## SR Harita Tablosu",
        "",
        _md_table(["Gezegen/Nokta", "Konum", "SR Ev", "Retro"], chart_rows),
        "",
    ]

    theme_rows = []
    for theme in sr_data["yearly_themes"]["ascendant"]:
        theme_rows.append((
            "Yükselen",
            _planet_tr(theme["planet"]),
            f"{theme['orb']:.2f}°",
            theme["sign_tr"],
        ))
    for theme in sr_data["yearly_themes"]["midheaven"]:
        theme_rows.append((
            "MC",
            _planet_tr(theme["planet"]),
            f"{theme['orb']:.2f}°",
            theme["sign_tr"],
        ))
    themes_table = (
        _md_table(["Angle", "SR Gezegen", "Orb", "Burç"], theme_rows)
        if theme_rows
        else "_SR ASC/MC ile 5° içinde kavuşum yapan SR gezegeni yok._"
    )
    themes_section = [
        "## Yıl Temalandırıcı (SR ASC/MC Kavuşumları)",
        "",
        "_SR Yükselen veya MC'ye 5° içinde kavuşumdaki SR gezegenleri yılın baş temasıdır._",
        "",
        themes_table,
        "",
    ]

    natal_house_rows = []
    for item in sr_data["sr_in_natal_houses"]:
        natal_house_rows.append((
            _planet_tr(item["id"]),
            item["sr_sign_tr"],
            f"e{item['sr_house']}",
            f"e{item['natal_house']}",
        ))
    natal_house_section = [
        "## SR Gezegenleri Natal Evlere Düşüş",
        "",
        "_SR gezegenlerinin SR ve natal harita ev numaraları. Natal ev kolonu yılın hangi natal alanın aktif olduğunu gösterir._",
        "",
        _md_table(
            ["Gezegen", "Burç", "SR Ev", "Natal Ev"],
            natal_house_rows,
        ),
        "",
    ]

    cluster_rows = []
    for house in range(1, 13):
        occupants = sr_data["natal_house_occupants_sr"][house]
        if not occupants:
            continue
        cluster_rows.append((
            f"e{house}",
            ", ".join(_planet_tr(p) for p in occupants),
            len(occupants),
        ))
    clusters_section = [
        "## Natal Evlerdeki SR Gezegen Kümeleri",
        "",
        "_Her natal eve düşen SR gezegenleri. 2+ gezegenli evler yıl odağıdır._",
        "",
        (
            _md_table(["Natal Ev", "SR Gezegenleri", "Sayı"], cluster_rows)
            if cluster_rows
            else "_SR gezegen kümesi yok._"
        ),
        "",
    ]

    aspect_rows = []
    for asp in sr_data["sr_natal_aspects"]:
        aspect_rows.append((
            f"SR {_planet_tr(asp['sr'])}",
            _aspect_tr(asp["type"]),
            f"n.{_planet_tr(asp['natal'])}",
            f"{asp['orb']:.2f}°",
            f"e{asp['natal_house']}" if asp["natal_house"] else "-",
            asp["natal_sign_tr"] or "-",
        ))
    aspect_table = (
        _md_table(
            ["SR", "Açı", "Natal", "Orb", "Natal Ev", "Natal Burç"],
            aspect_rows,
        )
        if aspect_rows
        else "_3° içinde SR-natal major açı tespit edilmedi._"
    )
    aspects_section = [
        "## SR ↔ Natal Major Açılar (orb ≤3°)",
        "",
        f"_Toplam: {len(sr_data['sr_natal_aspects'])}. Yılın net temas noktaları._",
        "",
        aspect_table,
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
    ] + [f"- {limit}" for limit in sr_data.get("limitations", [])]

    full = "\n".join([
        *fm_lines,
        *intro,
        *overview,
        *guide,
        *chart_section,
        *themes_section,
        *natal_house_section,
        *clusters_section,
        *aspects_section,
        *limit_section,
    ])
    if embedded:
        return _to_embedded_markdown(full, sr_data)
    return full
