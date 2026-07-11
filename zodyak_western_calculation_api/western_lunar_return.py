#!/usr/bin/env python3
"""Lunar Return calculation for Western Astrology.

Verilen bir tarih için transit Ay'ın natal Ay longitude'una tam geldiği
anı bulur, o an için tam harita üretir ve natal ile karşılaştırma
analizleri sağlar.

Lunar Return aylık çerçevedir; periyot ~27.3 gün, dolayısıyla ayda
ortalama 1 LR olur. Bir LR exact'i, bir sonraki LR exact'ine kadar
geçerli kabul edilir.

Default konum: doğum yeri (klasik). Opsiyonel `return_location` ile
relocated LR.

Bu modül `western_solar_return`'den iki harita karşılaştırma yardımcılarını
yeniden kullanır (Sun/Moon ayrımı dışında mantık aynıdır). SR modülü
değiştirilmez.
"""

from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo

import swisseph as swe

from .western_chart import (
    _signed_delta,
    calculate_core_chart,
)
from .western_solar_return import (
    ASPECT_TR,
    MAJOR_ASPECTS,
    PLANET_TR,
    _build_sr_payload,
    _collect_bodies,
    _compute_sr_natal_aspects,
    _sr_angle_in_natal_house,
    _sr_in_natal_houses,
)


LR_VERSION = "1.0.0"

# LR'da orb SR'den daha sıkı tutulur; aylık periyot kısadır.
LR_NATAL_ORB = 2.0           # LR ↔ natal major aspect eşiği
LR_ANGLE_THEME_ORB = 4.0     # LR ASC/MC'ye "ay temalandırıcı" eşiği


class LunarReturnError(ValueError):
    """Lunar Return input/calculation errors."""


# ---------------------------------------------------------------------------
# Exact LR datetime
# ---------------------------------------------------------------------------


def _moon_longitude_at(jd_ut: float) -> float:
    """Verilen JD'de tropikal Ay longitude'unu döner."""
    values, _ = swe.calc_ut(jd_ut, swe.MOON, swe.FLG_SWIEPH | swe.FLG_SPEED)
    return float(values[0]) % 360.0


def _julian_day_from_utc(dt_utc: datetime) -> float:
    """Yerel hesap için yardımcı (western_chart._julian_day muadili).

    Mikrosaniye duyarlılığıyla JD UT üretir.
    """
    hour = (
        dt_utc.hour
        + dt_utc.minute / 60.0
        + dt_utc.second / 3600.0
        + dt_utc.microsecond / 3_600_000_000.0
    )
    return swe.julday(dt_utc.year, dt_utc.month, dt_utc.day, hour)


