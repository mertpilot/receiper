# Receiper (Cloud/SaaS Edition)

Receiper, mobil cihazdan fiş tarayıp bulutta OCR eden ve sonuçları web dashboard'da "online Excel tablosu" gibi canlı gösteren bir sistemdir.

## Teknoloji Stack

- Backend API: FastAPI
- OCR: Tesseract + `parser.py` heuristics (korundu)
- DB: PostgreSQL (cloud) / SQLite (local fallback)
- Realtime: WebSocket
- Dashboard: HTML/CSS/JS + Export to Excel (SheetJS)
- Mobile entegrasyonu: JWT + multipart/form-data

## Klasor Yapisi

- `backend/app/`: Cloud backend (auth, db, api, websocket)
- `backend/parser.py`: OCR ve fiş parse logic (mevcut mantık)
- `backend/Dockerfile`: Render/PaaS deploy image
- `docker-compose.yml`: local app + postgres
- `render.yaml`: Render blueprint
- `docs/ARCHITECTURE_SAAS.md`: mimari haritası
- `docs/MOBILE_API.md`: mobil endpoint sözleşmesi

## Hızlı Başlangıç (Local)

### Seçenek A: Docker ile

```bash
docker compose up --build
```

Ardından:

- Dashboard: `http://localhost:8000`
- API Docs: `http://localhost:8000/docs`

### Seçenek B: Windows lokal script

1. Tesseract kur
2. `backend/requirements.txt` yükle
3. `./start.ps1` çalıştır

## Render Deploy

- `render.yaml` dosyası ile:
  - 1 web service (`receiper-api`)
  - 1 PostgreSQL DB (`receiper-db`)
- Render `DATABASE_URL` ve `JWT_SECRET` env'lerini otomatik bağlayabilir.

## Ana Endpointler

- `POST /api/auth/register`
- `POST /api/auth/login`
- `GET /api/auth/me`
- `POST /api/pairing-codes`
- `POST /api/mobile/pair`
- `POST /api/mobile/receipts`
- `GET /api/receipts`
- `GET /health`
- `WS /ws?token=<jwt>`

