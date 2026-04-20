# Receiper Mobile API Entegrasyonu

## 1) Login

`POST /api/auth/login`

```json
{
  "email": "demo@receiper.com",
  "password": "123456"
}
```

Response:

```json
{
  "access_token": "<jwt>",
  "token_type": "bearer",
  "expires_in_seconds": 2592000,
  "user": {
    "id": "uuid",
    "email": "demo@receiper.com",
    "full_name": "Demo"
  }
}
```

## 2) QR/Code Pair

Mobil kullanıcı login olduktan sonra:

`POST /api/mobile/pair`

Headers:

- `Authorization: Bearer <jwt>`
- `Content-Type: application/json`

Body:

```json
{
  "code": "A1B2C3",
  "device_name": "Samsung A54",
  "platform": "android"
}
```

## 3) Fis Upload (multipart/form-data)

`POST /api/mobile/receipts`

Headers:

- `Authorization: Bearer <jwt>`

Form fields:

- `file`: image/jpeg|png
- `device_id`: (optional, pairing response'undan gelen id)

Örnek cURL:

```bash
curl -X POST "https://YOUR_API/api/mobile/receipts" \
  -H "Authorization: Bearer <jwt>" \
  -F "file=@/path/to/receipt.jpg" \
  -F "device_id=<optional-device-id>"
```

## 4) Realtime Geri Besleme

Web dashboard websocket:

`GET /ws?token=<jwt>`

Yeni fiş geldiğinde event:

```json
{
  "event": "receipt.created",
  "receipt": {
    "id": "uuid",
    "evrak_no": "0001",
    "toplam": 660.0
  }
}
```

