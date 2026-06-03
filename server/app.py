"""FastAPI application: web UI + REST API + Vapi webhooks.

Endpoints:
  GET  /                       -> the single-page voice UI
  GET  /api/config             -> public Vapi key for the browser SDK
  POST /api/claims             -> create a call session, returns {call_id}
  POST /api/claims/837         -> parse an uploaded 837, returns CallRequest JSON
  GET  /api/assistant/{id}     -> transient Vapi assistant config (browser passes
                                  this to vapi.start())
  GET  /api/results/{id}       -> final CallResult once the call ends
  POST /vapi/webhook           -> Vapi events (function-call, end-of-call-report)
"""

from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles

from server.config import get_settings
from server.edi import parse_837
from server.models import CallRequest
from server.session_store import store
from server.vapi_webhook import build_assistant_config, router as vapi_router

ROOT_DIR = Path(__file__).resolve().parent.parent
WEB_DIR = ROOT_DIR / "web"
DIST_DIR = WEB_DIR / "dist"  # Vite production build (preferred when present)

app = FastAPI(title="Claim Status Voice Agent")
app.include_router(vapi_router)

# Serve the built React SPA's hashed assets, if a production build exists.
if (DIST_DIR / "assets").is_dir():
    app.mount("/assets", StaticFiles(directory=DIST_DIR / "assets"), name="assets")


@app.get("/")
def index() -> FileResponse:
    # Prefer the built SPA; fall back to the no-build vanilla page.
    built = DIST_DIR / "index.html"
    return FileResponse(built if built.exists() else WEB_DIR / "index.html")


@app.get("/sample_claims.json")
def sample_claims() -> FileResponse:
    return FileResponse(ROOT_DIR / "sample_claims.json")


@app.get("/api/config")
def api_config() -> dict:
    return {"vapi_public_key": get_settings().vapi_public_key}


@app.post("/api/claims")
def create_claims(call_request: CallRequest) -> dict:
    session = store.create(call_request)
    return {"call_id": session.call_id}


@app.post("/api/claims/837")
async def parse_837_endpoint(payload: dict) -> dict:
    raw = payload.get("edi", "")
    if not raw:
        raise HTTPException(status_code=400, detail="Missing 'edi' text")
    claims = parse_837(raw)
    if not claims:
        raise HTTPException(status_code=422, detail="No claims found in 837")
    payer = payload.get("payer_name", "Unknown Payer")
    return CallRequest(payer_name=payer, claims=claims[:3]).model_dump()


@app.get("/api/assistant/{call_id}")
def assistant_config(call_id: str) -> dict:
    return build_assistant_config(call_id)


@app.get("/api/results/{call_id}")
def get_results(call_id: str) -> JSONResponse:
    result = store.get_result(call_id)
    if result is None:
        raise HTTPException(status_code=404, detail="Result not ready")
    return JSONResponse(result.model_dump())
