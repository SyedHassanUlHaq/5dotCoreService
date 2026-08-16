import logging
import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.exceptions import RequestValidationError
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from sqlalchemy.exc import IntegrityError
from starlette.exceptions import HTTPException as StarletteHTTPException
from starlette.middleware.sessions import SessionMiddleware

from admin import setup_admin
from api import auth, crash_reports, detection_request, detection_webhooks, feedback, notifications, payments, plans, stats, subscriptions, users, webhooks
from utils.errors import AppError

load_dotenv()

logging.basicConfig(
    level=os.getenv("LOG_LEVEL", "INFO"),
    format="%(asctime)s %(levelname)s %(name)s: %(message)s",
)
logger = logging.getLogger(__name__)


@asynccontextmanager
async def lifespan(_app: FastAPI):
    yield
    print("[*] Core service shutdown")


app = FastAPI(title="5dot Core API", version="1.0", lifespan=lifespan)

app.add_middleware(SessionMiddleware, secret_key=os.getenv("SESSION_SECRET_KEY", "super-secret-key"))
app.add_middleware(
    CORSMiddleware,
    allow_origins=os.getenv("ALLOWED_ORIGINS", "*").split(","),
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _error_response(status_code: int, code: str, message: str) -> JSONResponse:
    return JSONResponse(
        status_code=status_code,
        content={"error": {"code": code, "message": message, "statusCode": status_code}},
    )


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    return _error_response(exc.status_code, exc.code, exc.message)


@app.exception_handler(RequestValidationError)
async def validation_error_handler(_request: Request, exc: RequestValidationError):
    first = exc.errors()[0] if exc.errors() else None
    if first:
        field = ".".join(str(p) for p in first["loc"] if p != "body")
        message = f"{field}: {first['msg']}" if field else first["msg"]
    else:
        message = "Invalid request."
    return _error_response(422, "VALIDATION_ERROR", message)


@app.exception_handler(StarletteHTTPException)
async def http_exception_handler(_request: Request, exc: StarletteHTTPException):
    return _error_response(exc.status_code, "HTTP_ERROR", str(exc.detail))


@app.exception_handler(IntegrityError)
async def integrity_error_handler(request: Request, exc: IntegrityError):
    logger.warning("Integrity error on %s %s: %s", request.method, request.url.path, exc)
    return _error_response(409, "CONFLICT", "The request conflicts with existing data.")


@app.exception_handler(Exception)
async def unhandled_exception_handler(request: Request, exc: Exception):
    logger.error("Unhandled error on %s %s", request.method, request.url.path, exc_info=exc)
    return _error_response(500, "SERVER_ERROR", "Something went wrong. Please try again.")


# Routes
app.include_router(auth.router,          prefix="/v1/auth",          tags=["Auth"])
app.include_router(users.router,         prefix="/v1/users",         tags=["Users"])
app.include_router(detection_request.router,         prefix="/v1/scans",         tags=["Scans"])
app.include_router(feedback.router,      prefix="/v1/feedback",      tags=["Feedback"])
app.include_router(notifications.router, prefix="/v1/notifications", tags=["Notifications"])
app.include_router(plans.router,         prefix="/v1/plans",         tags=["Plans"])
app.include_router(subscriptions.router, prefix="/v1/subscriptions", tags=["Subscriptions"])
app.include_router(stats.router,         prefix="/v1/stats",         tags=["Stats"])
app.include_router(webhooks.router,      prefix="/v1/webhooks",      tags=["Webhooks"])
app.include_router(detection_webhooks.router, prefix="/v1/webhooks", tags=["Webhooks"])
app.include_router(payments.router,      prefix="/v1",              tags=["Payments"])
app.include_router(crash_reports.router, prefix="/v1/crash-reports", tags=["Crash reports"])

setup_admin(app)


@app.get("/")
def root():
    return {"message": "5dot Core API running", "version": app.version}