def _find_lunar_return_exact_utc(
    natal_moon_longitude: float,
    target_date: date,
) -> datetime:
    """target_date merkezli ±15 gün penceresinde Moon = natal Moon anını bul.

    Ay günde ~13° ilerlediğinden ayda bir LR vardır; ±15 gün penceresi
    bir LR'yi garantili kapsar. Bisection ile 1 saniye hassasiyetine
    kadar daraltılır.
    """
    center = datetime(
        target_date.year, target_date.month, target_date.day,
        12, 0, 0, tzinfo=timezone.utc,
    )
    start = center - timedelta(days=15)
    end = center + timedelta(days=15)

    def diff_at(dt: datetime) -> float:
        return _signed_delta(
            _moon_longitude_at(_julian_day_from_utc(dt)),
            natal_moon_longitude,
        )

    # Ay 360°/27.3g ~13.18°/gün hareket eder. Pencerede birden fazla
    # sıfır geçişi olabilir; tek tek günleri tara ve sıfır geçen ilk
    # alt aralığı bul, sonra bisect et.
    sample_step = timedelta(hours=12)
    cursor = start
    diff_prev = diff_at(cursor)
    found_bracket = None
    while cursor < end:
        next_cursor = cursor + sample_step
        if next_cursor > end:
            next_cursor = end
        diff_next = diff_at(next_cursor)
        # _signed_delta -180..+180 değişimini yakalamak için: ardışık
        # iki diff'in ürünü ≤ 0 ise sıfır geçişi var (Moon hızlı, bu
        # 12 saatlik adımda en fazla ~6.6° kayar; 180°'lik sıçrama yok).
        if diff_prev == 0.0:
            return cursor
        if diff_prev * diff_next < 0:
            # target_date'e en yakın bracket'i seç: ilk bulduğumuzu al
            # ve devam et; sonrasında daha yakın çıkarsa güncelle.
            candidate = (cursor, next_cursor, diff_prev, diff_next)
            if found_bracket is None:
                found_bracket = candidate
            else:
                # Hangi bracket'in ortası target_date'e daha yakın?
                old_mid = found_bracket[0] + (found_bracket[1] - found_bracket[0]) / 2
                new_mid = cursor + (next_cursor - cursor) / 2
                if abs((new_mid - center).total_seconds()) < abs(
                    (old_mid - center).total_seconds()
                ):
                    found_bracket = candidate
        cursor = next_cursor
        diff_prev = diff_next

    if found_bracket is None:
        raise LunarReturnError(
            f"Lunar Return exact anı {target_date.isoformat()} "
            "tarihinin ±15 gün penceresinde bulunamadı."
        )

    bracket_start, bracket_end, diff_start, diff_end = found_bracket

    # Bisection
    for _ in range(100):
        if (bracket_end - bracket_start).total_seconds() <= 1.0:
            break
        mid = bracket_start + (bracket_end - bracket_start) / 2
        diff_mid = diff_at(mid)
        if (diff_start <= 0 <= diff_mid) or (diff_start >= 0 >= diff_mid):
            bracket_end = mid
            diff_end = diff_mid
        else:
            bracket_start = mid
            diff_start = diff_mid

    return bracket_start + (bracket_end - bracket_start) / 2


# ---------------------------------------------------------------------------
# LR'a özgü tema fonksiyonu
# ---------------------------------------------------------------------------


def _monthly_themes(lr_chart: dict, orb: float = LR_ANGLE_THEME_ORB) -> dict:
    """LR ASC/MC'ye orb içinde olan LR gezegenleri (ay temalandırıcı).

    SR'in `_yearly_themes` fonksiyonunun LR muadili; orb 4° (daha sıkı).
    """
    from .western_chart import _shortest_separation

    asc_long = lr_chart["angles"]["ascendant"]["longitude"]
    mc_long = lr_chart["angles"]["midheaven"]["longitude"]

    themes = {"ascendant": [], "midheaven": []}
    for planet in lr_chart["planets"]["items"]:
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


# ---------------------------------------------------------------------------
# Ana fonksiyon
# ---------------------------------------------------------------------------


