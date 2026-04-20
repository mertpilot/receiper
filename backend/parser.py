import os
import re
import unicodedata
from pathlib import Path
from typing import Optional

from PIL import Image, ImageEnhance, ImageFilter, ImageOps
import pytesseract


AMOUNT_TOKEN_REGEX = re.compile(r"(?:\d{1,3}(?:[.\s]\d{3})+|\d+)[,\.]\d{1,2}")
DATE_REGEX = re.compile(r"([0-3]?\d[./-][01]?\d[./-]20\d{2})")
DATE_SHORT_REGEX = re.compile(r"([0-3]?\d[./-][01]?\d[./-]\d{2})")
DATE_LOOSE_REGEX = re.compile(r"([0-3]?\d)\s*[./-]\s*([01]?\d)\s*[./\-\s]+\s*(20\d{2,3})")
TIME_REGEX = re.compile(r"\b([0-2]?\d:[0-5]\d(?::[0-5]\d)?)\b")
VAT_RATE_REGEX = re.compile(r"%\s*([0-9]{1,2})|\b([0-9]{1,2})\s*%")
OCR_MAX_SIDE = 2200
OCR_MIN_SIDE = 900


def _strip_diacritics(text: str) -> str:
    normalized = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in normalized if not unicodedata.combining(ch))


def _fold_text(text: str) -> str:
    mapped = text.translate(str.maketrans({
        "Ç": "C",
        "Ğ": "G",
        "İ": "I",
        "I": "I",
        "Ö": "O",
        "Ş": "S",
        "Ü": "U",
        "ç": "c",
        "ğ": "g",
        "ı": "i",
        "ö": "o",
        "ş": "s",
        "ü": "u",
    }))
    return _strip_diacritics(mapped)


def _clean_line(line: str) -> str:
    line = line.replace("\t", " ").strip()
    line = re.sub(r"\s+", " ", line)
    line = line.strip("|`'\".,:;~=+_-/\\[]{}")
    return line


def _normalize_visible_text(text: str) -> str:
    normalized = unicodedata.normalize("NFKC", text)
    normalized = "".join(ch for ch in normalized if not unicodedata.combining(ch))
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _configure_tesseract() -> None:
    configured = os.getenv("TESSERACT_CMD", "").strip()
    if configured:
        pytesseract.pytesseract.tesseract_cmd = configured


def _resolve_tessdata_dir() -> Optional[Path]:
    env_dir = os.getenv("TESSDATA_DIR", "").strip()
    if env_dir:
        p = Path(env_dir)
        if p.exists() and p.is_dir():
            return p

    prefix = os.getenv("TESSDATA_PREFIX", "").strip()
    if prefix:
        p = Path(prefix)
        if p.exists() and p.is_dir():
            if p.name.lower() == "tessdata":
                return p
            child = p / "tessdata"
            if child.exists() and child.is_dir():
                return child

    local = Path(__file__).resolve().parent / "tessdata"
    if local.exists() and local.is_dir():
        return local

    return None


def _build_tesseract_config(psm: int = 6) -> str:
    config = f"--oem 3 --psm {psm}"
    tessdata = _resolve_tessdata_dir()
    if tessdata:
        config = f"--tessdata-dir {tessdata} {config}"
    return config


def _resolve_ocr_lang() -> str:
    requested = os.getenv("OCR_LANG", "tur+eng")
    parts = [p.strip() for p in requested.split("+") if p.strip()]
    if not parts:
        parts = ["eng"]

    try:
        available = set(pytesseract.get_languages(config=_build_tesseract_config()))
    except Exception:
        available = set()

    if not available:
        return requested

    selected = [p for p in parts if p in available]
    if selected:
        return "+".join(selected)
    if "eng" in available:
        return "eng"
    return next(iter(available))


