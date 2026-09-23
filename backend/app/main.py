import logging
import time
import uuid
from collections import defaultdict, deque
from contextlib import asynccontextmanager
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
from starlette.exceptions import HTTPException
from sqlalchemy import text
from app.core.config import settings
from app.db.database import SessionLocal
from app.api.routes import router
from app.integrations.google_calendar import router as google_router

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s %(message)s")
logger = logging.getLogger("scheduler")


@asynccontextmanager
async def lifespan(app):
    settings().validate_production()
    with SessionLocal() as db:
        db.execute(text("SELECT 1"))
    yield


app = FastAPI(title="Tempo · Personalized AI Scheduling", version="1.0.0", lifespan=lifespan)
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings().frontend_url],
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "PATCH", "DELETE"],
    allow_headers=["Content-Type", "X-Requested-With"],
)
app.include_router(router)
app.include_router(google_router)
requests_by_client = defaultdict(deque)


@app.middleware("http")
async def boundaries(request: Request, call_next):
    request_id = str(uuid.uuid4())
    origin = request.headers.get("origin")
    if request.method not in {"GET", "HEAD", "OPTIONS"}:
        if origin and origin != settings().frontend_url:
            return JSONResponse({"detail": "Origin not allowed"}, status_code=403)
        # Custom header prevents form-based and no-CORS cross-site requests even without Origin.
        if request.headers.get("x-requested-with") != "Tempo":
            return JSONResponse({"detail": "Missing request protection header"}, status_code=403)
    host = request.client.host if request.client else "unknown"
    category = (
        "auth"
        if request.url.path in {"/api/auth/login", "/api/auth/register"}
        else "agent"
        if request.url.path == "/api/agent/chat"
        else "api"
    )
    key = (host, category)
    now = time.monotonic()
    bucket = requests_by_client[key]
    while bucket and bucket[0] < now - 60:
        bucket.popleft()
    limit = {"auth": 15, "agent": 12}.get(category, settings().rate_limit_per_minute)
    if len(bucket) >= limit:
        return JSONResponse(
            {"detail": "Too many requests. Try again in a minute."}, 429, headers={"Retry-After": "60"}
        )
    bucket.append(now)
    if len(requests_by_client) > 10000:
        for old in list(requests_by_client):
            if not requests_by_client[old] or requests_by_client[old][-1] < now - 60:
                del requests_by_client[old]
    try:
        response = await call_next(request)
    except Exception:
        logger.exception("request_failed id=%s path=%s", request_id, request.url.path)
        response = JSONResponse({"detail": "An unexpected error occurred", "request_id": request_id}, 500)
    response.headers["X-Request-ID"] = request_id
    response.headers["X-Content-Type-Options"] = "nosniff"
    response.headers["Cache-Control"] = "no-store"
    logger.info(
        "request id=%s user=%s method=%s path=%s status=%s",
        request_id,
        getattr(request.state, "user_id", "anonymous"),
        request.method,
        request.url.path,
        response.status_code,
    )
    return response


@app.exception_handler(RequestValidationError)
async def validation_error(request, exc):
    # Avoid returning rejected input (which can contain passwords).
    return JSONResponse({"detail": [{"loc": e["loc"], "msg": e["msg"]} for e in exc.errors()]}, 422)


@app.exception_handler(HTTPException)
async def http_error(request, exc):
    return JSONResponse({"detail": exc.detail}, exc.status_code, headers=exc.headers)


@app.get("/api/health")
def health():
    with SessionLocal() as db:
        db.execute(text("SELECT 1 FROM users LIMIT 1"))
    return {"status": "ok", "ai_configured": bool(settings().openai_api_key and settings().ai_enabled)}
