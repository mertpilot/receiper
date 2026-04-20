from __future__ import annotations

from contextlib import asynccontextmanager
from datetime import datetime, timezone
from pathlib import Path

from fastapi import FastAPI, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from .auth import decode_access_token
from .config import get_settings
from .database import Base, SessionLocal, engine
from .models import User
from .realtime import ws_manager
from .routers import auth, mobile, pairing, receipts


settings = get_settings()
STATIC_DIR = Path(__file__).resolve().parent / "static"


@asynccontextmanager
async def lifespan(_: FastAPI):
    Path(settings.upload_root).mkdir(parents=True, exist_ok=True)
    Base.metadata.create_all(bind=engine)
    yield


app = FastAPI(title=settings.app_name, lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.allowed_origins,
    allow_credentials=False,
    allow_methods=["*"],
    allow_headers=["*"],
)

app.mount("/static", StaticFiles(directory=STATIC_DIR), name="static")

app.include_router(auth.router)
app.include_router(pairing.router)
app.include_router(receipts.router)
app.include_router(mobile.router)


@app.get("/")
def dashboard():
    return FileResponse(STATIC_DIR / "dashboard.html")


@app.get("/mobile-test")
def mobile_test():
    return FileResponse(STATIC_DIR / "mobile-client.html")


@app.get("/health")
def health():
    return JSONResponse(
        {
            "status": "ok",
            "service": settings.app_name,
            "env": settings.environment,
            "time_utc": datetime.now(timezone.utc).isoformat(),
        }
    )


@app.websocket("/ws")
async def ws_endpoint(websocket: WebSocket):
    token = websocket.query_params.get("token", "")
    if not token:
        await websocket.close(code=4401, reason="Token gerekli")
        return

    try:
        payload = decode_access_token(token)
        user_id = payload.get("sub")
        if not user_id:
            raise ValueError("Token sub missing")
    except Exception:
        await websocket.close(code=4401, reason="Token gecersiz")
        return

    with SessionLocal() as db:
        user = db.get(User, user_id)
    if not user:
        await websocket.close(code=4401, reason="Kullanici bulunamadi")
        return

    await ws_manager.connect(user_id, websocket)
    await websocket.send_json({"event": "ws.ready", "user_id": user_id})

    try:
        while True:
            message = await websocket.receive_text()
            if message.lower() == "ping":
                await websocket.send_json({"event": "pong"})
    except WebSocketDisconnect:
        await ws_manager.disconnect(user_id, websocket)
    except Exception:
        await ws_manager.disconnect(user_id, websocket)
        await websocket.close(code=1011)