def _prepare_variant(img: Image.Image, rotation: int, variant: str) -> Image.Image:
    rotated = img.rotate(rotation, expand=True)
    gray = ImageOps.grayscale(rotated)

    if variant == "base":
        proc = ImageOps.autocontrast(gray, cutoff=1)
        proc = ImageEnhance.Contrast(proc).enhance(2.4)
        proc = ImageEnhance.Sharpness(proc).enhance(1.8)
        return proc

    if variant == "threshold":
        proc = ImageOps.autocontrast(gray, cutoff=1)
        return proc.point(lambda p: 255 if p > 165 else 0)

    proc = gray.filter(ImageFilter.MedianFilter(size=3))
    proc = ImageEnhance.Contrast(proc).enhance(2.9)
    return proc


def _score_ocr_text(text: str) -> float:
    upper = _fold_text(text).upper()
    score = 0.0

    if DATE_REGEX.search(upper) or DATE_SHORT_REGEX.search(upper):
        score += 4.0
    if TIME_REGEX.search(upper):
        score += 2.0
    if "TOPLAM" in upper:
        score += 4.0
    if "KDV" in upper or "KDY" in upper:
        score += 3.0
    if "FIS" in upper or "FI" in upper:
        score += 2.0

    score += min(8.0, float(len(AMOUNT_TOKEN_REGEX.findall(upper))))
    score += min(6.0, float(len(re.findall(r"\b[A-Z]{3,}\b", upper)))) * 0.25
    return score


def _ocr_single(image: Image.Image, lang: str, psm: int) -> str:
    config = _build_tesseract_config(psm=psm)
    text = pytesseract.image_to_string(image, lang=lang, config=config)
    return (text or "").strip()


def _resize_for_ocr(image: Image.Image) -> Image.Image:
    width, height = image.size
    max_side = max(width, height)
    min_side = min(width, height)

    scale = 1.0
    if max_side > OCR_MAX_SIDE:
        scale = OCR_MAX_SIDE / float(max_side)
    elif min_side < OCR_MIN_SIDE:
        scale = min(1.8, OCR_MIN_SIDE / float(min_side))

    if abs(scale - 1.0) < 0.01:
        return image

    new_size = (
        max(1, int(round(width * scale))),
        max(1, int(round(height * scale))),
    )
    return image.resize(new_size, Image.Resampling.LANCZOS)


def _ocr_with_best_candidate(image: Image.Image, lang: str) -> str:
    best_text = ""
    best_score = -1.0
    best_rotation = 0
    work = _resize_for_ocr(image)

    rotations: list[int] = [0, 90, 270]
    if work.width > work.height:
        rotations = [0, 270, 90]

    for rotation in rotations:
        base = _prepare_variant(work, rotation, "base")
        text = _ocr_single(base, lang=lang, psm=11)
        score = _score_ocr_text(text)
        if score > best_score:
            best_score = score
            best_text = text
            best_rotation = rotation
        if score >= 17:
            return best_text

    if best_score < 9:
        base_180 = _prepare_variant(work, 180, "base")
        text_180 = _ocr_single(base_180, lang=lang, psm=11)
        score_180 = _score_ocr_text(text_180)
        if score_180 > best_score:
            best_score = score_180
            best_text = text_180
            best_rotation = 180

    for psm in (6,):
        base = _prepare_variant(work, best_rotation, "base")
        text = _ocr_single(base, lang=lang, psm=psm)
        score = _score_ocr_text(text)
        if score > best_score:
            best_score = score
            best_text = text
        if score >= 16:
            return best_text

    if best_score < 12:
        for variant in ("threshold", "denoise"):
            proc = _prepare_variant(work, best_rotation, variant)
            text = _ocr_single(proc, lang=lang, psm=11)
            score = _score_ocr_text(text)
            if score > best_score:
                best_score = score
                best_text = text

    return (best_text or "").strip()


def ocr_image(image_path: Path) -> str:
    _configure_tesseract()
    lang = _resolve_ocr_lang()

    try:
        with Image.open(image_path) as img:
            normalized = ImageOps.exif_transpose(img)
            text = _ocr_with_best_candidate(normalized, lang=lang)
    except pytesseract.TesseractNotFoundError as exc:
        raise RuntimeError("Tesseract bulunamadi. Lutfen Tesseract OCR kurup TESSERACT_CMD ayari yapin.") from exc
    except pytesseract.TesseractError as exc:
        raise RuntimeError(f"OCR hatasi: {exc}") from exc

    return text


