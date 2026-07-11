#!/usr/bin/env python3
"""Western astrology fixed star calculations.

Klasik sabit yıldız kataloğu (28 yıldız: 4 Royal + 14 birinci kademe + 10 ikinci kademe).
Tropikal longitude'da gezegen/angle ↔ yıldız kavuşumları (klasik orb 1°).

Sadece kavuşum yorum gelenektir (Robson, Brady, Ebertin standardı). Diğer açı tipleri
sabit yıldızlarla anlamlı kabul edilmez.

Kullanım:
    - compute_star_positions(jd_ut) → {star_id: longitude}
    - find_star_conjunctions(bodies, jd_ut, orb=1.0) → [{star, body, orb, ...}]

Gereksinim: ephe/sefstars.txt dosyası mevcut olmalı.
"""

from __future__ import annotations

from datetime import datetime
from functools import lru_cache

import swisseph as swe


# ---------------------------------------------------------------------------
# Yıldız kataloğu
# ---------------------------------------------------------------------------
# Her giriş: (star_id, swisseph_name, name_tr, nature_short_tr)
# - star_id: kısa, snake_case (kod içi referans)
# - swisseph_name: swe.fixstar_ut için tam ad veya nomenklatür (sefstars.txt'deki)
# - name_tr: Türkçe yaygın ad
# - nature_short_tr: klasik niteliğin kısa özeti (tek satır, yorum ipucu)


ROYAL_STARS = [
    # 4 Kraliyet Yıldızı (sezonal eksen)
    ("aldebaran",   "Aldebaran",   "Aldebaran (Boğa Gözü)",      "Mars-doğa; cesaret, askeri başarı, ani yükseliş ve düşüş"),
    ("regulus",     "Regulus",     "Regulus (Aslan Kalbi)",       "Jüpiter-Mars doğa; iktidar, soyluluk, intikamdan kaçınma şartlı başarı"),
    ("antares",     "Antares",     "Antares (Akrep Kalbi)",       "Mars-Jüpiter doğa; tutku, mücadele, ani yıkım/dönüşüm"),
    ("fomalhaut",   "Fomalhaut",   "Fomalhaut (Güney Balık)",     "Venüs-Merkür doğa; sanat, idealizm, ahlaki sınav"),
]


PRIMARY_STARS = [
    # 14 birinci kademe
    ("spica",       "Spica",       "Spica (Başak Başağı)",        "Venüs-Mars doğa; nadir bahşedici yıldız, sanat, başarı, koruma"),
    ("algol",       "Algol",       "Algol (Medusa)",              "Satürn-Jüpiter doğa; en kötü ün; şiddet ve kafa kayıpları (klasik)"),
    ("sirius",      "Sirius",      "Sirius (Köpek Yıldızı)",      "Jüpiter-Mars doğa; ün, başarı, koruyucu güç"),
    ("arcturus",    "Arcturus",    "Arcturus (Çoban)",            "Jüpiter-Mars doğa; başarı sanat, yenilik kabul"),
    ("vega",        "Vega",        "Vega (Lir)",                  "Venüs-Merkür doğa; sanat, sihir, idealizm"),
    ("altair",      "Altair",      "Altair (Kartal)",             "Mars-Jüpiter doğa; cüret, askeri yetenek, ani aksilik"),
    ("capella",     "Capella",     "Capella (Keçi)",              "Mars-Merkür doğa; meraklı zeka, askeri/sivil onur"),
    ("procyon",     "Procyon",     "Procyon (Küçük Köpek)",       "Mars-Merkür doğa; hızlı yükseliş, hızlı düşüş"),
    ("rigel",       "Rigel",       "Rigel (Orion ayağı)",         "Jüpiter-Satürn doğa; teknik beceri, dayanıklı başarı"),
    ("betelgeuse",  "Betelgeuse",  "Betelgeuse (Orion omzu)",     "Mars-Merkür doğa; askeri onur, beklenmedik başarı"),
    ("pollux",      "Pollux",      "Pollux (İkizler-güney)",      "Mars doğa; cesur ama acımasız, savaşçı"),
    ("castor",      "Castor",      "Castor (İkizler-kuzey)",      "Merkür doğa; zeka, dil yeteneği, hızlı düşünce"),
    ("polaris",     "Polaris",     "Polaris (Kutup Yıldızı)",     "Satürn-Venüs doğa; kalıtsal, dönüş noktası, miras"),
    ("alcyone",     "Alcyone",     "Alcyone (Pleyad)",            "Ay-Mars doğa; gözyaşı, görme/duyu sorunları, vizyon"),
]


