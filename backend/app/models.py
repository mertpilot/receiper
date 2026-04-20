from __future__ import annotations

from datetime import date, datetime, timezone
from uuid import uuid4

from sqlalchemy import Date, DateTime, Float, ForeignKey, String, Text, UniqueConstraint
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .database import Base


def _utcnow() -> datetime:
    return datetime.now(timezone.utc)


class User(Base):
    __tablename__ = "users"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    email: Mapped[str] = mapped_column(String(255), unique=True, index=True)
    password_hash: Mapped[str] = mapped_column(String(255))
    full_name: Mapped[str] = mapped_column(String(120), default="")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    updated_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    devices: Mapped[list["MobileDevice"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    pairing_codes: Mapped[list["PairingCode"]] = relationship(back_populates="user", cascade="all, delete-orphan")
    receipts: Mapped[list["Receipt"]] = relationship(back_populates="user", cascade="all, delete-orphan")


class MobileDevice(Base):
    __tablename__ = "mobile_devices"
    __table_args__ = (UniqueConstraint("user_id", "device_name", name="uq_mobile_device_user_name"),)

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_name: Mapped[str] = mapped_column(String(120), default="Unknown Device")
    platform: Mapped[str] = mapped_column(String(40), default="android")
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    last_seen_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, onupdate=_utcnow)

    user: Mapped["User"] = relationship(back_populates="devices")
    receipts: Mapped[list["Receipt"]] = relationship(back_populates="device")


class PairingCode(Base):
    __tablename__ = "pairing_codes"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    code: Mapped[str] = mapped_column(String(12), unique=True, index=True)
    created_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow)
    expires_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), index=True)
    consumed_at: Mapped[datetime | None] = mapped_column(DateTime(timezone=True), nullable=True)
    consumed_by_device_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("mobile_devices.id", ondelete="SET NULL"),
        nullable=True,
    )

    user: Mapped["User"] = relationship(back_populates="pairing_codes")


class Receipt(Base):
    __tablename__ = "receipts"

    id: Mapped[str] = mapped_column(String(36), primary_key=True, default=lambda: str(uuid4()))
    user_id: Mapped[str] = mapped_column(String(36), ForeignKey("users.id", ondelete="CASCADE"), index=True)
    device_id: Mapped[str | None] = mapped_column(
        String(36),
        ForeignKey("mobile_devices.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_file_name: Mapped[str] = mapped_column(String(255))
    source_image_path: Mapped[str] = mapped_column(String(500))
    uploaded_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), default=_utcnow, index=True)

    # Excel-like template fields
    kod: Mapped[str] = mapped_column(String(20), default="MS")
    hesap_kodu: Mapped[str] = mapped_column(String(20), default="MS")
    evrak_tarihi_text: Mapped[str] = mapped_column(String(16), default="")
    evrak_tarihi: Mapped[date | None] = mapped_column(Date, nullable=True)
    evrak_no: Mapped[str] = mapped_column(String(80), default="")
    vergi_tc_no: Mapped[str] = mapped_column(String(20), default="")
    gider_aciklama: Mapped[str] = mapped_column(String(255), default="")
    kdv_orani: Mapped[float | None] = mapped_column(Float, nullable=True)
    alinan_mal_masraf: Mapped[float | None] = mapped_column(Float, nullable=True)
    ind_kdv: Mapped[float | None] = mapped_column(Float, nullable=True)
    toplam: Mapped[float | None] = mapped_column(Float, nullable=True)

    # Additional parsed fields for analytics/debug
    merchant: Mapped[str] = mapped_column(String(160), default="")
    payment_type: Mapped[str] = mapped_column(String(30), default="")
    receipt_time: Mapped[str] = mapped_column(String(16), default="")
    raw_text: Mapped[str] = mapped_column(Text, default="")

    user: Mapped["User"] = relationship(back_populates="receipts")
    device: Mapped["MobileDevice"] = relationship(back_populates="receipts")