def _normalize_amount_token(token: str) -> Optional[float]:
    raw = token.upper().replace(" ", "")
    raw = raw.replace("O", "0").replace("I", "1").replace("L", "1").replace("S", "5")
    raw = re.sub(r"[^0-9,\.]", "", raw)
    if not raw:
        return None

    last_dot = raw.rfind(".")
    last_comma = raw.rfind(",")
    sep = max(last_dot, last_comma)

    if sep == -1:
        digits = re.sub(r"[^0-9]", "", raw)
        return float(digits) if digits else None

    left = re.sub(r"[^0-9]", "", raw[:sep])
    right = re.sub(r"[^0-9]", "", raw[sep + 1 :])

    if not left:
        left = "0"
    if not right:
        right = "00"
    if len(right) == 1:
        right += "0"
    elif len(right) > 2:
        right = right[:2]

    return float(f"{left}.{right}")


def _amounts_from_line(line: str) -> list[float]:
    found = AMOUNT_TOKEN_REGEX.findall(line)
    values: list[float] = []
    for token in found:
        value = _normalize_amount_token(token)
        if value is not None:
            values.append(value)
    return values


def _extract_date(text: str) -> str:
    folded = _fold_text(text)
    m = DATE_REGEX.search(folded)
    if m:
        return m.group(1).replace("-", ".").replace("/", ".")

    m2 = DATE_SHORT_REGEX.search(folded)
    if m2:
        value = m2.group(1).replace("-", ".").replace("/", ".")
        day, month, year = value.split(".")
        year_full = f"20{year}" if len(year) == 2 else year
        return f"{day.zfill(2)}.{month.zfill(2)}.{year_full}"

    loose = DATE_LOOSE_REGEX.search(folded)
    if loose:
        day = loose.group(1).zfill(2)
        month = loose.group(2).zfill(2)
        year = loose.group(3)[:4]
        return f"{day}.{month}.{year}"

    for raw_line in folded.split("\n"):
        line = raw_line.upper()
        if "SAAT" not in line and "TARIH" not in line and not re.search(r"\d{1,2}\s+\d{1,2}\s+\d{2,4}", line):
            continue

        tokens = re.findall(r"\d{1,4}", line)
        if len(tokens) < 3:
            continue

        for idx in range(len(tokens) - 2):
            day_raw = tokens[idx]
            month_raw = tokens[idx + 1]
            year_raw = tokens[idx + 2]

            if not (1 <= int(day_raw) <= 31 and 1 <= int(month_raw) <= 12):
                continue

            if len(year_raw) == 2:
                year = f"20{year_raw}"
            elif len(year_raw) == 3 and year_raw.startswith("2"):
                year = f"2{year_raw[1:].zfill(3)}"
            elif len(year_raw) == 4 and year_raw.startswith("20"):
                year = year_raw
            else:
                continue

            return f"{day_raw.zfill(2)}.{month_raw.zfill(2)}.{year[:4]}"

    return ""


def _extract_time(text: str) -> str:
    folded = _fold_text(text)
    m = TIME_REGEX.search(folded)
    return m.group(1) if m else ""


def _extract_total(lines_upper: list[str]) -> Optional[float]:
    keywords = ("GENEL TOPLAM", "TOPLAM", "ODENECEK", "TUTAR", "ISLEM TUTARI")
    best: Optional[float] = None

    for line in lines_upper:
        if not any(k in line for k in keywords):
            continue
        amounts = _amounts_from_line(line)
        if not amounts:
            continue
        value = max(amounts)
        best = value if best is None else max(best, value)

    if best is not None:
        return best

    all_amounts: list[float] = []
    for line in lines_upper:
        all_amounts.extend(_amounts_from_line(line))

    if not all_amounts:
        return None
    return max(all_amounts)


