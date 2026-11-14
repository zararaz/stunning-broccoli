"""Production entry point: the HTTP API and the web UI in one process.

    uvicorn server:app --host 0.0.0.0 --port 7860

Routes:
    GET  /health      is it up, and what is it serving? (no login, for the host's health checks)
    POST /api/chat    {"message": "...", "user_id": "..."} -> {"request_id": "...", "reply": "..."}
    GET  /api/docs    interactive API documentation
    /                 the web chat UI

Configuration comes from environment variables (see src/settings.py).
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent / "src"))

import gradio as gr  # noqa: E402
from fastapi import FastAPI, Request  # noqa: E402
from fastapi.responses import JSONResponse  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import settings  # noqa: E402
from app import build_demo  # noqa: E402
from service import ChatError, ChatService, basic_auth_user, client_key, log_event, setup_logging  # noqa: E402

setup_logging()
service = ChatService()                      # loads data, vectors and models once, at startup
log_event("startup", **service.info())

api = FastAPI(title="City guide", docs_url="/api/docs", openapi_url="/api/openapi.json")


@api.middleware("http")
async def login_required(request: Request, call_next):
    """With CITY_GUIDE_USERS set, every route except /health needs a login.
    The browser shows its own login box and resends the login on every request."""
    if settings.USERS and request.url.path != "/health":
        if basic_auth_user(request.headers.get("authorization")) is None:
            return JSONResponse({"error": "login required"}, status_code=401,
                                headers={"WWW-Authenticate": 'Basic realm="city-guide"'})
    return await call_next(request)


@api.get("/health")
def health():
    service.engine.con.execute("SELECT 1 FROM businesses LIMIT 1")   # the data is really readable
    return {"status": "ok", **service.info()}


class ChatIn(BaseModel):
    message: str
    user_id: str = "anonymous"


@api.post("/api/chat")
def chat(body: ChatIn, request: Request):
    login = basic_auth_user(request.headers.get("authorization"))
    ip = request.client.host if request.client else None
    try:
        out, _ = service.chat(body.message, login or body.user_id, client_key(login, ip))
        return out
    except ChatError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


# The web UI at /: the same page as `python app.py`, sharing this process's service.
app = gr.mount_gradio_app(api, build_demo(service, full_trace=settings.DEBUG_TRACE), path="/")
