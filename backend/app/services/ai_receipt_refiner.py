from __future__ import annotations

import base64
import json
import mimetypes
import re
from pathlib import Path
from typing import Any
from urllib import error, request

from ..config import get_settings


settings = get_settings()

_JSON_BLOCK_RE = re.compile(r"\{.*\}", re.S)
_DATE_RE = re.compile(r"^([0-3]?\d)[./-]([01]?\d)[./-](\d{2,4})$")
_TIME_RE = re.compile(r"^([0-2]?\d):([0-5]\d)(?::([0-5]\d))?$")


def _clean_text(value: Any) -> str:
    if value is None:
        return ""
    text = str(value).strip()
    text = re.sub(r"\s+", " ", text)
    return text


def _normalize_date(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    match = _DATE_RE.match(text)
    if not match:
        return ""
    day = int(match.group(1))
    month = int(match.group(2))
    year_raw = match.group(3)
    if year_raw.isdigit() and len(year_raw) == 2:
        year = int(f"20{year_raw}")
    else:
        year = int(year_raw) if year_raw.isdigit() else 0
    if not (1 <= day <= 31 and 1 <= month <= 12 and 2000 <= year <= 2099):
        return ""
    return f"{day:02d}.{month:02d}.{year:04d}"


def _normalize_time(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    match = _TIME_RE.match(text)
    if not match:
        return ""
    hour = int(match.group(1))
    minute = int(match.group(2))
    second = match.group(3)
    if hour > 23:
        return ""
    if second is not None:
        return f"{hour:02d}:{minute:02d}:{int(second):02d}"
    return f"{hour:02d}:{minute:02d}"


def _normalize_amount(value: Any) -> float | None:
    if value is None:
        return None
    if isinstance(value, bool):
        return None
    if isinstance(value, (int, float)):
        number = float(value)
        return round(number, 2) if number >= 0 else None

    text = _clean_text(value).upper()
    if not text:
        return None
    text = text.replace("TL", "")
    text = text.replace("O", "0").replace("I", "1").replace("L", "1").replace("S", "5")
    text = re.sub(r"[^0-9,.\-]", "", text)
    if not text:
        return None

    negative = text.startswith("-")
    text = text.replace("-", "")
    if not text:
        return None

    last_dot = text.rfind(".")
    last_comma = text.rfind(",")
    separator = max(last_dot, last_comma)

    if separator == -1:
        digits = re.sub(r"[^0-9]", "", text)
        if not digits:
            return None
        number = float(digits)
    else:
        left = re.sub(r"[^0-9]", "", text[:separator]) or "0"
        right = re.sub(r"[^0-9]", "", text[separator + 1 :]) or "00"
        if len(right) == 1:
            right += "0"
        elif len(right) > 2:
            right = right[:2]
        number = float(f"{left}.{right}")

    if negative:
        number *= -1
    if number < 0:
        return None
    return round(number, 2)


def _normalize_tax_id(value: Any) -> str:
    text = _clean_text(value)
    if not text:
        return ""
    digits = re.sub(r"[^0-9]", "", text)
    if len(digits) in {10, 11}:
        return digits
    return ""


def _normalize_receipt_no(value: Any) -> str:
    text = _clean_text(value).upper()
    if not text:
        return ""
    text = re.sub(r"[^A-Z0-9-]", "", text)
    if len(text) < 3:
        return ""
    return text[:24]


def _normalize_payment_type(value: Any) -> str:
    text = _clean_text(value).lower()
    if not text:
        return ""
    if any(token in text for token in ("kart", "card", "pos", "visa", "master")):
        return "Kart"
    if any(token in text for token in ("nakit", "cash")):
        return "Nakit"
    return ""


def normalize_receipt_payload(payload: dict[str, Any]) -> dict[str, Any]:
    normalized: dict[str, Any] = {
        "merchant": _clean_text(payload.get("merchant")),
        "date": _normalize_date(payload.get("date")),
        "time": _normalize_time(payload.get("time")),
        "total": _normalize_amount(payload.get("total")),
        "kdv": _normalize_amount(payload.get("kdv")),
        "vat_rate": _normalize_amount(payload.get("vat_rate")),
        "receipt_no": _normalize_receipt_no(payload.get("receipt_no")),
        "tax_id": _normalize_tax_id(payload.get("tax_id")),
        "expense_description": _clean_text(payload.get("expense_description")),
        "net_amount": _normalize_amount(payload.get("net_amount")),
        "payment_type": _normalize_payment_type(payload.get("payment_type")),
    }

    if normalized["vat_rate"] is not None and not (0 <= normalized["vat_rate"] <= 99):
        normalized["vat_rate"] = None

    total = normalized["total"]
    kdv = normalized["kdv"]

    if total is not None and kdv is not None and kdv > total:
        normalized["kdv"] = None
        kdv = None

    if normalized["net_amount"] is None and total is not None and kdv is not None:
        normalized["net_amount"] = round(max(total - kdv, 0), 2)

    if normalized["total"] is None and normalized["net_amount"] is not None and kdv is not None:
        normalized["total"] = round(normalized["net_amount"] + kdv, 2)

    if normalized["vat_rate"] is None and total is not None and kdv is not None and total > kdv:
        base = total - kdv
        if base > 0:
            normalized["vat_rate"] = round((kdv / base) * 100, 2)

    if not normalized["expense_description"]:
        merchant = normalized["merchant"]
        normalized["expense_description"] = f"{merchant} Gideri".strip() if merchant else "Fis Gideri"

    return normalized


def compute_parse_confidence(parsed: dict[str, Any]) -> float:
    score = 0.0

    merchant = _clean_text(parsed.get("merchant"))
    if len(merchant) >= 4 and not re.search(r"\d", merchant):
        score += 0.16

    expense = _clean_text(parsed.get("expense_description"))
    if len(expense) >= 5:
        score += 0.10

    if _normalize_date(parsed.get("date")):
        score += 0.16
    if _normalize_time(parsed.get("time")):
        score += 0.04

    total = _normalize_amount(parsed.get("total"))
    kdv = _normalize_amount(parsed.get("kdv"))
    net_amount = _normalize_amount(parsed.get("net_amount"))

    if total is not None and total > 0:
        score += 0.22
    if kdv is not None and total is not None and 0 <= kdv < total:
        score += 0.12
    if net_amount is not None and total is not None:
        if abs((total - (kdv or 0.0)) - net_amount) <= 1.0:
            score += 0.10
    elif net_amount is not None:
        score += 0.05

    vat_rate = _normalize_amount(parsed.get("vat_rate"))
    if vat_rate is not None and 0 <= vat_rate <= 99:
        score += 0.05

    tax_id = _normalize_tax_id(parsed.get("tax_id"))
    if len(tax_id) in {10, 11}:
        score += 0.09

    if _normalize_receipt_no(parsed.get("receipt_no")):
        score += 0.08

    if _normalize_payment_type(parsed.get("payment_type")):
        score += 0.04

    return round(min(score, 1.0), 4)


def _is_missing(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str) and not value.strip():
        return True
    return False


def _is_generic_description(value: str) -> bool:
    text = _clean_text(value).lower()
    if not text:
        return True
    return text in {"fis gideri", "gider", "gideri"}


def _merge_parsed(base: dict[str, Any], ai: dict[str, Any], base_conf: float, ai_conf: float) -> dict[str, Any]:
    merged = dict(base)
    prefer_ai = ai_conf >= base_conf + 0.06

    text_fields = ("merchant", "date", "time", "receipt_no", "tax_id", "payment_type")
    for key in text_fields:
        ai_value = ai.get(key)
        if _is_missing(ai_value):
            continue
        if _is_missing(merged.get(key)) or prefer_ai:
            merged[key] = ai_value

    ai_desc = _clean_text(ai.get("expense_description"))
    base_desc = _clean_text(merged.get("expense_description"))
    if ai_desc and (_is_generic_description(base_desc) or prefer_ai):
        merged["expense_description"] = ai_desc

    numeric_fields = ("total", "kdv", "vat_rate", "net_amount")
    for key in numeric_fields:
        ai_value = ai.get(key)
        if ai_value is None:
            continue
        if merged.get(key) is None or prefer_ai:
            merged[key] = ai_value

    return normalize_receipt_payload(merged)


def _build_prompt(raw_text: str, parsed: dict[str, Any]) -> str:
    return (
        "Sen Turkce fis verisi ayiklama uzmanisin.\n"
        "Asagidaki OCR metni ve mevcut parser sonucunu kullanarak yalnizca JSON don.\n"
        "Sadece su anahtarlar olsun: merchant,date,time,total,kdv,vat_rate,receipt_no,tax_id,expense_description,net_amount,payment_type.\n"
        "Kurallar:\n"
        "- date formati DD.MM.YYYY\n"
        "- time HH:MM veya bos\n"
        "- total/kdv/vat_rate/net_amount sayi veya null\n"
        "- tax_id sadece 10-11 hane sayi\n"
        "- payment_type sadece Kart, Nakit veya bos\n"
        "- Emin degilsen null veya bos don.\n\n"
        f"Mevcut parser sonucu:\n{json.dumps(parsed, ensure_ascii=False)}\n\n"
        f"OCR ham metin:\n{raw_text[:8000]}"
    )


def _extract_json_object(text: str) -> dict[str, Any] | None:
    if not text:
        return None
    candidate = text.strip()
    if candidate.startswith("```"):
        candidate = candidate.strip("`")
        if candidate.lower().startswith("json"):
            candidate = candidate[4:].strip()
    try:
        data = json.loads(candidate)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass

    match = _JSON_BLOCK_RE.search(text)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        return None
    return None


def _extract_text_from_gemini(result: dict[str, Any]) -> str:
    candidates = result.get("candidates")
    if not isinstance(candidates, list):
        return ""
    for candidate in candidates:
        content = candidate.get("content", {})
        parts = content.get("parts", [])
        if not isinstance(parts, list):
            continue
        for part in parts:
            text = part.get("text")
            if isinstance(text, str) and text.strip():
                return text
    return ""


def _call_gemini(raw_text: str, parsed: dict[str, Any], image_path: Path, include_image: bool) -> dict[str, Any] | None:
    if not settings.gemini_api_key:
        return None

    prompt = _build_prompt(raw_text=raw_text, parsed=parsed)
    parts: list[dict[str, Any]] = [{"text": prompt}]

    if include_image and image_path.exists() and image_path.is_file():
        mime_type = mimetypes.guess_type(image_path.name)[0] or "image/jpeg"
        data = image_path.read_bytes()
        # Keep payload bounded for low latency and avoid hitting request limits.
        if len(data) <= 4 * 1024 * 1024:
            parts.append(
                {
                    "inlineData": {
                        "mimeType": mime_type,
                        "data": base64.b64encode(data).decode("ascii"),
                    }
                }
            )

    payload = {
        "contents": [{"role": "user", "parts": parts}],
        "generationConfig": {
            "temperature": 0,
            "maxOutputTokens": 500,
            "responseMimeType": "application/json",
        },
    }

    url = (
        f"https://generativelanguage.googleapis.com/v1beta/models/"
        f"{settings.gemini_model}:generateContent?key={settings.gemini_api_key}"
    )
    body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
    req = request.Request(
        url=url,
        data=body,
        method="POST",
        headers={"Content-Type": "application/json; charset=utf-8"},
    )
    try:
        with request.urlopen(req, timeout=settings.gemini_timeout_seconds) as resp:
            response_body = resp.read().decode("utf-8", errors="ignore")
    except (error.URLError, TimeoutError, OSError):
        return None

    try:
        parsed_response = json.loads(response_body)
    except json.JSONDecodeError:
        return None

    text = _extract_text_from_gemini(parsed_response)
    json_payload = _extract_json_object(text)
    if not json_payload:
        return None
    return json_payload


def maybe_refine_receipt_parse(
    *,
    raw_text: str,
    parsed: dict[str, Any],
    image_path: Path,
) -> tuple[dict[str, Any], bool, float]:
    normalized_base = normalize_receipt_payload(parsed)
    base_confidence = compute_parse_confidence(normalized_base)

    if not settings.gemini_fallback_enabled:
        return normalized_base, False, base_confidence
    if not settings.gemini_api_key:
        return normalized_base, False, base_confidence
    if base_confidence >= 0.68:
        return normalized_base, False, base_confidence

    include_image = base_confidence < 0.52
    ai_payload = _call_gemini(
        raw_text=raw_text,
        parsed=normalized_base,
        image_path=image_path,
        include_image=include_image,
    )
    if not ai_payload:
        return normalized_base, False, base_confidence

    normalized_ai = normalize_receipt_payload(ai_payload)
    ai_confidence = compute_parse_confidence(normalized_ai)
    merged = _merge_parsed(normalized_base, normalized_ai, base_confidence, ai_confidence)
    merged_confidence = compute_parse_confidence(merged)
    ai_used = merged != normalized_base
    return merged, ai_used, merged_confidence
