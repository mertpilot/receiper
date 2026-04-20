from __future__ import annotations

import re
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from fastapi import HTTPException, UploadFile, status
from sqlalchemy.orm import Session

from excel_writer import build_template_row
from parser import ocr_image, parse_receipt_text

from ..config import get_settings
from ..models import Receipt, User


settings = get_settings()


def _parse_receipt_date(date_text: str) -> datetime.date | None:
    clean = (date_text or "").strip()
    if not clean:
        return None
    try:
        return datetime.strptime(clean, "%d.%m.%Y").date()
    except ValueError:
        return None


def _safe_file_name(original_name: str) -> str:
    suffix = Path(original_name or "").suffix.lower() or ".jpg"
    suffix = re.sub(r"[^a-z0-9.]", "", suffix)
    if not suffix.startswith("."):
        suffix = f".{suffix}"
    if suffix not in {".jpg", ".jpeg", ".png", ".webp", ".bmp", ".tif", ".tiff"}:
        suffix = ".jpg"
    return f"{uuid4().hex}{suffix}"


def _build_receipt_row(
    user: User,
    file_name: str,
    source_image_path: str,
    raw_text: str,
    parsed: dict,
    template_row: dict,
    device_id: str | None,
) -> Receipt:
    return Receipt(
        user_id=user.id,
        device_id=device_id,
        source_file_name=file_name,
        source_image_path=source_image_path,
        raw_text=raw_text,
        merchant=parsed.get("merchant", ""),
        payment_type=parsed.get("payment_type", ""),
        receipt_time=parsed.get("time", ""),
        kod=template_row.get("kod", "MS"),
        hesap_kodu=template_row.get("hesap_kodu", "MS"),
        evrak_tarihi_text=template_row.get("evrak_tarihi", ""),
        evrak_tarihi=_parse_receipt_date(template_row.get("evrak_tarihi", "")),
        evrak_no=template_row.get("evrak_no", ""),
        vergi_tc_no=template_row.get("vergi_tc_no", ""),
        gider_aciklama=template_row.get("gider_aciklama", ""),
        kdv_orani=template_row.get("kdv_orani"),
        alinan_mal_masraf=template_row.get("alinan_mal_masraf"),
        ind_kdv=template_row.get("ind_kdv"),
        toplam=template_row.get("toplam"),
    )


async def process_receipt_upload(
    *,
    file: UploadFile,
    user: User,
    db: Session,
    device_id: str | None = None,
) -> tuple[Receipt, dict, dict, str]:
    if not file.content_type or not file.content_type.startswith("image/"):
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Lutfen gecerli bir gorsel yukleyin")

    content = await file.read()
    if len(content) > settings.max_upload_mb * 1024 * 1024:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Dosya boyutu {settings.max_upload_mb}MB sinirini asti",
        )

    safe_name = _safe_file_name(file.filename or "")
    user_upload_dir = Path(settings.upload_root) / user.id
    user_upload_dir.mkdir(parents=True, exist_ok=True)
    destination = user_upload_dir / safe_name
    destination.write_bytes(content)

    try:
        raw_text = ocr_image(destination)
        parsed = parse_receipt_text(raw_text)
    except RuntimeError as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail=f"OCR/parse hatasi: {exc}") from exc

    template_row = build_template_row(parsed)
    receipt = _build_receipt_row(
        user=user,
        file_name=safe_name,
        source_image_path=str(destination),
        raw_text=raw_text,
        parsed=parsed,
        template_row=template_row,
        device_id=device_id,
    )
    db.add(receipt)
    db.commit()
    db.refresh(receipt)
    return receipt, parsed, template_row, raw_text

