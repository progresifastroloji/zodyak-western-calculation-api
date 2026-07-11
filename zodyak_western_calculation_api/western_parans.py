#!/usr/bin/env python3
"""Parans (sabit yıldız) calculation — Brady's Visual Astrology style.

Paran: iki cisim (gezegen-yıldız veya gezegen-gezegen) doğum gününde
dört açısal noktanın (rise / set / culminate / anti-culminate) birinden
**eşzamanlı** geçerse oluşur (default orb 30 dakika).

Hellenistik çizgi + Bernadette Brady'nin Visual Astrology yaklaşımıdır.

Her cisim doğum gününde tipik olarak 4 angle'dan birer kez geçer
(rising, culminating, setting, anti-culminating). Bu modül 10 gezegen
+ ~36 büyük sabit yıldız için bu 4 zaman damgasını swe.rise_trans ile
hesaplar; sonra cisim çiftleri arasında eşzamanlılık (zaman farkı ≤ orb)
arar.

v1 kapsamı:
- 10 klasik gezegen (Sun-Pluto)
- ~36 paran-katılımcı sabit yıldız (Brady'nin temel listesi)
- 4 angle (rise, culminate, set, anti-culminate)
- Default orb: 30 dakika; yapılandırılabilir (15-60 dk)
- Paran tipleri: planet-star, star-planet, planet-planet

v2'ye:
- Heliacal rising/setting (Güneş ile birlikte doğan/batan)
- Latitude-based paran listing (Brady'nin "paran latitudes")
- Asteroid parans (Ceres/Pallas/Juno/Vesta dahil)

Bu modül mevcut hiçbir modülü değiştirmez; sadece western_chart
yardımcılarını ve swisseph rise_trans/fixstar_ut fonksiyonlarını kullanır.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

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


PARANS_VERSION = "1.0.0"

# Default paran orb (dakika); yapılandırılabilir
DEFAULT_PARAN_ORB_MINUTES = 30.0
MIN_PARAN_ORB_MINUTES = 5.0
MAX_PARAN_ORB_MINUTES = 60.0


# 10 gezegen — paran katılımcısı
PARAN_PLANETS: list[tuple[int, str, str]] = [
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

# Brady'nin temel sabit yıldız listesi (paran için en sık kullanılan ~36 yıldız)
# sefstars.txt adı (Swiss Ephemeris standardı), id, Türkçe ad, takım yıldızı
PARAN_FIXED_STARS: list[tuple[str, str, str, str]] = [
    ("Achernar", "achernar", "Achernar", "Eridanus"),
    ("Acrux", "acrux", "Acrux", "Crux"),
    ("Adhara", "adhara", "Adhara", "Canis Major"),
    ("Aldebaran", "aldebaran", "Aldebaran", "Taurus"),
    ("Algol", "algol", "Algol", "Perseus"),
    ("Alpheratz", "alpheratz", "Alpheratz", "Andromeda"),
    ("Altair", "altair", "Altair", "Aquila"),
    ("Antares", "antares", "Antares", "Scorpius"),
    ("Arcturus", "arcturus", "Arcturus", "Boötes"),
    ("Bellatrix", "bellatrix", "Bellatrix", "Orion"),
    ("Betelgeuse", "betelgeuse", "Betelgeuse", "Orion"),
    ("Canopus", "canopus", "Canopus", "Carina"),
    ("Capella", "capella", "Capella", "Auriga"),
    ("Castor", "castor", "Castor", "Gemini"),
    ("Deneb", "deneb", "Deneb", "Cygnus"),
    ("Denebola", "denebola", "Denebola", "Leo"),
    ("Diphda", "diphda", "Diphda", "Cetus"),
    ("Dubhe", "dubhe", "Dubhe", "Ursa Major"),
    ("El Nath", "el_nath", "El Nath", "Taurus"),
    ("Fomalhaut", "fomalhaut", "Fomalhaut", "Piscis Austrinus"),
    ("Hamal", "hamal", "Hamal", "Aries"),
    ("Markab", "markab", "Markab", "Pegasus"),
    ("Menkar", "menkar", "Menkar", "Cetus"),
    ("Mirach", "mirach", "Mirach", "Andromeda"),
    ("Mirfak", "mirfak", "Mirfak", "Perseus"),
    ("Polaris", "polaris", "Polaris", "Ursa Minor"),
    ("Pollux", "pollux", "Pollux", "Gemini"),
    ("Procyon", "procyon", "Procyon", "Canis Minor"),
    ("Regulus", "regulus", "Regulus", "Leo"),
    ("Rigel", "rigel", "Rigel", "Orion"),
    ("Scheat", "scheat", "Scheat", "Pegasus"),
    ("Schedar", "schedar", "Schedar", "Cassiopeia"),
    ("Sirius", "sirius", "Sirius", "Canis Major"),
    ("Spica", "spica", "Spica", "Virgo"),
    ("Vega", "vega", "Vega", "Lyra"),
    ("Alphecca", "alphecca", "Alphecca", "Corona Borealis"),
]

# Angle event tipleri
ANGLE_EVENTS = [
    ("rise", swe.CALC_RISE, "Doğuş", "ASC"),
    ("culminate", swe.CALC_MTRANSIT, "Doruk", "MC"),
    ("set", swe.CALC_SET, "Batış", "DSC"),
    ("anti_culminate", swe.CALC_ITRANSIT, "Yer Altı Doruğu", "IC"),
]
ANGLE_TR = {e[0]: e[2] for e in ANGLE_EVENTS}
ANGLE_LABEL = {e[0]: e[3] for e in ANGLE_EVENTS}


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class ParansInputError(ValueError):
    """Parans için geçersiz input."""


class ParansCalculationError(RuntimeError):
    """Parans hesaplama hatası."""


# ---------------------------------------------------------------------------
# Yardımcılar
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> tuple[float, list[str]]:
    if not isinstance(payload, dict):
        raise ParansInputError("JSON gövdesi nesne olmalıdır")
    p = payload.get("parans") or {}
    if not isinstance(p, dict):
        raise ParansInputError("parans alanı nesne olmalıdır")

    try:
        orb_minutes = float(p.get("orb_minutes") or DEFAULT_PARAN_ORB_MINUTES)
    except (TypeError, ValueError) as exc:
        raise ParansInputError("parans.orb_minutes sayı olmalıdır") from exc
    if not MIN_PARAN_ORB_MINUTES <= orb_minutes <= MAX_PARAN_ORB_MINUTES:
        raise ParansInputError(
            f"parans.orb_minutes {MIN_PARAN_ORB_MINUTES}-{MAX_PARAN_ORB_MINUTES} "
            f"aralığında olmalıdır"
        )

    star_filter = p.get("stars")
    if star_filter is not None and not isinstance(star_filter, list):
        raise ParansInputError("parans.stars liste olmalıdır")
    star_filter_ids = (
        [str(s).lower().strip() for s in star_filter] if star_filter else []
    )

    return orb_minutes, star_filter_ids


def _planet_events(
    jd_search_start: float,
    planet_id: int,
    geopos: tuple[float, float, float],
    window_days: float = 1.5,
) -> list[dict]:
    """Bir gezegenin 4 angle geçiş zamanlarını döner."""
    events = []
    for event_id, code, _tr, _label in ANGLE_EVENTS:
        try:
            retval, tret = swe.rise_trans(
                jd_search_start,
                planet_id,
                code,
                geopos,
                0.0,
                0.0,
                swe.FLG_SWIEPH,
            )
        except swe.Error:
            continue
        if retval < 0:
            continue
        if tret[0] <= 0:
            continue
        if tret[0] > jd_search_start + window_days:
            continue
        events.append({
            "event": event_id,
            "jd_utc": tret[0],
        })
    return events


def _star_events(
    jd_search_start: float,
    star_name: str,
    geopos: tuple[float, float, float],
    window_days: float = 1.5,
) -> list[dict]:
    """Bir sabit yıldızın 4 angle geçiş zamanlarını döner."""
    events = []
    for event_id, code, _tr, _label in ANGLE_EVENTS:
        try:
            retval, tret = swe.rise_trans(
                jd_search_start,
                star_name,
                code,
                geopos,
                0.0,
                0.0,
                swe.FLG_SWIEPH,
            )
        except swe.Error:
            continue
        if retval < 0:
            continue
        if tret[0] <= 0:
            continue
        if tret[0] > jd_search_start + window_days:
            continue
        events.append({
            "event": event_id,
            "jd_utc": tret[0],
        })
    return events


def _jd_to_iso(jd: float) -> str:
    """JD UT → ISO-8601 UTC string."""
    year, month, day, hour_decimal = swe.revjul(jd)
    hours = int(hour_decimal)
    minutes_float = (hour_decimal - hours) * 60.0
    minutes = int(minutes_float)
    seconds = int((minutes_float - minutes) * 60.0)
    return f"{year:04d}-{month:02d}-{day:02d}T{hours:02d}:{minutes:02d}:{seconds:02d}Z"


def _star_available(name: str) -> bool:
    """Yıldız sefstars.txt'de bulunup hesaplanabilir mi?"""
    try:
        # swe.fixstar_ut bir JD ile çağrılır; JD2000 yeterli kontrol
        swe.fixstar_ut(name, 2451545.0, swe.FLG_SWIEPH)
        return True
    except swe.Error:
        return False


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_parans(payload: dict, chart: dict | None = None) -> dict:
    """Parans hesap paketi."""

    orb_minutes, star_filter_ids = _validate_input(payload)
    natal_chart = chart or calculate_core_chart(payload)

    birth = natal_chart["birth"]
    birth_utc = datetime.fromisoformat(
        birth["utc_datetime"].replace("Z", "+00:00")
    )
    if birth_utc.tzinfo is None:
        birth_utc = birth_utc.replace(tzinfo=timezone.utc)

    lat = float(birth["latitude"])
    lon = float(birth["longitude"])
    geopos = (lon, lat, 0.0)

    # 24 saatlik pencere: doğumdan 12 saat önce → 12 saat sonra
    jd_birth = _julian_day(birth_utc)
    jd_search_start = jd_birth - 0.5
    jd_search_end = jd_birth + 0.5
    orb_jd = orb_minutes / (24.0 * 60.0)  # gün cinsinden

    # Sabit yıldızları filtrele
    if star_filter_ids:
        active_stars = [
            row for row in PARAN_FIXED_STARS
            if row[1] in star_filter_ids
        ]
    else:
        active_stars = list(PARAN_FIXED_STARS)

    # Sabit yıldız availability ön kontrolü (sefstars.txt yüklü değilse hata
    # vermek yerine usulüne uygun atla)
    skipped_stars = []
    usable_stars = []
    for star_row in active_stars:
        sefstars_name, star_id, _name_tr, _const = star_row
        if _star_available(sefstars_name):
            usable_stars.append(star_row)
        else:
            skipped_stars.append({
                "star_id": star_id,
                "sefstars_name": sefstars_name,
                "reason": "not_found_in_sefstars",
            })

    # Cisim event'leri (cisim_id, kind, name_tr, events: [...])
    bodies: list[dict] = []

    for planet_id, body_id, name_tr in PARAN_PLANETS:
        events = _planet_events(jd_search_start, planet_id, geopos)
        # Pencerede gerçekleşenleri tut (search_end'i geçenleri at)
        events = [e for e in events if e["jd_utc"] <= jd_search_end]
        bodies.append({
            "id": body_id,
            "kind": "planet",
            "name_tr": name_tr,
            "events": events,
        })

    for sefstars_name, star_id, name_tr, constellation in usable_stars:
        events = _star_events(jd_search_start, sefstars_name, geopos)
        events = [e for e in events if e["jd_utc"] <= jd_search_end]
        bodies.append({
            "id": star_id,
            "kind": "star",
            "name_tr": name_tr,
            "constellation": constellation,
            "sefstars_name": sefstars_name,
            "events": events,
        })

    # Tüm event'leri zaman damgasıyla ISO formatlı tabloya çevir
    for body in bodies:
        for e in body["events"]:
            e["utc_iso"] = _jd_to_iso(e["jd_utc"])
            e["angle_tr"] = ANGLE_TR.get(e["event"], e["event"])
            e["angle_label"] = ANGLE_LABEL.get(e["event"], e["event"])

    # Paran tespiti: tüm cisim çiftleri × tüm event çiftleri
    parans_found: list[dict] = []
    for i in range(len(bodies)):
        body_a = bodies[i]
        for j in range(i + 1, len(bodies)):
            body_b = bodies[j]
            for ea in body_a["events"]:
                for eb in body_b["events"]:
                    diff_jd = abs(ea["jd_utc"] - eb["jd_utc"])
                    if diff_jd <= orb_jd:
                        diff_minutes = diff_jd * 24.0 * 60.0
                        # Pair label: planet-planet | planet-star | star-star
                        pair_kind = "_".join(sorted([body_a["kind"], body_b["kind"]]))
                        # Doğum anına yakınlık (mutlak fark)
                        center_jd = (ea["jd_utc"] + eb["jd_utc"]) / 2.0
                        offset_minutes_from_birth = (
                            (center_jd - jd_birth) * 24.0 * 60.0
                        )
                        parans_found.append({
                            "body_a": body_a["id"],
                            "body_a_tr": body_a["name_tr"],
                            "body_a_kind": body_a["kind"],
                            "body_a_event": ea["event"],
                            "body_a_event_tr": ea["angle_tr"],
                            "body_a_angle": ea["angle_label"],
                            "body_a_utc": ea["utc_iso"],
                            "body_b": body_b["id"],
                            "body_b_tr": body_b["name_tr"],
                            "body_b_kind": body_b["kind"],
                            "body_b_event": eb["event"],
                            "body_b_event_tr": eb["angle_tr"],
                            "body_b_angle": eb["angle_label"],
                            "body_b_utc": eb["utc_iso"],
                            "orb_minutes": round(diff_minutes, 4),
                            "pair_kind": pair_kind,
                            "center_utc": _jd_to_iso(center_jd),
                            "offset_from_birth_minutes": round(
                                offset_minutes_from_birth, 4
                            ),
                        })

    # Sıralama: orb küçükten büyüğe
    parans_found.sort(key=lambda r: r["orb_minutes"])

    # Doğum anına en yakın (mutlak offset minimum) paran
    nearest_to_birth = None
    if parans_found:
        nearest_to_birth = min(
            parans_found,
            key=lambda r: abs(r["offset_from_birth_minutes"]),
        )

    natal_summary = {
        "birth_date": birth["date"],
        "birth_time": birth["time"],
        "birth_utc": birth["utc_datetime"],
        "latitude": lat,
        "longitude": lon,
        "house_system": natal_chart["meta"]["house_system"],
    }

    limitations = [
        "Parans 24 saatlik doğum günü penceresinde hesaplanır; pencere dışı eşzamanlılıklar listelenmez.",
        "Heliacal rising/setting (Güneş'le doğan/batan) v1'de yoktur.",
        "Latitude-based paran katmanları (Brady'nin paran latitudes) v1'de yoktur.",
        "Asteroid (Ceres/Pallas/Juno/Vesta) parans v1'de yoktur.",
        f"Default orb {DEFAULT_PARAN_ORB_MINUTES:.0f} dakika (Brady standardı). 5-60 dk arası yapılandırılabilir.",
    ]
    time_confidence = natal_chart["data_quality"].get("birth_time_confidence")
    if time_confidence in {"low", "unknown"}:
        limitations.append(
            "Doğum saati güveni düşük; offset_from_birth değerleri ciddi belirsizlik taşır. "
            "Paran çiftleri yine geçerli (saat günü kaydırmadıkça)."
        )
    if skipped_stars:
        limitations.append(
            f"sefstars.txt'de bulunamayan yıldız sayısı: {len(skipped_stars)}. "
            "Bu yıldızlar hesap dışı bırakıldı."
        )

    return {
        "status": "available",
        "version": PARANS_VERSION,
        "method": "parans_brady_visual_astrology_v1",
        "orb_minutes": orb_minutes,
        "search_window": {
            "start_utc": _jd_to_iso(jd_search_start),
            "end_utc": _jd_to_iso(jd_search_end),
            "birth_utc": birth["utc_datetime"],
        },
        "natal_summary": natal_summary,
        "planets_count": len(PARAN_PLANETS),
        "stars_total": len(active_stars),
        "stars_usable": len(usable_stars),
        "stars_skipped": skipped_stars,
        "events_summary": {
            "total_planet_events": sum(
                len(b["events"]) for b in bodies if b["kind"] == "planet"
            ),
            "total_star_events": sum(
                len(b["events"]) for b in bodies if b["kind"] == "star"
            ),
        },
        "parans_count": len(parans_found),
        "parans": parans_found,
        "nearest_to_birth": nearest_to_birth,
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


def build_parans_markdown(
    data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    natal_summary = data["natal_summary"]
    parans = data["parans"]
    nearest = data["nearest_to_birth"]
    window = data["search_window"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Parans"',
        'type: "parans_pack"',
        'source: "western_api_v2_parans"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'method: "{data["method"]}"',
        f'orb_minutes: {data["orb_minutes"]}',
        f'parans_count: {data["parans_count"]}',
        f'planets_count: {data["planets_count"]}',
        f'stars_usable: {data["stars_usable"]}',
        f'stars_skipped: {len(data["stars_skipped"])}',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{PARANS_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Parans",
        "",
        "## Kullanım Notu",
        "",
        "- Parans Brady'nin Visual Astrology katmanıdır; doğum günü içinde iki cismin angle geçişlerinin eşzamanlı olması.",
        f"- Default orb {data['orb_minutes']:.0f} dakika.",
        "- Angle setleri: Rise (ASC), Culminate (MC), Set (DSC), Anti-culminate (IC).",
        "- Cisim çiftleri planet-planet, planet-star, star-star olabilir.",
        "- 'offset_from_birth_minutes' paran merkez anının doğum anından farkıdır (pozitif = sonra, negatif = önce).",
        "- Yorum içermez; bu bir veri paketidir.",
        "",
        "## Özet",
        "",
        f"- Doğum: {natal_summary['birth_date']} {natal_summary['birth_time']} ({natal_summary['birth_utc']})",
        f"- Konum: lat={natal_summary['latitude']:.4f}, lon={natal_summary['longitude']:.4f}",
        f"- Tarama penceresi: {window['start_utc']} → {window['end_utc']}",
        f"- Gezegen sayısı: {data['planets_count']}",
        f"- Kullanılabilir yıldız: {data['stars_usable']}",
        f"- Atlanan yıldız (sefstars'ta yok): {len(data['stars_skipped'])}",
        f"- Toplam paran sayısı: **{data['parans_count']}**",
        "",
    ]

    if nearest:
        overview.extend([
            "## Doğum Anına En Yakın Paran",
            "",
            f"- **{nearest['body_a_tr']}** ({nearest['body_a_angle']}) "
            f"+ **{nearest['body_b_tr']}** ({nearest['body_b_angle']})",
            f"- Orb: {nearest['orb_minutes']:.2f} dakika",
            f"- Merkez anı (UTC): {nearest['center_utc']}",
            f"- Doğumdan offset: {nearest['offset_from_birth_minutes']:.2f} dakika",
            f"- Tip: {nearest['pair_kind']}",
            "",
        ])

    if parans:
        rows = []
        for p in parans:
            rows.append((
                f'{p["body_a_tr"]} ({p["body_a_angle"]})',
                f'{p["body_b_tr"]} ({p["body_b_angle"]})',
                f'{p["orb_minutes"]:.2f}',
                f'{p["offset_from_birth_minutes"]:+.1f}',
                p["pair_kind"],
                p["center_utc"],
            ))
        parans_table = _md_table(
            ["Cisim A", "Cisim B", "Orb (dk)", "Doğum Offset (dk)", "Tip", "Merkez UTC"],
            rows,
        )
    else:
        parans_table = (
            "_Doğum günü penceresinde, verilen orb içinde paran tespit edilmedi._"
        )

    parans_section = [
        "## Tüm Paranlar (Orb İçinde, Orb'a Göre Sıralı)",
        "",
        parans_table,
        "",
    ]

    if data["stars_skipped"]:
        skipped_rows = [
            (s["star_id"], s["sefstars_name"], s["reason"])
            for s in data["stars_skipped"]
        ]
        skipped_section = [
            "## Atlanan Yıldızlar",
            "",
            _md_table(
                ["Star ID", "sefstars.txt Adı", "Sebep"],
                skipped_rows,
            ),
            "",
        ]
    else:
        skipped_section = []

    limit_section = [
        "## Sınırlamalar",
        "",
        *[f"- {item}" for item in data.get("limitations", [])],
        "",
    ]

    technical_section = [
        "## Teknik Kaynak Veri",
        "",
        "Aşağıdaki JSON tüm paran datasının makine-okunur kopyasıdır.",
        "",
        "```json",
        json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True),
        "```",
        "",
    ]

    return "\n".join([
        *fm_lines,
        *overview,
        *parans_section,
        *skipped_section,
        *limit_section,
        *technical_section,
    ])
