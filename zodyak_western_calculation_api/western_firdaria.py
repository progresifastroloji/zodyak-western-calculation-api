#!/usr/bin/env python3
"""Firdaria classical Persian time-lord calculations.

Klasik Pers time-lord tekniği. Doğum sect'ine göre (gündüz/gece) 9
ana dönem (major firdar) 75 yıllık tam döngü oluşturur. Her ana
dönem (Node'lar hariç) 7 eşit alt-döneme (sub-firdar) bölünür.

Gündüz sırası: Sun(10) → Venus(8) → Mercury(13) → Moon(9) →
Saturn(11) → Jupiter(12) → Mars(7) → North Node(3) → South Node(2)

Gece sırası: Moon(9) → Saturn(11) → Jupiter(12) → Mars(7) →
Sun(10) → Venus(8) → Mercury(13) → North Node(3) → South Node(2)

Sub-period sırası: Ana lord'tan başlayıp Chaldean sırasında ilerler:
Saturn → Jupiter → Mars → Sun → Venus → Mercury → Moon → (Saturn'a dön)

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve calculate_core_chart fonksiyonunu kullanır.
"""

from __future__ import annotations

import json
import os
from datetime import date, datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


FIRDARIA_VERSION = "1.0.0"
TROPICAL_YEAR_DAYS = 365.2422
TOTAL_FIRDARIA_CYCLE = 75.0  # yıl
DEFAULT_REFERENCE_TIMEZONE = os.environ.get(
    "WESTERN_ASTROLOGY_DEFAULT_TIMEZONE", "Europe/Istanbul",
)

# (lord, yıl) sıralı; toplam 75 yıl
DIURNAL_FIRDARIA = [
    ("sun", 10.0),
    ("venus", 8.0),
    ("mercury", 13.0),
    ("moon", 9.0),
    ("saturn", 11.0),
    ("jupiter", 12.0),
    ("mars", 7.0),
    ("north_node", 3.0),
    ("south_node", 2.0),
]

NOCTURNAL_FIRDARIA = [
    ("moon", 9.0),
    ("saturn", 11.0),
    ("jupiter", 12.0),
    ("mars", 7.0),
    ("sun", 10.0),
    ("venus", 8.0),
    ("mercury", 13.0),
    ("north_node", 3.0),
    ("south_node", 2.0),
]

# Chaldean sırası (sub-period için)
CHALDEAN_ORDER = ["saturn", "jupiter", "mars", "sun", "venus", "mercury", "moon"]

# Klasik 7 gezegen (sub-period'a katılanlar)
SUB_PERIOD_LORDS = set(CHALDEAN_ORDER)
NODE_LORDS = {"north_node", "south_node"}

PLANET_TR = {
    "sun": "Güneş",
    "moon": "Ay",
    "mercury": "Merkür",
    "venus": "Venüs",
    "mars": "Mars",
    "jupiter": "Jüpiter",
    "saturn": "Satürn",
    "north_node": "Kuzey Ay Düğümü",
    "south_node": "Güney Ay Düğümü",
}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class FirdariaInputError(ValueError):
    """Firdaria için geçersiz input."""


class FirdariaCalculationError(RuntimeError):
    """Firdaria hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _parse_target_date(value: str) -> date:
    try:
        return datetime.strptime(str(value), "%Y-%m-%d").date()
    except (ValueError, TypeError) as exc:
        raise FirdariaInputError(
            f"Geçersiz tarih (YYYY-MM-DD bekleniyor): {value}"
        ) from exc


def _validate_input(payload: dict) -> tuple[date, str]:
    if not isinstance(payload, dict):
        raise FirdariaInputError("JSON gövdesi nesne olmalıdır")
    f = payload.get("firdaria") or {}
    if not isinstance(f, dict):
        raise FirdariaInputError("firdaria alanı nesne olmalıdır")

    target_value = f.get("target_date")
    if target_value:
        target_date = _parse_target_date(target_value)
    else:
        target_date = date.today()

    reference_tz = str(f.get("reference_timezone") or DEFAULT_REFERENCE_TIMEZONE)
    try:
        ZoneInfo(reference_tz)
    except ZoneInfoNotFoundError as exc:
        raise FirdariaInputError(
            f"Geçersiz firdaria.reference_timezone: {reference_tz}"
        ) from exc

    return target_date, reference_tz


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


def _date_from_age(birth_utc: datetime, age_years: float) -> datetime:
    """Yaş cinsinden ofseti UTC tarihe çevirir."""
    return birth_utc + timedelta(days=age_years * TROPICAL_YEAR_DAYS)


def _sub_sequence(major_lord: str) -> list[str]:
    """Ana lord'tan başlayarak Chaldean sırasında 7 sub-lord."""
    if major_lord not in SUB_PERIOD_LORDS:
        return []
    start_idx = CHALDEAN_ORDER.index(major_lord)
    return [
        CHALDEAN_ORDER[(start_idx + offset) % 7]
        for offset in range(7)
    ]