SECONDARY_STARS = [
    # 10 ikinci kademe
    ("deneb_adige", "Deneb Adige", "Deneb (Kuğu)",                "Venüs-Merkür doğa; sanatsal yetenek, idealist"),
    ("mirach",      "Mirach",      "Mirach (Andromeda)",          "Venüs doğa; kişisel cazibe, evlilik"),
    ("alphecca",    "Alphecca",    "Alphecca (Kuzey Tacı)",       "Venüs-Merkür doğa; onur, sanat, mistik eğilim"),
    ("rasalhague",  "Rasalhague",  "Rasalhague (Yılancı)",        "Satürn-Venüs doğa; iyileşme, zehir, mistik"),
    ("markab",      "Markab",      "Markab (Pegasus)",            "Mars-Merkür doğa; tehlike, ani değişim"),
    ("scheat",      "Scheat",      "Scheat (Pegasus)",            "Mars-Merkür doğa; aşırılık, kazalar, suya bağlı sorunlar (klasik)"),
    ("bellatrix",   "Bellatrix",   "Bellatrix (Orion-doğu)",      "Mars-Merkür doğa; askeri onur, ani onur ve düşüş"),
    ("zosma",       "Zosma",       "Zosma (Aslan sırtı)",         "Satürn-Venüs doğa; melankoli, dehşet, kötü duyurma (klasik)"),
    ("toliman",     "Toliman",     "Toliman (Alpha Centauri)",    "Venüs-Jüpiter doğa; dostluk, sosyal başarı"),
    ("achernar",    "Achernar",    "Achernar (Nehir sonu)",       "Jüpiter doğa; başarı, dini/felsefi yönelim"),
]


TERTIARY_STARS = [
    # 32 üçüncü kademe — klasik literatürde sık geçen ek yıldızlar
    ("hamal",        "Hamal",         "Hamal (Koç başı)",            "Mars-Satürn doğa; şiddet, ani saldırı, askeri tema"),
    ("sheratan",     "Sheratan",      "Sheratan (Koç boynuz)",       "Mars-Satürn doğa; tehlike, yaralanma"),
    ("alpheratz",    "Alpheratz",     "Alpheratz (Andromeda başı)",  "Jüpiter-Venüs doğa; bağımsızlık, popülerlik, onur"),
    ("caph",         "Caph",          "Caph (Cassiopeia)",           "Satürn-Venüs doğa; entelektüel, sanatsal"),
    ("schedar",      "Schedar",       "Schedar (Cassiopeia)",        "Satürn-Venüs doğa; ciddi, sabırlı, kalıcı başarı"),
    ("algenib",      "Algenib",       "Algenib (Pegasus köşesi)",    "Mars-Merkür doğa; cüretkâr zeka, ani değişim"),
    ("mirfak",       "Mirfak",        "Mirfak (Perseus)",            "Jüpiter-Satürn doğa; kalıcı güç, dayanıklılık"),
    ("menkar",       "Menkar",        "Menkar (Balina çene)",        "Satürn doğa; hastalık, miras, boğaz/ses sorunları"),
    ("alnilam",      "Alnilam",       "Alnilam (Orion kemeri-orta)", "Jüpiter-Satürn doğa; kısa süreli onur, dikkat"),
    ("mintaka",      "Mintaka",       "Mintaka (Orion kemeri)",      "Satürn-Merkür doğa; iyi şans, dikkatli zeka"),
    ("alhena",       "Alhena",        "Alhena (İkizler ayak)",       "Merkür-Venüs doğa; sanat, ayak yaralanması"),
    ("wasat",        "Wasat",         "Wasat (İkizler orta)",        "Satürn doğa; şiddet, melankoli, kimyasal tehlike"),
    ("acubens",      "Acubens",       "Acubens (Yengeç pence)",      "Satürn-Merkür doğa; sıradan, sabırlı, gizlilik"),
    ("asellus_borealis", "Asellus Borealis", "Asellus Borealis (Yengeç eşek-kuzey)", "Mars-Güneş doğa; askeri, riskli"),
    ("alphard",      "Alphard",       "Alphard (Hidra kalbi)",       "Satürn-Venüs doğa; aşırılık, zehirlenme, melankoli"),
    ("adhafera",     "Adhafera",      "Adhafera (Aslan yelesi)",     "Satürn-Merkür doğa; sahtekarlık, hırsızlık, intihar (klasik kötü)"),
    ("denebola",     "Denebola",      "Denebola (Aslan kuyruğu)",    "Satürn-Venüs doğa; talihsizlik, asalet sonrası düşüş"),
    ("vindemiatrix", "Vindemiatrix",  "Vindemiatrix (Başak)",        "Satürn-Merkür doğa; depresyon, dul kalma, üzüntü (klasik)"),
    ("algorab",      "Algorab",       "Algorab (Karga)",             "Mars-Satürn doğa; yıkım, scavenger, kara büyü (klasik)"),
    ("seginus",      "Seginus",       "Seginus (Çoban omzu)",        "Merkür-Satürn doğa; arkadaş kaybı, ihanet"),
    ("zuben_elgenubi", "Zuben Elgenubi", "Zubenelgenubi (Terazi güney kefe)", "Satürn-Mars doğa; sosyal sorun, hastalık, talihsizlik"),
    ("zuben_eschamali", "Zuben Eschamali", "Zubeneschamali (Terazi kuzey kefe)", "Jüpiter-Merkür doğa; başarı, kalıcı onur"),
    ("unukalhai",    "Unukalhai",     "Unukalhai (Yılan kalbi)",     "Satürn-Mars doğa; kronik hastalık, kazalar"),
    ("dschubba",     "Dschubba",      "Dschubba (Akrep alın)",       "Mars-Satürn doğa; araştırmacı zeka, gizli düşmanlar"),
    ("sabik",        "Sabik",         "Sabik (Yılancı)",             "Satürn-Venüs doğa; çarpık ahlak, ahlaki sınav"),
    ("lesath",       "Lesath",        "Lesath (Akrep iğne)",         "Merkür-Mars doğa; tehlike, kazalar, asit/zehir"),
    ("sargas",       "Sargas",        "Sargas (Akrep)",              "Satürn-Venüs doğa; tehlike, savaş"),
    ("ras_algethi",  "Ras Algethi",   "Ras Algethi (Herkül başı)",   "Venüs-Merkür doğa; mistik güç, sanat"),
    ("nunki",        "Nunki",         "Nunki (Yay)",                 "Jüpiter-Merkür doğa; dürüst, dini eğilim, dolaylı başarı"),
    ("sadalmelik",   "Sadalmelik",    "Sadalmelik (Kova)",           "Satürn-Merkür doğa; ölümlü tehlike, dava"),
    ("sadalsuud",    "Sadalsuud",     "Sadalsuud (Kova)",            "Satürn-Merkür doğa; aile sorunu, talihsizlik"),
    ("diphda",       "Diphda",        "Diphda (Balina kuyruğu)",     "Satürn doğa; kayıp, iftira, ihanet"),
]


