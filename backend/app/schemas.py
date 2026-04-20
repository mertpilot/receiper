from __future__ import annotations

from datetime import datetime

from pydantic import BaseModel, ConfigDict, Field


class UserCreateRequest(BaseModel):
    email: str = Field(min_length=5, max_length=255)
    password: str = Field(min_length=6, max_length=128)
    full_name: str = Field(default="", max_length=120)


class UserLoginRequest(BaseModel):
    email: str
    password: str


class UserOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    email: str
    full_name: str
    created_at: datetime


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    expires_in_seconds: int
    user: UserOut


class PairingCodeOut(BaseModel):
    code: str
    expires_at: datetime
    pairing_uri: str


class MobilePairRequest(BaseModel):
    code: str = Field(min_length=4, max_length=12)
    device_name: str = Field(default="Android Cihaz")
    platform: str = Field(default="android")


class MobileDeviceOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    device_name: str
    platform: str
    created_at: datetime
    last_seen_at: datetime


class PairingResult(BaseModel):
    message: str
    device: MobileDeviceOut


class ReceiptOut(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: str
    user_id: str
    device_id: str | None
    uploaded_at: datetime
    source_file_name: str

    kod: str
    hesap_kodu: str
    evrak_tarihi_text: str
    evrak_no: str
    vergi_tc_no: str
    gider_aciklama: str
    kdv_orani: float | None
    alinan_mal_masraf: float | None
    ind_kdv: float | None
    toplam: float | None

    merchant: str
    payment_type: str
    receipt_time: str


class ReceiptListResponse(BaseModel):
    items: list[ReceiptOut]
    total: int


class UploadReceiptResponse(BaseModel):
    ok: bool = True
    receipt: ReceiptOut
    raw_text_preview: str
    parsed: dict
    template_row: dict
    ai_used: bool = False
    parse_confidence: float | None = None


class RealtimeReceiptEvent(BaseModel):
    event: str = "receipt.created"
    receipt: ReceiptOut