def _build_majors_with_dates(
    sequence: list[tuple[str, float]],
    birth_utc: datetime,
    cycle_offset_years: float = 0.0,
) -> list[dict]:
    """Sıralı major dönemleri start/end yaş ve tarihleri ile döner."""
    result = []
    cumulative = cycle_offset_years
    for index, (lord, years) in enumerate(sequence):
        start_age = cumulative
        end_age = cumulative + years
        result.append({
            "index": index,
            "lord": lord,
            "lord_tr": PLANET_TR.get(lord, lord),
            "years": years,
            "start_age": round(start_age, 6),
            "end_age": round(end_age, 6),
            "start_date_utc": _date_from_age(birth_utc, start_age).date().isoformat(),
            "end_date_utc": _date_from_age(birth_utc, end_age).date().isoformat(),
            "has_sub_periods": lord not in NODE_LORDS,
        })
        cumulative = end_age
    return result


def _build_subs_for_major(
    major: dict,
    birth_utc: datetime,
) -> list[dict]:
    """Bir ana dönem için 7 alt-dönem üretir (Node'lar hariç)."""
    if not major["has_sub_periods"]:
        return []
    sub_sequence = _sub_sequence(major["lord"])
    sub_length = major["years"] / 7.0
    subs = []
    for index, sub_lord in enumerate(sub_sequence):
        sub_start_age = major["start_age"] + index * sub_length
        sub_end_age = sub_start_age + sub_length
        subs.append({
            "index": index,
            "lord": sub_lord,
            "lord_tr": PLANET_TR.get(sub_lord, sub_lord),
            "years": round(sub_length, 6),
            "start_age": round(sub_start_age, 6),
            "end_age": round(sub_end_age, 6),
            "start_date_utc": _date_from_age(birth_utc, sub_start_age).date().isoformat(),
            "end_date_utc": _date_from_age(birth_utc, sub_end_age).date().isoformat(),
        })
    return subs


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_firdaria(payload: dict, chart: dict | None = None) -> dict:
    """Firdaria zaman-lord paketi üretir."""

    target_date, reference_tz = _validate_input(payload)
    natal_chart = chart or calculate_core_chart(payload)

    birth = natal_chart["birth"]
    birth_utc = datetime.fromisoformat(
        birth["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)

    # Sect tespiti (mevcut natal_derivatives mantığıyla aynı)
    sun = next(p for p in natal_chart["planets"]["items"] if p["id"] == "sun")
    chart_sect = "diurnal" if sun["house"] in {7, 8, 9, 10, 11, 12} else "nocturnal"
    sequence = DIURNAL_FIRDARIA if chart_sect == "diurnal" else NOCTURNAL_FIRDARIA

    age_years = _compute_age_years(birth_utc, target_date, reference_tz)
    if age_years < 0:
        raise FirdariaInputError("Hedef tarih doğum tarihinden önce olamaz")

    # 75 yıllık döngüyü tekrar et
    cycle_number = int(age_years // TOTAL_FIRDARIA_CYCLE)
    age_in_cycle = age_years - cycle_number * TOTAL_FIRDARIA_CYCLE
    cycle_offset_years = cycle_number * TOTAL_FIRDARIA_CYCLE

    # Mevcut döngünün tüm major'leri (start/end yaşları gerçek doğumdan itibaren)
    all_majors_current_cycle = _build_majors_with_dates(
        sequence, birth_utc, cycle_offset_years
    )

    # Aktif major'u bul
    current_major = None
    for major in all_majors_current_cycle:
        if major["start_age"] <= age_years < major["end_age"]:
            current_major = major
            break
    if current_major is None:
        # Sayısal kenar durumu: tam end_age noktasında bir sonraki başlasın
        current_major = all_majors_current_cycle[-1]

    # Major içindeki konum
    years_elapsed_in_major = age_years - current_major["start_age"]
    years_remaining_in_major = current_major["end_age"] - age_years
    current_major_summary = {
        **current_major,
        "years_elapsed": round(years_elapsed_in_major, 6),
        "years_remaining": round(years_remaining_in_major, 6),
        "progress_ratio": round(
            years_elapsed_in_major / current_major["years"], 6,
        ) if current_major["years"] > 0 else 0.0,
    }

    # Aktif major'un tüm sub'ları
    subs_of_current_major = _build_subs_for_major(current_major, birth_utc)

    # Aktif sub'u bul
    current_sub_summary = None
    if subs_of_current_major:
        current_sub = None
        for sub in subs_of_current_major:
            if sub["start_age"] <= age_years < sub["end_age"]:
                current_sub = sub
                break
        if current_sub is None:
            current_sub = subs_of_current_major[-1]
        years_elapsed_in_sub = age_years - current_sub["start_age"]
        years_remaining_in_sub = current_sub["end_age"] - age_years
        current_sub_summary = {
            **current_sub,
            "years_elapsed": round(years_elapsed_in_sub, 6),
            "years_remaining": round(years_remaining_in_sub, 6),
            "progress_ratio": round(
                years_elapsed_in_sub / current_sub["years"], 6,
            ) if current_sub["years"] > 0 else 0.0,
        }

    # Sonraki major (sub değişimi olmayanlarda da sıradaki major gösterilsin)
    current_major_index = current_major["index"]
    if current_major_index + 1 < len(all_majors_current_cycle):
        next_major = all_majors_current_cycle[current_major_index + 1]
    else:
        # Döngü tekrar başlar
        next_cycle_majors = _build_majors_with_dates(
            sequence, birth_utc, cycle_offset_years + TOTAL_FIRDARIA_CYCLE,
        )
        next_major = next_cycle_majors[0]

    natal_summary = {
        "birth_date": birth["date"],
        "birth_time": birth["time"],
        "house_system": natal_chart["meta"]["house_system"],
        "sun_house": sun["house"],
        "chart_sect_method": "sun_house_7_to_12_is_above_horizon",
    }

    limitations = [
        "Firdaria sembolik bir time-lord tekniğidir; transit/SR/profections ile birlikte okunur.",
        "Sub-period sırası ana lord'tan başlayıp Chaldean sırasında ilerler.",
        "North/South Node major dönemlerinde sub-period yoktur.",
        f"Tek tam döngü {TOTAL_FIRDARIA_CYCLE:.0f} yıldır; sonra dizi tekrar başlar.",
    ]
    time_confidence = natal_chart["data_quality"].get("birth_time_confidence")
    if time_confidence in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; sect tespiti Sun'ın ev konumuna bağlı "
            "olduğundan ufuk yakınında saat hatası diurnal/nocturnal kararını çevirebilir."
        )

    return {
        "status": "available",
        "version": FIRDARIA_VERSION,
        "method": "firdaria_classical_persian_with_chaldean_subs",
        "target_date": target_date.isoformat(),
        "reference_timezone": reference_tz,
        "age_years": round(age_years, 6),
        "cycle_number": cycle_number,
        "age_in_cycle": round(age_in_cycle, 6),
        "chart_sect": chart_sect,
        "natal_summary": natal_summary,
        "current_major": current_major_summary,
        "current_sub": current_sub_summary,
        "next_major": next_major,
        "all_majors_current_cycle": all_majors_current_cycle,
        "subs_of_current_major": subs_of_current_major,
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
    lines = [
        "| " + " | ".join(headers) + " |",
        "| " + " | ".join("---" for _ in headers) + " |",
    ]
    lines.extend(
        "| " + " | ".join(_markdown_value(v) for v in row) + " |"
        for row in rows
    )
    return "\n".join(lines)


def build_firdaria_markdown(
    firdaria: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    target_date = firdaria["target_date"]
    age = firdaria["age_years"]
    sect = firdaria["chart_sect"]
    natal_summary = firdaria["natal_summary"]
    current_major = firdaria["current_major"]
    current_sub = firdaria["current_sub"]
    next_major = firdaria["next_major"]
    all_majors = firdaria["all_majors_current_cycle"]
    subs = firdaria["subs_of_current_major"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Firdaria {target_date}"',
        'type: "firdaria_pack"',
        'source: "western_api_v2_firdaria"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'target_date: "{target_date}"',
        f'age_years: {age}',
        f'chart_sect: "{sect}"',
        f'current_major_lord: "{current_major["lord"]}"',
        f'current_sub_lord: "{current_sub["lord"] if current_sub else "-"}"',
        f'method: "{firdaria["method"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{FIRDARIA_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Firdaria {target_date}",
        "",
        "## Kullanım Notu",
        "",
        "- Firdaria klasik Pers time-lord tekniğidir; sembolik dönem yöneticilerini listeler.",
        "- Yorum içermez; transit/SR/profections ile birlikte okunmalıdır.",
        "- 75 yıllık tam döngü içinde 9 ana dönem (major firdar), her ana dönem 7 alt-dönem (sub-firdar).",
        "- Node major dönemlerinde sub-period yoktur.",
        "",
        "## Dönem Özeti",
        "",
        f"- Hedef tarih: {target_date}",
        f"- Yaş: {age:.4f}",
        f"- Chart sect: **{sect}** (Sun {natal_summary['sun_house']}. evde)",
        f"- Cycle: {firdaria['cycle_number']} (yaş döngüde: {firdaria['age_in_cycle']:.4f})",
        f"- Doğum: {natal_summary['birth_date']} {natal_summary['birth_time']}",
        "",
        "## Aktif Major Firdar",
        "",
        f"- **Lord: {current_major['lord_tr']}** ({current_major['lord']})",
        f"- Süre: {current_major['years']:.1f} yıl",
        f"- Yaş aralığı: {current_major['start_age']:.2f} → {current_major['end_age']:.2f}",
        f"- Tarih aralığı: {current_major['start_date_utc']} → {current_major['end_date_utc']}",
        f"- Geçen: {current_major['years_elapsed']:.4f} yıl",
        f"- Kalan: {current_major['years_remaining']:.4f} yıl",
        f"- İlerleme: %{current_major['progress_ratio'] * 100:.1f}",
        "",
    ]

    if current_sub:
        overview.extend([
            "## Aktif Sub-Firdar",
            "",
            f"- **Sub Lord: {current_sub['lord_tr']}** ({current_sub['lord']})",
            f"- Süre: {current_sub['years']:.4f} yıl",
            f"- Yaş aralığı: {current_sub['start_age']:.2f} → {current_sub['end_age']:.2f}",
            f"- Tarih aralığı: {current_sub['start_date_utc']} → {current_sub['end_date_utc']}",
            f"- Geçen: {current_sub['years_elapsed']:.4f} yıl",
            f"- Kalan: {current_sub['years_remaining']:.4f} yıl",
            f"- İlerleme: %{current_sub['progress_ratio'] * 100:.1f}",
            "",
        ])
    else:
        overview.extend([
            "## Aktif Sub-Firdar",
            "",
            "_Aktif ana lord Node'dur; sub-period yoktur._",
            "",
        ])

    overview.extend([
        "## Sonraki Major Firdar",
        "",
        f"- Lord: **{next_major['lord_tr']}** ({next_major['lord']})",
        f"- Başlangıç: {next_major['start_date_utc']} (yaş {next_major['start_age']:.2f})",
        f"- Bitiş: {next_major['end_date_utc']} (yaş {next_major['end_age']:.2f})",
        f"- Süre: {next_major['years']:.1f} yıl",
        "",
    ])

    major_rows = [
        (
            f'{m["index"] + 1}',
            m["lord_tr"],
            f'{m["years"]:.1f}',
            f'{m["start_age"]:.2f}',
            f'{m["end_age"]:.2f}',
            m["start_date_utc"],
            m["end_date_utc"],
            "Evet" if m["has_sub_periods"] else "Hayır",
            "← AKTİF" if m["index"] == current_major["index"] else "",
        )
        for m in all_majors
    ]
    majors_section = [
        "## Mevcut Döngünün Tüm Major Firdaria Dönemleri",
        "",
        _md_table(
            [
                "#",
                "Lord",
                "Yıl",
                "Başlangıç Yaşı",
                "Bitiş Yaşı",
                "Başlangıç Tarihi (UTC)",
                "Bitiş Tarihi (UTC)",
                "Sub var mı?",
                "Durum",
            ],
            major_rows,
        ),
        "",
    ]

    if subs:
        sub_rows = [
            (
                f'{s["index"] + 1}',
                s["lord_tr"],
                f'{s["years"]:.4f}',
                f'{s["start_age"]:.2f}',
                f'{s["end_age"]:.2f}',
                s["start_date_utc"],
                s["end_date_utc"],
                "← AKTİF" if (current_sub and s["index"] == current_sub["index"]) else "",
            )
            for s in subs
        ]
        subs_table = _md_table(
            [
                "#",
                "Sub Lord",
                "Yıl",
                "Başlangıç Yaşı",
                "Bitiş Yaşı",
                "Başlangıç Tarihi (UTC)",
                "Bitiş Tarihi (UTC)",
                "Durum",
            ],
            sub_rows,
        )
    else:
        subs_table = "_Aktif ana lord Node olduğundan sub-period yok._"

    subs_section = [
        f"## Aktif Major ({current_major['lord_tr']}) İçin Sub-Firdaria Dönemleri",
        "",
        subs_table,
        "",
    ]

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in firdaria.get("limitations", [])],
        "",
    ]

    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "Aşağıdaki JSON tüm Firdaria datasının makine-okunur kopyasıdır.",
        "",
        "```json",
        json.dumps(firdaria, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *majors_section,
        *subs_section,
        *limit_section,
        *technical_section,
    ])