def _extract_kdv(lines_upper: list[str], total: Optional[float]) -> Optional[float]:
    best: Optional[float] = None

    for idx, line in enumerate(lines_upper):
        if "KDV" not in line and "KDY" not in line:
            continue
        window = [line]
        if idx > 0:
            window.append(lines_upper[idx - 1])
        if idx + 1 < len(lines_upper):
            window.append(lines_upper[idx + 1])
        if idx + 2 < len(lines_upper):
            window.append(lines_upper[idx + 2])

        amounts: list[float] = []
        for w in window:
            amounts.extend(_amounts_from_line(w))
        if not amounts:
            continue
        positives = [v for v in amounts if v > 0]
        if not positives:
            continue

        if total is not None:
            under_total = [v for v in positives if v < total]
            if not under_total:
                continue
            value = max(under_total)
        else:
            value = max(positives)

        best = value if best is None else max(best, value)

    if best is not None:
        return best

    if total is None:
        return None

    for line in lines_upper:
        if "%" not in line:
            continue
        amounts = _amounts_from_line(line)
        if not amounts:
            continue
        candidate = max(amounts)
        if candidate < total:
            return round(total - candidate, 2)

    return None


def _extract_vat_rate(text: str, total: Optional[float], kdv: Optional[float]) -> Optional[float]:
    folded = _fold_text(text).upper()
    for m in VAT_RATE_REGEX.finditer(folded):
        value_str = m.group(1) or m.group(2)
        if not value_str:
            continue
        try:
            value = float(value_str)
        except ValueError:
            continue
        if 0 <= value <= 99:
            return value

    if total is not None and kdv is not None and total > kdv:
        base = total - kdv
        if base > 0:
            return round((kdv / base) * 100, 2)

    return None


def _extract_tax_id(lines: list[str]) -> str:
    keyed_candidates: list[str] = []
    any_candidates: list[str] = []

    for line in lines:
        folded = _fold_text(line).upper()
        normalized = folded.replace("O", "0").replace("I", "1").replace("L", "1")
        numbers = re.findall(r"\d{10,11}", normalized)
        if not numbers:
            continue

        if any(k in folded for k in ("VKN", "VERGI", "V.D", "VD", "VU", "TC")):
            keyed_candidates.extend(numbers)
        any_candidates.extend(numbers)

    def pick_best(candidates: list[str]) -> str:
        seen: set[str] = set()
        ordered: list[str] = []
        for candidate in candidates:
            if candidate in seen:
                continue
            seen.add(candidate)
            ordered.append(candidate)

        eleven = [c for c in ordered if len(c) == 11]
        if eleven:
            return eleven[0]

        ten = [c for c in ordered if len(c) == 10]
        if ten:
            return ten[0]
        return ""

    best = pick_best(keyed_candidates)
    if best:
        return best

    best = pick_best(any_candidates)
    if best:
        return best

    return ""


def _extract_receipt_no(lines: list[str]) -> str:
    priority_groups = [
        ("FIS NO", "BELGE NO", "EVRAK NO", "FIS"),
        ("ISLEM NO", "TRN", "REF"),
    ]

    for key_words in priority_groups:
        for line in lines:
            folded = _fold_text(line).upper()
            if not any(k in folded for k in key_words):
                continue

            tail = folded
            if ":" in folded:
                tail = folded.split(":", 1)[1]

            alnums = re.findall(r"[A-Z0-9-]{3,}", tail)
            for token in alnums:
                if any(ch.isdigit() for ch in token) and len(token) <= 16:
                    return token

            nums = re.findall(r"\d{3,}", folded)
            if nums:
                return nums[0]

    return ""


