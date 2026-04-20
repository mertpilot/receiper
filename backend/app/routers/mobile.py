from __future__ import annotations

from datetime import datetime, timezone

from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import MobileDevice, User
from ..realtime import ws_manager
from ..schemas import ReceiptOut, UploadReceiptResponse
from ..services.receipts import process_receipt_upload


router = APIRouter(tags=["Mobile"])


@router.post("/api/mobile/receipts", response_model=UploadReceiptResponse)
async def upload_receipt_from_mobile(
    file: UploadFile = File(...),
    device_id: str | None = Form(default=None),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    linked_device_id: str | None = None
    if device_id:
        device = db.scalar(
            select(MobileDevice).where(
                MobileDevice.id == device_id,
                MobileDevice.user_id == current_user.id,
            )
        )
        if not device:
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Cihaz bulunamadi veya hesaba ait degil")
        linked_device_id = device.id
        device.last_seen_at = datetime.now(timezone.utc)

    receipt, parsed, template_row, raw_text = await process_receipt_upload(
        file=file,
        user=current_user,
        db=db,
        device_id=linked_device_id,
    )

    receipt_payload = ReceiptOut.model_validate(receipt)
    await ws_manager.broadcast(
        current_user.id,
        {
            "event": "receipt.created",
            "receipt": receipt_payload.model_dump(mode="json"),
        },
    )

    return UploadReceiptResponse(
        receipt=receipt_payload,
        raw_text_preview=raw_text[:800],
        parsed=parsed,
        template_row=template_row,
    )


@router.post("/api/upload-receipt", response_model=UploadReceiptResponse)
async def upload_receipt_legacy(
    file: UploadFile = File(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    return await upload_receipt_from_mobile(file=file, device_id=None, db=db, current_user=current_user)
