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
from service import ChatError, ChatService, basic_auth_user, log_event, setup_logging  # noqa: E402

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


def client_key(request, user):
    """Rate-limit by logged-in user, else by IP address."""
    if user:
        return f"user:{user}"
    return f"ip:{request.client.host}" if request and request.client else "unknown"


@api.post("/api/chat")
def chat(body: ChatIn, request: Request):
    user = basic_auth_user(request.headers.get("authorization"))
    try:
        out, _ = service.chat(body.message, user or body.user_id, client_key(request, user))
        return out
    except ChatError as e:
        return JSONResponse({"error": e.message}, status_code=e.status)


def ui_handle(message, user_id, backend, request):
    user = basic_auth_user(request.headers.get("authorization")) if request else None
    try:
        out, trace = service.chat(message, user or user_id, client_key(request, user))
    except ChatError as e:
        return e.message, {"error": e.message}
    if settings.DEBUG_TRACE:
        return out["reply"], trace
    return out["reply"], {"request_id": out["request_id"], "mode": trace["request"]["mode"],
                          "search": trace["search_method"], "timings": trace["timings"]}


demo = build_demo(ui_handle, backends=(service.info()["llm"],), show_user=not settings.USERS)
app = gr.mount_gradio_app(api, demo, path="/")