STAR_CATALOG = ROYAL_STARS + PRIMARY_STARS + SECONDARY_STARS + TERTIARY_STARS


# Hızlı erişim: id → metadata
STAR_META = {
    sid: {
        "id": sid,
        "swisseph_name": swname,
        "name_tr": name_tr,
        "nature_tr": nature,
        "tier": tier,
    }
    for tier, group in (
        ("royal", ROYAL_STARS),
        ("primary", PRIMARY_STARS),
        ("secondary", SECONDARY_STARS),
        ("tertiary", TERTIARY_STARS),
    )
    for sid, swname, name_tr, nature in group
}


# Klasik kavuşum orb (Robson, Brady)
FIXED_STAR_ORB = 1.0


class FixedStarError(RuntimeError):
    """Fixed star hesaplama hatası (sefstars.txt eksik, isim bulunamadı, vb)."""


# ---------------------------------------------------------------------------
# Yıldız konum hesabı
# ---------------------------------------------------------------------------


def _star_longitude_at(jd_ut: float, swisseph_name: str) -> float | None:
    """Verilen JD'de bir sabit yıldızın tropikal longitude'unu döner.

    swisseph_name eşleşmezse None döner (sefstars.txt'de yok veya farklı yazılmış).
    """
    try:
        values, _retname, _retflags = swe.fixstar_ut(
            swisseph_name, jd_ut, swe.FLG_SWIEPH | swe.FLG_SPEED,
        )
    except Exception:
        return None
    if not values:
        return None
    return float(values[0]) % 360.0


def compute_star_positions(jd_ut: float) -> dict[str, dict]:
    """Tüm kataloğun verilen JD'deki tropikal longitude konumlarını döner.

    Dönüş: {star_id: {"longitude": float, "name_tr": str, "nature_tr": str, "tier": str, ...}}
    sefstars.txt eksikse veya yıldız bulunamazsa o yıldız atlanır.
    """
    out = {}
    for sid, meta in STAR_META.items():
        lon = _star_longitude_at(jd_ut, meta["swisseph_name"])
        if lon is None:
            continue
        out[sid] = {
            **meta,
            "longitude": lon,
        }
    return out


# ---------------------------------------------------------------------------
# Kavuşum tespiti
# ---------------------------------------------------------------------------


