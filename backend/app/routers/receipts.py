from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..database import get_db
from ..models import Receipt, User
from ..schemas import ReceiptListResponse, ReceiptOut


router = APIRouter(prefix="/api/receipts", tags=["Receipts"])


@router.get("", response_model=ReceiptListResponse)
def list_receipts(
    limit: int = Query(default=100, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    items = (
        db.execute(
            select(Receipt)
            .where(Receipt.user_id == current_user.id)
            .order_by(Receipt.uploaded_at.desc())
            .offset(offset)
            .limit(limit)
        )
        .scalars()
        .all()
    )
    total = db.scalar(select(func.count(Receipt.id)).where(Receipt.user_id == current_user.id)) or 0
    return ReceiptListResponse(items=items, total=int(total))


@router.get("/{receipt_id}", response_model=ReceiptOut)
def get_receipt(
    receipt_id: str,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    receipt = db.scalar(
        select(Receipt).where(
            Receipt.id == receipt_id,
            Receipt.user_id == current_user.id,
        )
    )
    if not receipt:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Kayit bulunamadi")
    return receipt