def calculate_lunar_return(
    payload: dict,
    natal_chart: dict | None = None,
) -> dict:
    """Lunar Return ana hesabı.

    Payload:
        - birth: natal birth bilgisi
        - person, options
        - return_date: 'YYYY-MM-DD' (opsiyonel; default = bugün UTC)
        - return_location: {lat, lon, timezone_id, place}? (relocated LR)
    """
    return_date_str = payload.get("return_date")
    if return_date_str:
        try:
            return_date = datetime.strptime(
                str(return_date_str), "%Y-%m-%d",
            ).date()
        except (ValueError, TypeError) as exc:
            raise LunarReturnError(
                f"Geçersiz return_date (YYYY-MM-DD bekleniyor): {return_date_str}"
            ) from exc
    else:
        return_date = datetime.now(timezone.utc).date()

    return_location = payload.get("return_location")

    natal = natal_chart or calculate_core_chart(payload)

    natal_moon = next(
        p for p in natal["planets"]["items"] if p["id"] == "moon"
    )
    natal_moon_long = natal_moon["longitude"]

    lr_utc = _find_lunar_return_exact_utc(natal_moon_long, return_date)

    lr_payload = _build_sr_payload(payload, lr_utc, return_location)
    lr_chart = calculate_core_chart(lr_payload)

    # SR yardımcılarının LR için adlandırma uyumu
    lr_natal_aspects = _compute_sr_natal_aspects(
        lr_chart, natal, orb=LR_NATAL_ORB,
    )
    lr_in_natal_houses_items = _sr_in_natal_houses(lr_chart, natal)
    monthly_themes = _monthly_themes(lr_chart)
    lr_asc_in_natal = _sr_angle_in_natal_house(lr_chart, natal, "ascendant")
    lr_mc_in_natal = _sr_angle_in_natal_house(lr_chart, natal, "midheaven")

    natal_house_occupants = {h: [] for h in range(1, 13)}
    for item in lr_in_natal_houses_items:
        natal_house_occupants[item["natal_house"]].append(item["id"])

    # Bir sonraki LR tahmini (ortalama 27.32 gün sonra)
    next_lr_estimate_utc = lr_utc + timedelta(days=27, hours=7, minutes=43)

    return {
        "status": "available",
        "version": LR_VERSION,
        "return_date_requested": return_date.isoformat(),
        "lr_exact_utc": lr_utc.isoformat().replace("+00:00", "Z"),
        "lr_exact_local": lr_chart["birth"]["local_datetime"],
        "next_lr_estimate_utc": next_lr_estimate_utc.isoformat().replace(
            "+00:00", "Z"
        ),
        "lr_location": {
            "lat": lr_chart["birth"]["latitude"],
            "lon": lr_chart["birth"]["longitude"],
            "timezone_id": lr_chart["birth"]["timezone_id"],
            "place": lr_chart["birth"]["place"],
            "is_relocated": bool(return_location),
        },
        "natal_summary": {
            "person_name": (natal["birth"].get("person") or {}).get("name"),
            "birth_date": natal["birth"]["date"],
            "ascendant_sign_tr": natal["angles"]["ascendant"]["sign_tr"],
            "midheaven_sign_tr": natal["angles"]["midheaven"]["sign_tr"],
            "moon_sign_tr": natal_moon["sign_tr"],
            "house_system": natal["meta"]["house_system"],
        },
        "lr_chart": lr_chart,
        "lr_in_natal_houses": lr_in_natal_houses_items,
        "natal_house_occupants_lr": natal_house_occupants,
        "lr_asc_in_natal_house": lr_asc_in_natal,
        "lr_mc_in_natal_house": lr_mc_in_natal,
        "monthly_themes": monthly_themes,
        "lr_natal_aspects": lr_natal_aspects,
        "limitations": [
            "Lunar Return aylık çerçevedir; bir sonraki LR'a kadar (~27 gün) geçerli.",
            "Tek başına yeterli değildir; transit, profection ve SR ile beraber okunur.",
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


def build_lunar_return_markdown(
    lr_data: dict,
    group_name: str = "Grup-01",
    generated_at: str | None = None,
) -> str:
    """LR sonucundan markdown raporu üret."""
    lr_chart = lr_data["lr_chart"]
    natal_summary = lr_data["natal_summary"]
    person_name = natal_summary.get("person_name") or "unknown"
    return_date_req = lr_data["return_date_requested"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Lunar Return {return_date_req}"',
        'type: "lunar_return_pack"',
        'source: "western_api_v2_lunar_return"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'return_date_requested: "{return_date_req}"',
        f'lr_exact_utc: "{lr_data["lr_exact_utc"]}"',
        f'lr_exact_local: "{lr_data["lr_exact_local"]}"',
        f'next_lr_estimate_utc: "{lr_data["next_lr_estimate_utc"]}"',
        f'lr_location_place: "{lr_data["lr_location"]["place"] or "-"}"',
        f'lr_location_tz: "{lr_data["lr_location"]["timezone_id"]}"',
        f'is_relocated: {str(lr_data["lr_location"]["is_relocated"]).lower()}',
        f'house_system: "{lr_chart["meta"]["house_system"]}"',
        f'node_type: "{lr_chart["meta"]["node_type"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{LR_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    intro = [
        f"# {person_name} - Lunar Return {return_date_req}",
        "",
        "## Teknik Kullanım Notu",
        "",
        "- Bu dosya Lunar Return (Ay Dönüm) haritasının teknik veri paketidir.",
        "- LR aylık çerçevedir; bir sonraki LR'a kadar (~27 gün) geçerlidir.",
        "- Transit, profection ve SR ile birlikte okunmalıdır; tek başına kullanılmaz.",
        "- Bu çıktı ham teknik veri paketidir; yorum metni değildir.",
        "",
    ]

    asc = lr_chart["angles"]["ascendant"]
    mc = lr_chart["angles"]["midheaven"]
    overview = [
        "## Lunar Return Temel Bilgiler",
        "",
        f"- Kişi: {person_name}",
        f"- Doğum tarihi: {natal_summary['birth_date']}",
        f"- İstenen tarih: {return_date_req}",
        f"- LR exact (UTC): {lr_data['lr_exact_utc']}",
        f"- LR exact (yerel): {lr_data['lr_exact_local']}",
        f"- Sonraki LR tahmini (UTC): {lr_data['next_lr_estimate_utc']}",
        f"- Konum: {lr_data['lr_location']['place'] or '-'} (timezone: {lr_data['lr_location']['timezone_id']})",
        f"- Relocated: {'Evet' if lr_data['lr_location']['is_relocated'] else 'Hayır (doğum yeri)'}",
        f"- Ev sistemi: {lr_chart['meta']['house_system']}",
        f"- Natal Yükselen: {natal_summary['ascendant_sign_tr']}",
        f"- Natal MC: {natal_summary['midheaven_sign_tr']}",
        f"- Natal Ay: {natal_summary['moon_sign_tr']}",
        f"- LR Yükselen: {asc['sign_tr']} {asc['degree_str']}",
        f"- LR MC: {mc['sign_tr']} {mc['degree_str']}",
        f"- LR Yükselen natal **e{lr_data['lr_asc_in_natal_house']}** üzerinde (ayın vurgusu)",
        f"- LR MC natal **e{lr_data['lr_mc_in_natal_house']}** üzerinde",
        "",
    ]

    guide = [
        "## LR Okuma Kılavuzu",
        "",
        "1. LR Yükselen'in natal evi bu ayın baş teması.",
        "2. LR MC'nin natal evi ayın görünür/hedef alanı.",
        "3. LR ASC/MC ile orb ≤4° kavuşumdaki LR gezegenleri 'ay temalandırıcı'.",
        "4. LR gezegenlerinin natal evlere düşüşü hangi natal alanların aktif olduğunu gösterir.",
        "5. LR ↔ Natal major açılar (orb ≤2°) ayın net temas noktaları.",
        "6. Ay'ın natal evi günlük zamanlamayı; LR Sun'ın natal evi ayın enerji odağını gösterir.",
        "7. LR tek başına yeterli değildir; transit, profection ve SR ile beraber okunur.",
        "",
    ]

    chart_rows = []
    for planet in lr_chart["planets"]["items"]:
        chart_rows.append((
            _planet_tr(planet["id"]),
            f"{planet['sign_tr']} {planet['degree_str']}",
            f"e{planet['house']}",
            "R" if planet["retrograde"] else "-",
        ))
    for node in lr_chart["nodes"]["items"]:
        chart_rows.append((
            _planet_tr(node["id"]),
            f"{node['sign_tr']} {node['degree_str']}",
            f"e{node['house']}",
            "R" if node["retrograde"] else "-",
        ))
    for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
        a = lr_chart["angles"][angle_id]
        chart_rows.append((
            _planet_tr(angle_id),
            f"{a['sign_tr']} {a['degree_str']}",
            "-",
            "-",
        ))
    chart_section = [
        "## LR Harita Tablosu",
        "",
        _md_table(["Gezegen/Nokta", "Konum", "LR Ev", "Retro"], chart_rows),
        "",
    ]

    theme_rows = []
    for theme in lr_data["monthly_themes"]["ascendant"]:
        theme_rows.append((
            "Yükselen",
            _planet_tr(theme["planet"]),
            f"{theme['orb']:.2f}°",
            theme["sign_tr"],
        ))
    for theme in lr_data["monthly_themes"]["midheaven"]:
        theme_rows.append((
            "MC",
            _planet_tr(theme["planet"]),
            f"{theme['orb']:.2f}°",
            theme["sign_tr"],
        ))
    themes_table = (
        _md_table(["Angle", "LR Gezegen", "Orb", "Burç"], theme_rows)
        if theme_rows
        else "_LR ASC/MC ile 4° içinde kavuşum yapan LR gezegeni yok._"
    )
    themes_section = [
        "## Ay Temalandırıcı (LR ASC/MC Kavuşumları)",
        "",
        "_LR Yükselen veya MC'ye 4° içinde kavuşumdaki LR gezegenleri ayın baş temasıdır._",
        "",
        themes_table,
        "",
    ]

    natal_house_rows = []
    for item in lr_data["lr_in_natal_houses"]:
        natal_house_rows.append((
            _planet_tr(item["id"]),
            item["sr_sign_tr"],  # SR helper'dan geliyor; alan adı sr_
            f"e{item['sr_house']}",
            f"e{item['natal_house']}",
        ))
    natal_house_section = [
        "## LR Gezegenleri Natal Evlere Düşüş",
        "",
        "_LR gezegenlerinin LR ve natal harita ev numaraları. Natal ev kolonu ayın hangi natal alanın aktif olduğunu gösterir._",
        "",
        _md_table(
            ["Gezegen", "Burç", "LR Ev", "Natal Ev"],
            natal_house_rows,
        ),
        "",
    ]

    cluster_rows = []
    for house in range(1, 13):
        occupants = lr_data["natal_house_occupants_lr"][house]
        if not occupants:
            continue
        cluster_rows.append((
            f"e{house}",
            ", ".join(_planet_tr(p) for p in occupants),
            len(occupants),
        ))
    clusters_section = [
        "## Natal Evlerdeki LR Gezegen Kümeleri",
        "",
        "_Her natal eve düşen LR gezegenleri. 2+ gezegenli evler ayın odağıdır._",
        "",
        (
            _md_table(["Natal Ev", "LR Gezegenleri", "Sayı"], cluster_rows)
            if cluster_rows
            else "_LR gezegen kümesi yok._"
        ),
        "",
    ]

    aspect_rows = []
    for asp in lr_data["lr_natal_aspects"]:
        # SR helper'dan geliyor; alan adları sr_ ile başlıyor ama içerik LR.
        aspect_rows.append((
            f"LR {_planet_tr(asp['sr'])}",
            _aspect_tr(asp["type"]),
            f"n.{_planet_tr(asp['natal'])}",
            f"{asp['orb']:.2f}°",
            f"e{asp['natal_house']}" if asp["natal_house"] else "-",
            asp["natal_sign_tr"] or "-",
        ))
    aspect_table = (
        _md_table(
            ["LR", "Açı", "Natal", "Orb", "Natal Ev", "Natal Burç"],
            aspect_rows,
        )
        if aspect_rows
        else "_2° içinde LR-natal major açı tespit edilmedi._"
    )
    aspects_section = [
        f"## LR ↔ Natal Major Açılar (orb ≤{LR_NATAL_ORB:.0f}°)",
        "",
        f"_Toplam: {len(lr_data['lr_natal_aspects'])}. Ayın net temas noktaları._",
        "",
        aspect_table,
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
    ] + [f"- {limit}" for limit in lr_data.get("limitations", [])]

    return "\n".join([
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