def _merchant_guess(lines: list[str], tax_id: str) -> str:
    blocked = (
        "VERGI",
        "V.D",
        "VKN",
        "SAAT",
        "TARIH",
        "TOPLAM",
        "KDV",
        "ISLEM",
        "BANKA",
        "POS",
        "MAH",
        "SK",
        "SOKAK",
        "CAD",
        "NO",
        "TEL",
        "BURSA",
        "ANKARA",
        "ISTANBUL",
    )

    candidates: list[tuple[float, str]] = []

    for idx, line in enumerate(lines[:14]):
        cleaned = _clean_line(line)
        if len(cleaned) < 3:
            continue

        folded = _fold_text(cleaned).upper()
        if tax_id and tax_id in re.sub(r"[^0-9]", "", folded):
            continue
        if any(tok in folded for tok in blocked):
            continue
        if re.search(r"\d", folded):
            continue

        letter_count = len(re.findall(r"[A-Z]", folded))
        if letter_count < 4:
            continue

        valid_ratio = len(re.findall(r"[A-Z ]", folded)) / max(1, len(folded))
        if valid_ratio < 0.55:
            continue

        words = re.findall(r"[A-Z]{3,}", folded)
        if not words:
            continue

        score = sum(len(w) for w in words) - (idx * 0.2)
        candidates.append((score, _normalize_visible_text(cleaned).title()))

    if not candidates:
        return ""

    candidates.sort(key=lambda x: x[0], reverse=True)
    return candidates[0][1]


def _extract_expense_description(lines: list[str], merchant: str) -> str:
    blocked = (
        "TOPLAM",
        "KDV",
        "BANKA",
        "POS",
        "ISLEM",
        "TARIH",
        "SAAT",
        "FIS",
        "VKN",
        "VERGI",
        "MAH",
        "SK",
        "SOKAK",
        "CAD",
        "TEL",
    )

    for raw in lines:
        cleaned = _clean_line(raw)
        if not cleaned:
            continue

        folded = _fold_text(cleaned).upper()
        if any(tok in folded for tok in blocked):
            continue

        has_amount = bool(_amounts_from_line(folded))
        if not has_amount:
            continue

        text_part = AMOUNT_TOKEN_REGEX.sub(" ", folded)
        text_part = re.sub(r"[%*xX0-9.,:;\-]+", " ", text_part)
        text_part = re.sub(r"\s+", " ", text_part).strip()
        text_part = " ".join(part for part in text_part.split(" ") if len(part) >= 2)

        if len(text_part) >= 3:
            return text_part.title()

    if merchant:
        return f"{merchant} Gideri"
    return "Fis Gideri"


def parse_receipt_text(raw_text: str) -> dict:
    normalized_text = raw_text.replace("\r", "\n")
    lines = [_clean_line(line) for line in normalized_text.split("\n")]
    lines = [line for line in lines if line]
    lines_upper = [_fold_text(line).upper() for line in lines]

    date = _extract_date(normalized_text)
    time = _extract_time(normalized_text)
    total = _extract_total(lines_upper)
    kdv = _extract_kdv(lines_upper, total=total)
    vat_rate = _extract_vat_rate(normalized_text, total=total, kdv=kdv)
    tax_id = _extract_tax_id(lines)
    receipt_no = _extract_receipt_no(lines)

    payment_type = ""
    all_upper = "\n".join(lines_upper)
    if any(tok in all_upper for tok in ("KREDI", "KART", "POS", "VISA", "MASTERCARD", "DEBIT")):
        payment_type = "Kart"
    elif "NAKIT" in all_upper:
        payment_type = "Nakit"

    merchant = _merchant_guess(lines, tax_id=tax_id)
    expense_description = _extract_expense_description(lines, merchant=merchant)
    merchant = _normalize_visible_text(merchant)
    expense_description = _normalize_visible_text(expense_description)

    net_amount = None
    if total is not None and kdv is not None:
        net_amount = round(max(total - kdv, 0), 2)
    elif total is not None:
        net_amount = total

    return {
        "merchant": merchant,
        "date": date,
        "time": time,
        "total": total,
        "kdv": kdv,
        "vat_rate": vat_rate,
        "receipt_no": receipt_no,
        "tax_id": tax_id,
        "expense_description": expense_description,
        "net_amount": net_amount,
        "payment_type": payment_type,
    }