def _shortest_separation(a: float, b: float) -> float:
    diff = abs(a - b) % 360.0
    return min(diff, 360.0 - diff)


def find_star_conjunctions(
    bodies: list[dict],
    jd_ut: float,
    orb: float = FIXED_STAR_ORB,
    star_positions: dict[str, dict] | None = None,
) -> list[dict]:
    """Verilen body listesi ↔ sabit yıldız kavuşumlarını döner (orb ≤ orb).

    bodies: her biri {"id": str, "label": str, "longitude": float, "kind": str?}
    Sadece kavuşum (orb cinsinden en yakın 0°) sayılır.

    Dönüş satırı: {body_id, body_label, body_kind, star_id, star_name_tr, star_tier,
                   star_nature_tr, longitude_star, orb}
    """
    if star_positions is None:
        star_positions = compute_star_positions(jd_ut)

    contacts = []
    for body in bodies:
        body_lon = body["longitude"]
        for sid, star in star_positions.items():
            sep = _shortest_separation(body_lon, star["longitude"])
            if sep <= orb:
                contacts.append({
                    "body_id": body["id"],
                    "body_label": body.get("label", body["id"]),
                    "body_kind": body.get("kind", "planet"),
                    "star_id": sid,
                    "star_name_tr": star["name_tr"],
                    "star_tier": star["tier"],
                    "star_nature_tr": star["nature_tr"],
                    "star_longitude": round(star["longitude"], 4),
                    "orb": round(sep, 4),
                })
    contacts.sort(key=lambda c: (c["orb"], c["body_id"]))
    return contacts


# ---------------------------------------------------------------------------
# Chart helper: bodies extraction (chart dict'inden body listesi)
# ---------------------------------------------------------------------------


def _bodies_from_chart(chart: dict, include_angles: bool = True) -> list[dict]:
    """Chart dict'inden (calculate_core_chart çıktısı) standart body listesi üret."""
    bodies = []
    for planet in chart.get("planets", {}).get("items", []):
        bodies.append({
            "id": planet["id"],
            "label": planet.get("name_tr") or planet["id"],
            "longitude": planet["longitude"],
            "kind": "planet",
        })
    for node in chart.get("nodes", {}).get("items", []):
        bodies.append({
            "id": node["id"],
            "label": node.get("name_tr") or node["id"],
            "longitude": node["longitude"],
            "kind": "node",
        })
    if include_angles:
        for angle_id in ("ascendant", "descendant", "midheaven", "imum_coeli"):
            a = chart.get("angles", {}).get(angle_id)
            if not a:
                continue
            bodies.append({
                "id": angle_id,
                "label": a.get("name_tr") or angle_id,
                "longitude": a["longitude"],
                "kind": "angle",
            })
    return bodies


def compute_chart_star_contacts(
    chart: dict,
    orb: float = FIXED_STAR_ORB,
    include_angles: bool = True,
) -> list[dict]:
    """Bir chart için (natal veya SR) tüm body ↔ sabit yıldız kavuşumlarını döner.

    JD önce chart['birth']['julian_day_ut'] alanından, yoksa
    chart['birth']['utc_datetime'] ISO string'inden hesaplanır.
    """
    birth = chart.get("birth") or {}
    jd_ut = birth.get("julian_day_ut")
    if jd_ut is None:
        utc_iso = birth.get("utc_datetime")
        if not utc_iso:
            raise FixedStarError(
                "chart['birth']['julian_day_ut'] veya ['utc_datetime'] eksik; "
                "sabit yıldız hesabı yapılamaz."
            )
        try:
            utc_dt = datetime.fromisoformat(utc_iso.replace("Z", "+00:00"))
        except ValueError as exc:
            raise FixedStarError(
                f"chart['birth']['utc_datetime'] parse edilemedi: {utc_iso}"
            ) from exc
        # Lazy import to avoid circular dependency with western_chart
        from .western_chart import _julian_day
        jd_ut = _julian_day(utc_dt)

    bodies = _bodies_from_chart(chart, include_angles=include_angles)
    return find_star_conjunctions(bodies, jd_ut, orb=orb)


# ---------------------------------------------------------------------------
# Sefstars varlık kontrolü
# ---------------------------------------------------------------------------


def is_available() -> bool:
    """sefstars.txt erişilebilir mi (basit test: bir yıldız konumu alınabiliyor mu)."""
    try:
        # Sirius klasik, sefstars.txt'de mutlaka olur
        values, _retname, _retflags = swe.fixstar_ut(
            "Sirius", 2451545.0, swe.FLG_SWIEPH,
        )
        return bool(values)
    except Exception:
        return False
