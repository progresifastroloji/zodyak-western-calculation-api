#!/usr/bin/env python3
"""Mundane astrology (dünya astrolojisi) calculations.

v1 kapsamı — üç olay tipi:
- aries_ingress: Güneş'in 0° Koç'a giriş anı (yıllık dünya haritası)
- lunation: verilen ay içindeki Yeniay ve Dolunay anları
- eclipse: verilen yıl içindeki Güneş ve Ay tutulmaları

Her olay için verilen referans konuma göre harita kurulur (mundane
haritalar konuma göre okunur; başkent koordinatı verilmesi tipiktir).

v2'ye: Great Conjunctions, planet ingresses, national charts,
etkilenen coğrafya analizi.

Bu bir veri paketidir; yorum içermez.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

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


MUNDANE_VERSION = "1.0.0"

EVENT_TYPES = {"aries_ingress", "lunation", "eclipse"}

MIN_YEAR = 1800
MAX_YEAR = 2100


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class MundaneInputError(ValueError):
    """Mundane için geçersiz input."""


class MundaneCalculationError(RuntimeError):
    """Mundane hesaplama hatası."""


# ---------------------------------------------------------------------------
# Input doğrulama
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise MundaneInputError("JSON gövdesi nesne olmalıdır")
    m = payload.get("mundane") or {}
    if not isinstance(m, dict):
        raise MundaneInputError("mundane alanı nesne olmalıdır")

    event_type = m.get("event_type")
    if event_type not in EVENT_TYPES:
        raise MundaneInputError(
            f"mundane.event_type zorunlu ve şunlardan biri olmalı: "
            f"{', '.join(sorted(EVENT_TYPES))}"
        )

    try:
        year = int(m.get("year"))
    except (TypeError, ValueError) as exc:
        raise MundaneInputError("mundane.year tam sayı olmalıdır") from exc
    if not MIN_YEAR <= year <= MAX_YEAR:
        raise MundaneInputError(f"mundane.year {MIN_YEAR}-{MAX_YEAR} arasında olmalıdır")

    month = None
    if event_type == "lunation":
        try:
            month = int(m.get("month"))
        except (TypeError, ValueError) as exc:
            raise MundaneInputError(
                "lunation için mundane.month (1-12) zorunludur"
            ) from exc
        if not 1 <= month <= 12:
            raise MundaneInputError("mundane.month 1-12 arasında olmalıdır")

    loc = m.get("location") or {}
    if not isinstance(loc, dict) or "lat" not in loc or "lon" not in loc:
        raise MundaneInputError(
            "mundane.location.lat ve lon zorunludur (mundane harita konuma göre kurulur; "
            "tipik olarak başkent koordinatı verilir)"
        )
    tz_id = loc.get("timezone_id") or "UTC"
    try:
        ZoneInfo(str(tz_id))
    except ZoneInfoNotFoundError as exc:
        raise MundaneInputError(f"Geçersiz timezone_id: {tz_id}") from exc

    return {
        "event_type": event_type,
        "year": year,
        "month": month,
        "location": {
            "lat": float(loc["lat"]),
            "lon": float(loc["lon"]),
            "timezone_id": str(tz_id),
            "place": loc.get("place"),
        },
    }


# ---------------------------------------------------------------------------
# Olay anı bulucular
# ---------------------------------------------------------------------------


def _jd_to_datetime(jd: float) -> datetime:
    year, month, day, hour_decimal = swe.revjul(jd)
    hours = int(hour_decimal)
    minutes_float = (hour_decimal - hours) * 60.0
    minutes = int(minutes_float)
    seconds_float = (minutes_float - minutes) * 60.0
    seconds = int(seconds_float)
    microseconds = int((seconds_float - seconds) * 1e6)
    return datetime(
        year, month, day, hours, minutes, seconds, microseconds,
        tzinfo=timezone.utc,
    )


def _sun_longitude(jd: float) -> float:
    values, _ = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH)
    return float(values[0]) % 360.0


def _moon_sun_elongation(jd: float) -> float:
    """Moon - Sun boylam farkı (0-360)."""
    sun, _ = swe.calc_ut(jd, swe.SUN, swe.FLG_SWIEPH)
    moon, _ = swe.calc_ut(jd, swe.MOON, swe.FLG_SWIEPH)
    return (float(moon[0]) - float(sun[0])) % 360.0


def _find_aries_ingress(year: int) -> datetime:
    """Güneş'in 0° Koç'a girişini bisection ile bul (Mart 18-23 arası)."""
    jd_start = swe.julday(year, 3, 15, 0.0)
    jd_end = swe.julday(year, 3, 25, 0.0)

    # Sun longitude Mart ortasında ~354-360, ingress'te 0'ı geçer.
    # Fonksiyon: f(jd) = ((sun_lon + 180) % 360) - 180 → ingress'te işaret değişimi
    def f(jd):
        lon = _sun_longitude(jd)
        return ((lon + 180.0) % 360.0) - 180.0

    lo, hi = jd_start, jd_end
    f_lo = f(lo)
    # İşaret değişimini kaba tara (0.25 gün adım)
    step = 0.25
    found = False
    jd = lo
    while jd < hi:
        f_cur = f(jd + step)
        if f_lo < 0 <= f_cur or (f_lo > 0 and f_cur <= 0 and abs(f_lo) < 90):
            lo, hi = jd, jd + step
            found = True
            break
        f_lo = f_cur
        jd += step
    if not found:
        raise MundaneCalculationError(f"{year} Aries ingress bulunamadı")

    # Bisection
    for _ in range(60):
        mid = (lo + hi) / 2.0
        if f(lo) * f(mid) <= 0:
            hi = mid
        else:
            lo = mid
    return _jd_to_datetime((lo + hi) / 2.0)


def _find_lunations(year: int, month: int) -> list[dict]:
    """Ay içindeki Yeniay (elongasyon 0) ve Dolunay (180) anları."""
    jd_start = swe.julday(year, month, 1, 0.0)
    if month == 12:
        jd_end = swe.julday(year + 1, 1, 1, 0.0)
    else:
        jd_end = swe.julday(year, month + 1, 1, 0.0)

    events = []
    for target, label, tr in ((0.0, "new_moon", "Yeniay"), (180.0, "full_moon", "Dolunay")):
        def f(jd, t=target):
            return ((_moon_sun_elongation(jd) - t + 180.0) % 360.0) - 180.0

        step = 0.5
        jd = jd_start
        f_prev = f(jd)
        while jd < jd_end:
            jd_next = jd + step
            f_cur = f(jd_next)
            # İşaret değişimi + süreklilik kontrolü (sıçrama değil)
            if f_prev * f_cur <= 0 and abs(f_prev) < 90 and abs(f_cur) < 90:
                lo, hi = jd, jd_next
                for _ in range(60):
                    mid = (lo + hi) / 2.0
                    if f(lo) * f(mid) <= 0:
                        hi = mid
                    else:
                        lo = mid
                event_dt = _jd_to_datetime((lo + hi) / 2.0)
                if event_dt.year == year and event_dt.month == month:
                    events.append({
                        "type": label,
                        "type_tr": tr,
                        "utc_datetime": event_dt.isoformat().replace("+00:00", "Z"),
                        "_dt": event_dt,
                    })
            f_prev = f_cur
            jd = jd_next
    events.sort(key=lambda e: e["_dt"])
    return events


def _find_eclipses(year: int) -> list[dict]:
    """Yıl içindeki Güneş ve Ay tutulmaları (swe.sol_eclipse_when_glob / lun_eclipse_when)."""
    events = []
    jd_start = swe.julday(year, 1, 1, 0.0)
    jd_year_end = swe.julday(year + 1, 1, 1, 0.0)

    # Güneş tutulmaları
    jd = jd_start
    for _ in range(10):  # yılda en fazla 5 güneş tutulması olur
        try:
            retflag, tret = swe.sol_eclipse_when_glob(jd, swe.FLG_SWIEPH, 0)
        except swe.Error:
            break
        jd_max = tret[0]
        if jd_max >= jd_year_end:
            break
        ecl_dt = _jd_to_datetime(jd_max)
        kind = []
        if retflag & swe.ECL_TOTAL:
            kind.append("total")
        if retflag & swe.ECL_ANNULAR:
            kind.append("annular")
        if retflag & swe.ECL_PARTIAL:
            kind.append("partial")
        if retflag & swe.ECL_ANNULAR_TOTAL:
            kind.append("hybrid")
        events.append({
            "type": "solar_eclipse",
            "type_tr": "Güneş Tutulması",
            "kind": "/".join(kind) or "unknown",
            "utc_datetime": ecl_dt.isoformat().replace("+00:00", "Z"),
            "_dt": ecl_dt,
        })
        jd = jd_max + 10.0

    # Ay tutulmaları
    jd = jd_start
    for _ in range(10):
        try:
            retflag, tret = swe.lun_eclipse_when(jd, swe.FLG_SWIEPH, 0)
        except swe.Error:
            break
        jd_max = tret[0]
        if jd_max >= jd_year_end:
            break
        ecl_dt = _jd_to_datetime(jd_max)
        kind = []
        if retflag & swe.ECL_TOTAL:
            kind.append("total")
        if retflag & swe.ECL_PARTIAL:
            kind.append("partial")
        if retflag & swe.ECL_PENUMBRAL:
            kind.append("penumbral")
        events.append({
            "type": "lunar_eclipse",
            "type_tr": "Ay Tutulması",
            "kind": "/".join(kind) or "unknown",
            "utc_datetime": ecl_dt.isoformat().replace("+00:00", "Z"),
            "_dt": ecl_dt,
        })
        jd = jd_max + 10.0

    events.sort(key=lambda e: e["_dt"])
    return events


def _chart_for_moment(dt: datetime, loc: dict, options: dict, label: str) -> dict:
    payload = {
        "birth": {
            "year": dt.year,
            "month": dt.month,
            "day": dt.day,
            "hour": dt.hour,
            "minute": dt.minute,
            "second": dt.second,
            "lat": loc["lat"],
            "lon": loc["lon"],
            "timezone_id": "UTC",
            "utc": True,
            "place": label,
            "time_confidence": "high",
        },
        "options": options,
    }
    return calculate_core_chart(payload)


def _chart_summary(chart: dict) -> dict:
    """Mundane özet: eksenler + gezegen konumları + majör açılar."""
    return {
        "ascendant": f'{chart["angles"]["ascendant"]["sign_tr"]} {chart["angles"]["ascendant"]["degree_str"]}',
        "midheaven": f'{chart["angles"]["midheaven"]["sign_tr"]} {chart["angles"]["midheaven"]["degree_str"]}',
        "planets": [
            {
                "id": p["id"],
                "name_tr": p.get("name_tr"),
                "position": f'{p["sign_tr"]} {p["degree_str"]}',
                "house": p.get("house"),
                "retrograde": p.get("retrograde", False),
            }
            for p in chart["planets"]["items"]
        ],
        "major_aspects": [
            {
                "from": a["from"],
                "type": a["type"],
                "to": a["to"],
                "orb": a["orb"],
            }
            for a in (chart.get("aspects") or {}).get("major", [])
        ],
    }


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_mundane(payload: dict) -> dict:
    """Mundane olay(lar) + haritalar."""

    params = _validate_input(payload)
    loc = params["location"]
    options = payload.get("options") or {}
    event_type = params["event_type"]
    year = params["year"]

    events_out = []

    if event_type == "aries_ingress":
        ingress_dt = _find_aries_ingress(year)
        chart = _chart_for_moment(
            ingress_dt, loc, options, f"Aries Ingress {year}",
        )
        events_out.append({
            "type": "aries_ingress",
            "type_tr": "Koç Girişi (Yıllık Harita)",
            "utc_datetime": ingress_dt.isoformat().replace("+00:00", "Z"),
            "chart_summary": _chart_summary(chart),
        })
    elif event_type == "lunation":
        lunations = _find_lunations(year, params["month"])
        for ev in lunations:
            chart = _chart_for_moment(
                ev["_dt"], loc, options,
                f'{ev["type_tr"]} {ev["_dt"].date().isoformat()}',
            )
            events_out.append({
                "type": ev["type"],
                "type_tr": ev["type_tr"],
                "utc_datetime": ev["utc_datetime"],
                "chart_summary": _chart_summary(chart),
            })
    elif event_type == "eclipse":
        eclipses = _find_eclipses(year)
        for ev in eclipses:
            chart = _chart_for_moment(
                ev["_dt"], loc, options,
                f'{ev["type_tr"]} {ev["_dt"].date().isoformat()}',
            )
            events_out.append({
                "type": ev["type"],
                "type_tr": ev["type_tr"],
                "kind": ev["kind"],
                "utc_datetime": ev["utc_datetime"],
                "chart_summary": _chart_summary(chart),
            })

    if not events_out:
        raise MundaneCalculationError(
            f"{year} için {event_type} olayı bulunamadı"
        )

    limitations = [
        "Mundane haritalar verilen konuma göre kurulur; farklı başkentler farklı ASC/MC/ev verir.",
        "Great Conjunctions, planet ingresses ve national charts v1'de yoktur.",
        "Tutulma görünürlük coğrafyası (path of totality) v1'de yoktur.",
        "Bu veri paketi yorum içermez.",
    ]

    return {
        "status": "available",
        "version": MUNDANE_VERSION,
        "method": "mundane_ingress_lunation_eclipse_v1",
        "event_type": event_type,
        "year": year,
        "month": params["month"],
        "location": loc,
        "events_count": len(events_out),
        "events": events_out,
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


def build_mundane_markdown(
    data: dict,
    event_label: str,
    generated_at: str | None = None,
) -> str:
    loc = data["location"]

    fm_lines = [
        "---",
        f'title: "Mundane - {event_label}"',
        'type: "mundane_pack"',
        'source: "western_api_v2_mundane"',
        f'event_type: "{data["event_type"]}"',
        f'year: {data["year"]}',
        f'month: {data["month"] if data["month"] else "null"}',
        f'location_place: "{loc.get("place") or "-"}"',
        f'events_count: {data["events_count"]}',
        f'method: "{data["method"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{MUNDANE_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# Mundane: {event_label}",
        "",
        "## Kullanım Notu",
        "",
        "- Mundane haritalar dünya olayları içindir; verilen konuma göre kurulur.",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Parametreler",
        "",
        f"- Olay tipi: **{data['event_type']}**",
        f"- Yıl: {data['year']}" + (f" / Ay: {data['month']}" if data["month"] else ""),
        f"- Konum: {loc.get('place') or '-'} ({loc['lat']:.4f}, {loc['lon']:.4f})",
        f"- Olay sayısı: {data['events_count']}",
        "",
    ]

    event_sections = []
    for i, ev in enumerate(data["events"], 1):
        cs = ev["chart_summary"]
        title = f"## {i}. {ev['type_tr']}"
        if ev.get("kind"):
            title += f" ({ev['kind']})"
        event_sections.append(title)
        event_sections.append("")
        event_sections.append(f"- UTC an: **{ev['utc_datetime']}**")
        event_sections.append(f"- ASC: {cs['ascendant']} | MC: {cs['midheaven']}")
        event_sections.append("")
        planet_rows = [
            (
                p["name_tr"] or p["id"],
                p["position"],
                f'e{p["house"]}' if p.get("house") else "-",
                "R" if p["retrograde"] else "-",
            )
            for p in cs["planets"]
        ]
        event_sections.append(_md_table(["Gezegen", "Konum", "Ev", "Retro"], planet_rows))
        event_sections.append("")
        if cs["major_aspects"]:
            aspect_rows = [
                (a["from"], a["type"], a["to"], f'{a["orb"]:.2f}°')
                for a in cs["major_aspects"]
            ]
            event_sections.append("**Majör açılar:**")
            event_sections.append("")
            event_sections.append(_md_table(["A", "Açı", "B", "Orb"], aspect_rows))
            event_sections.append("")

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
        *event_sections,
        *limit_section,
        *technical_section,
    ])
