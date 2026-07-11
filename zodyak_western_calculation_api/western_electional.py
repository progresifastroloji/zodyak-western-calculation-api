#!/usr/bin/env python3
"""Electional astrology (yer-zaman seçimi) calculations.

Verilen amaç + zaman penceresi + konum için aday anlar taranır ve
klasik electional kriterlerine göre skorlanır. En iyi N aday döner.

Skor kriterleri (klasik pratik):
- Moon durumu: void of course değil (+), combust değil (+), dignified (+)
- Amaç evinin yöneticisi: retro değil (+), combust değil (+), dignified (+)
- Doğal significator (amaca göre): dignified (+), retro değil (+)
- Malefic'ler (Mars/Saturn) angular evlerde değil (+)
- Mercury retro değil (kontrat/iletişim amaçları için kritik)
- Benefic (Venüs/Jüpiter) ASC veya MC'de (+)

Sınırlar: pencere maks 60 gün, adım min 5 dk (tarama yükü kontrolü).

Bu bir veri paketidir; nihai seçim danışmana aittir.
"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from .western_chart import (
    ChartCalculationError,
    ChartInputError,
    _shortest_separation,
    calculate_core_chart,
)


# ---------------------------------------------------------------------------
# Sabitler
# ---------------------------------------------------------------------------


ELECTIONAL_VERSION = "1.0.0"

MAX_WINDOW_DAYS = 60
MIN_STEP_MINUTES = 5
DEFAULT_STEP_MINUTES = 15
DEFAULT_TOP_N = 5
MAX_TOP_N = 20

# Amaç → hedef ev + doğal significator
PURPOSE_CONFIG = {
    "marriage": {"house": 7, "significator": "venus", "tr": "Evlilik"},
    "business_start": {"house": 10, "significator": "mercury", "tr": "İş kuruluşu"},
    "contract": {"house": 3, "significator": "mercury", "tr": "Sözleşme"},
    "travel": {"house": 9, "significator": "jupiter", "tr": "Yolculuk"},
    "surgery": {"house": 6, "significator": "mars", "tr": "Ameliyat"},
    "moving_home": {"house": 4, "significator": "moon", "tr": "Taşınma"},
    "education_start": {"house": 9, "significator": "jupiter", "tr": "Eğitim başlangıcı"},
    "financial_investment": {"house": 2, "significator": "jupiter", "tr": "Yatırım"},
    "lawsuit_filing": {"house": 7, "significator": "saturn", "tr": "Dava açma"},
    "job_application": {"house": 10, "significator": "sun", "tr": "İş başvurusu"},
    "launch_product": {"house": 10, "significator": "mercury", "tr": "Ürün lansmanı"},
    "buy_property": {"house": 4, "significator": "saturn", "tr": "Gayrimenkul alımı"},
    "general": {"house": 1, "significator": "moon", "tr": "Genel"},
}

CLASSICAL_RULERSHIP = {
    "aries": "mars", "taurus": "venus", "gemini": "mercury",
    "cancer": "moon", "leo": "sun", "virgo": "mercury",
    "libra": "venus", "scorpio": "mars", "sagittarius": "jupiter",
    "capricorn": "saturn", "aquarius": "saturn", "pisces": "jupiter",
}
EXALTATION = {
    "aries": "sun", "taurus": "moon", "cancer": "jupiter",
    "virgo": "mercury", "libra": "saturn", "capricorn": "mars",
    "pisces": "venus",
}
DETRIMENT = {
    "aries": "venus", "taurus": "mars", "gemini": "jupiter",
    "cancer": "saturn", "leo": "saturn", "virgo": "jupiter",
    "libra": "mars", "scorpio": "venus", "sagittarius": "mercury",
    "capricorn": "moon", "aquarius": "sun", "pisces": "mercury",
}
FALL = {
    "aries": "saturn", "cancer": "mars", "libra": "sun",
    "capricorn": "jupiter", "scorpio": "moon", "virgo": "venus",
    "pisces": "mercury",
}

ANGULAR_HOUSES = {1, 4, 7, 10}
COMBUST_ORB = 8.5
MALEFICS = ("mars", "saturn")
BENEFICS = ("venus", "jupiter")


# ---------------------------------------------------------------------------
# Hata sınıfları
# ---------------------------------------------------------------------------


class ElectionalInputError(ValueError):
    """Electional için geçersiz input."""


class ElectionalCalculationError(RuntimeError):
    """Electional hesaplama hatası."""


# ---------------------------------------------------------------------------
# Input doğrulama
# ---------------------------------------------------------------------------


def _validate_input(payload: dict) -> dict:
    if not isinstance(payload, dict):
        raise ElectionalInputError("JSON gövdesi nesne olmalıdır")
    e = payload.get("electional") or {}
    if not isinstance(e, dict):
        raise ElectionalInputError("electional alanı nesne olmalıdır")

    purpose = e.get("purpose")
    if not purpose or purpose not in PURPOSE_CONFIG:
        raise ElectionalInputError(
            f"electional.purpose zorunlu ve geçerli olmalı. "
            f"Seçenekler: {', '.join(sorted(PURPOSE_CONFIG))}"
        )

    try:
        window_start = datetime.fromisoformat(
            str(e.get("window_start")).replace("Z", "+00:00")
        )
        window_end = datetime.fromisoformat(
            str(e.get("window_end")).replace("Z", "+00:00")
        )
    except (ValueError, TypeError) as exc:
        raise ElectionalInputError(
            "electional.window_start ve window_end ISO-8601 olmalıdır "
            "(örn 2026-07-01T00:00:00Z)"
        ) from exc
    if window_start.tzinfo is None:
        window_start = window_start.replace(tzinfo=timezone.utc)
    if window_end.tzinfo is None:
        window_end = window_end.replace(tzinfo=timezone.utc)
    window_start = window_start.astimezone(timezone.utc)
    window_end = window_end.astimezone(timezone.utc)

    if window_end <= window_start:
        raise ElectionalInputError("window_end, window_start'tan sonra olmalıdır")
    window_days = (window_end - window_start).total_seconds() / 86400.0
    if window_days > MAX_WINDOW_DAYS:
        raise ElectionalInputError(
            f"Pencere en fazla {MAX_WINDOW_DAYS} gün olabilir (verilen: {window_days:.1f})"
        )

    try:
        step_minutes = int(e.get("step_minutes") or DEFAULT_STEP_MINUTES)
    except (TypeError, ValueError) as exc:
        raise ElectionalInputError("electional.step_minutes tam sayı olmalıdır") from exc
    if step_minutes < MIN_STEP_MINUTES:
        raise ElectionalInputError(
            f"step_minutes en az {MIN_STEP_MINUTES} olmalıdır"
        )

    loc = e.get("location") or {}
    if not isinstance(loc, dict) or "lat" not in loc or "lon" not in loc:
        raise ElectionalInputError("electional.location.lat ve lon zorunludur")
    tz_id = loc.get("timezone_id") or "UTC"
    try:
        ZoneInfo(str(tz_id))
    except ZoneInfoNotFoundError as exc:
        raise ElectionalInputError(f"Geçersiz timezone_id: {tz_id}") from exc

    try:
        top_n = int(e.get("top_n") or DEFAULT_TOP_N)
    except (TypeError, ValueError) as exc:
        raise ElectionalInputError("electional.top_n tam sayı olmalıdır") from exc
    top_n = max(1, min(top_n, MAX_TOP_N))

    return {
        "purpose": purpose,
        "window_start": window_start,
        "window_end": window_end,
        "step_minutes": step_minutes,
        "location": {
            "lat": float(loc["lat"]),
            "lon": float(loc["lon"]),
            "timezone_id": str(tz_id),
            "place": loc.get("place"),
        },
        "top_n": top_n,
    }


# ---------------------------------------------------------------------------
# Skorlama
# ---------------------------------------------------------------------------


def _planet_by_id(chart: dict, planet_id: str) -> dict | None:
    for p in chart["planets"]["items"]:
        if p["id"] == planet_id:
            return p
    return None


def _sign_id_of(planet: dict) -> str:
    return (planet.get("sign") or "").lower()


def _dignity_score(planet: dict) -> tuple[float, list[str]]:
    """Essential dignity puanı: domicile +2, exalt +1.5, detriment -1.5, fall -2."""
    sign_id = _sign_id_of(planet)
    pid = planet["id"]
    score = 0.0
    notes = []
    if CLASSICAL_RULERSHIP.get(sign_id) == pid:
        score += 2.0
        notes.append("domicile")
    if EXALTATION.get(sign_id) == pid:
        score += 1.5
        notes.append("exaltation")
    if DETRIMENT.get(sign_id) == pid:
        score -= 1.5
        notes.append("detriment")
    if FALL.get(sign_id) == pid:
        score -= 2.0
        notes.append("fall")
    return score, notes


def _score_candidate(chart: dict, purpose_config: dict) -> dict:
    """Bir aday anın electional skoru."""
    score = 0.0
    factors = []

    moon = _planet_by_id(chart, "moon")
    sun = _planet_by_id(chart, "sun")
    mercury = _planet_by_id(chart, "mercury")

    # 1) Moon durumu
    if moon:
        d_score, d_notes = _dignity_score(moon)
        score += d_score
        if d_notes:
            factors.append(f"Moon {'/'.join(d_notes)} ({d_score:+.1f})")
        if sun:
            sep = _shortest_separation(moon["longitude"], sun["longitude"])
            if sep <= COMBUST_ORB:
                score -= 2.0
                factors.append("Moon combust (-2.0)")
        # Geç derece (29°+) — Moon "at the bendings" değil ama VoC yakını riskli
        moon_deg_in_sign = moon["longitude"] % 30.0
        if moon_deg_in_sign >= 29.0:
            score -= 1.5
            factors.append("Moon 29° (anaretik) (-1.5)")

    # 2) Amaç evinin yöneticisi
    target_house = purpose_config["house"]
    cusp = chart["houses"]["items"][target_house - 1]
    cusp_sign = (cusp.get("sign") or "").lower()
    ruler_id = CLASSICAL_RULERSHIP.get(cusp_sign)
    ruler = _planet_by_id(chart, ruler_id) if ruler_id else None
    if ruler:
        d_score, d_notes = _dignity_score(ruler)
        score += d_score * 0.8
        if d_notes:
            factors.append(f"e{target_house} ruler {ruler_id} {'/'.join(d_notes)} ({d_score * 0.8:+.1f})")
        if ruler.get("retrograde"):
            score -= 1.5
            factors.append(f"e{target_house} ruler {ruler_id} retro (-1.5)")
        if sun and ruler["id"] != "sun":
            sep = _shortest_separation(ruler["longitude"], sun["longitude"])
            if sep <= COMBUST_ORB:
                score -= 1.5
                factors.append(f"e{target_house} ruler combust (-1.5)")

    # 3) Doğal significator
    sig_id = purpose_config["significator"]
    significator = _planet_by_id(chart, sig_id)
    if significator:
        d_score, d_notes = _dignity_score(significator)
        score += d_score * 0.6
        if d_notes:
            factors.append(f"Significator {sig_id} {'/'.join(d_notes)} ({d_score * 0.6:+.1f})")
        if significator.get("retrograde"):
            score -= 1.2
            factors.append(f"Significator {sig_id} retro (-1.2)")

    # 4) Malefic'ler angular evlerde mi
    for malefic_id in MALEFICS:
        malefic = _planet_by_id(chart, malefic_id)
        if malefic and malefic.get("house") in ANGULAR_HOUSES:
            score -= 1.0
            factors.append(f"{malefic_id} angular e{malefic['house']} (-1.0)")

    # 5) Benefic'ler ASC/MC'de mi
    for benefic_id in BENEFICS:
        benefic = _planet_by_id(chart, benefic_id)
        if benefic and benefic.get("house") in (1, 10):
            score += 1.5
            factors.append(f"{benefic_id} e{benefic['house']} (+1.5)")

    # 6) Mercury retro (evrensel ceza; kontrat/iletişim için ekstra)
    if mercury and mercury.get("retrograde"):
        penalty = 2.0 if purpose_config["significator"] == "mercury" else 1.0
        score -= penalty
        factors.append(f"Mercury retro (-{penalty:.1f})")

    return {"score": round(score, 2), "factors": factors}


# ---------------------------------------------------------------------------
# Ana hesap
# ---------------------------------------------------------------------------


def calculate_electional(payload: dict) -> dict:
    """Electional tarama + skorlama."""

    params = _validate_input(payload)
    purpose_config = PURPOSE_CONFIG[params["purpose"]]
    loc = params["location"]
    options = payload.get("options") or {}

    candidates = []
    current = params["window_start"]
    step = timedelta(minutes=params["step_minutes"])

    while current <= params["window_end"]:
        chart_payload = {
            "birth": {
                "year": current.year,
                "month": current.month,
                "day": current.day,
                "hour": current.hour,
                "minute": current.minute,
                "second": current.second,
                "lat": loc["lat"],
                "lon": loc["lon"],
                "timezone_id": "UTC",
                "utc": True,
                "time_confidence": "high",
            },
            "options": options,
        }
        try:
            chart = calculate_core_chart(chart_payload)
        except (ChartInputError, ChartCalculationError):
            current += step
            continue

        result = _score_candidate(chart, purpose_config)
        asc = chart["angles"]["ascendant"]
        moon = _planet_by_id(chart, "moon")
        candidates.append({
            "utc_datetime": current.isoformat().replace("+00:00", "Z"),
            "score": result["score"],
            "factors": result["factors"],
            "asc": f'{asc["sign_tr"]} {asc["degree_str"]}',
            "moon": f'{moon["sign_tr"]} {moon["degree_str"]}' if moon else None,
        })
        current += step

    if not candidates:
        raise ElectionalCalculationError("Pencerede geçerli aday bulunamadı")

    # Skora göre sırala, top_n al
    candidates.sort(key=lambda c: -c["score"])
    top = candidates[: params["top_n"]]

    # Yerel saat gösterimi
    tz = ZoneInfo(loc["timezone_id"])
    for cand in top:
        dt = datetime.fromisoformat(cand["utc_datetime"].replace("Z", "+00:00"))
        cand["local_datetime"] = dt.astimezone(tz).isoformat()

    limitations = [
        "Skorlar klasik electional kriterlerinin basitleştirilmiş bir modelidir; nihai seçim danışmana aittir.",
        "VoC (void of course) Ay tam kontrolü v1'de yoktur; 29° anaretik derece cezası kullanılır.",
        "Fixed star / antiscia / lunar mansion katmanları v1'de yoktur.",
        f"Tarama adımı {params['step_minutes']} dk; adım aralığındaki daha ince anlar örneklenmez.",
    ]

    return {
        "status": "available",
        "version": ELECTIONAL_VERSION,
        "method": "electional_classical_scoring_v1",
        "purpose": params["purpose"],
        "purpose_tr": purpose_config["tr"],
        "target_house": purpose_config["house"],
        "natural_significator": purpose_config["significator"],
        "window": {
            "start_utc": params["window_start"].isoformat().replace("+00:00", "Z"),
            "end_utc": params["window_end"].isoformat().replace("+00:00", "Z"),
            "step_minutes": params["step_minutes"],
        },
        "location": loc,
        "candidates_scanned": len(candidates),
        "top_candidates": top,
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


def build_electional_markdown(
    data: dict,
    person_name: str,
    group_name: str,
    generated_at: str | None = None,
) -> str:
    window = data["window"]
    top = data["top_candidates"]

    fm_lines = [
        "---",
        f'title: "{person_name} - Electional {data["purpose"]}"',
        'type: "electional_pack"',
        'source: "western_api_v2_electional"',
        f'person: "{person_name}"',
        f'group: "{group_name}"',
        f'purpose: "{data["purpose"]}"',
        f'purpose_tr: "{data["purpose_tr"]}"',
        f'target_house: {data["target_house"]}',
        f'window_start: "{window["start_utc"]}"',
        f'window_end: "{window["end_utc"]}"',
        f'candidates_scanned: {data["candidates_scanned"]}',
        f'method: "{data["method"]}"',
    ]
    if generated_at:
        fm_lines.append(f'modified: "{generated_at}"')
    fm_lines.append('api_version: "v2"')
    fm_lines.append(f'engine_version: "{ELECTIONAL_VERSION}"')
    fm_lines.append("---")
    fm_lines.append("")

    overview = [
        f"# {person_name} - Electional: {data['purpose_tr']}",
        "",
        "## Kullanım Notu",
        "",
        "- Verilen pencere klasik electional kriterlerine göre tarandı; en iyi adaylar aşağıdadır.",
        "- Skorlar basitleştirilmiş modeldir; nihai seçim danışmana aittir.",
        f"- Amaç: **{data['purpose_tr']}** → hedef ev {data['target_house']}, doğal significator {data['natural_significator']}.",
        "",
        "## Tarama Parametreleri",
        "",
        f"- Pencere: {window['start_utc']} → {window['end_utc']}",
        f"- Adım: {window['step_minutes']} dk",
        f"- Konum: {data['location'].get('place') or '-'} ({data['location']['lat']:.4f}, {data['location']['lon']:.4f})",
        f"- Taranan aday: {data['candidates_scanned']}",
        "",
    ]

    candidate_sections = ["## En İyi Adaylar", ""]
    for i, cand in enumerate(top, 1):
        candidate_sections.append(f"### {i}. Aday — Skor: {cand['score']:+.2f}")
        candidate_sections.append("")
        candidate_sections.append(f"- UTC: **{cand['utc_datetime']}**")
        candidate_sections.append(f"- Yerel: **{cand['local_datetime']}**")
        candidate_sections.append(f"- ASC: {cand['asc']}")
        candidate_sections.append(f"- Ay: {cand['moon']}")
        if cand["factors"]:
            candidate_sections.append("- Faktörler:")
            candidate_sections.extend(f"  - {f}" for f in cand["factors"])
        else:
            candidate_sections.append("- Faktör kaydı yok (nötr an)")
        candidate_sections.append("")

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
        *candidate_sections,
        *limit_section,
        *technical_section,
    ])
