from __future__ import annotations

import secrets
import string
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, status
from sqlalchemy import and_, select
from sqlalchemy.orm import Session

from ..auth import get_current_user
from ..config import get_settings
from ..database import get_db
from ..models import MobileDevice, PairingCode, User
from ..schemas import MobilePairRequest, PairingCodeOut, PairingResult


router = APIRouter(tags=["Pairing"])
settings = get_settings()


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


def _new_code(length: int = 6) -> str:
    alphabet = string.digits + string.ascii_uppercase
    return "".join(secrets.choice(alphabet) for _ in range(length))


@router.post("/api/pairing-codes", response_model=PairingCodeOut)
def create_pairing_code(
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    now = _utcnow()
    expires_at = now + timedelta(minutes=settings.pairing_ttl_minutes)

    code = None
    for _ in range(10):
        candidate = _new_code()
        existing = db.scalar(select(PairingCode).where(PairingCode.code == candidate))
        if not existing:
            code = candidate
            break
    if not code:
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Pairing code uretilemedi")

    record = PairingCode(
        user_id=current_user.id,
        code=code,
        expires_at=expires_at,
    )
    db.add(record)
    db.commit()

    base = settings.dashboard_base_url.strip().rstrip("/")
    if base:
        pairing_uri = f"{base}/pair?code={code}"
    else:
        pairing_uri = f"receiper://pair?code={code}"

    return PairingCodeOut(code=code, expires_at=expires_at, pairing_uri=pairing_uri)


@router.post("/api/mobile/pair", response_model=PairingResult)
def pair_mobile_device(
    payload: MobilePairRequest,
    db: Session = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    code = payload.code.strip().upper()
    now = _utcnow()
    record = db.scalar(
        select(PairingCode).where(
            and_(
                PairingCode.code == code,
                PairingCode.expires_at > now,
                PairingCode.consumed_at.is_(None),
            )
        )
    )
    if not record:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Pairing code gecersiz veya suresi dolmus")

    if record.user_id != current_user.id:
        raise HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail="Bu pairing kodu baska hesaba ait")

    device_name = payload.device_name.strip() or "Android Cihaz"
    platform = payload.platform.strip().lower() or "android"
    device = db.scalar(
        select(MobileDevice).where(
            and_(
                MobileDevice.user_id == current_user.id,
                MobileDevice.device_name == device_name,
            )
        )
    )
    if device is None:
        device = MobileDevice(user_id=current_user.id, device_name=device_name, platform=platform)
        db.add(device)
        db.flush()

    device.last_seen_at = now
    device.platform = platform
    record.consumed_at = now
    record.consumed_by_device_id = device.id
    db.commit()
    db.refresh(device)

    return PairingResult(message="Cihaz basariyla eslesti", device=device)

