import os
from contextlib import asynccontextmanager

from dotenv import load_dotenv
from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import JSONResponse
from starlette.middleware.sessions import SessionMiddleware

from admin import setup_admin
from api import auth, detection_request, detection_webhooks, feedback, notifications, payments, plans, stats, subscriptions, users, webhooks
from utils.errors import AppError

load_dotenv()


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


@app.exception_handler(AppError)
async def app_error_handler(_request: Request, exc: AppError):
    return JSONResponse(
        status_code=exc.status_code,
        content={"error": {"code": exc.code, "message": exc.message, "statusCode": exc.status_code}},
    )


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

setup_admin(app)


@app.get("/")
def root():
    return {"message": "5dot Core API running", "version": app.version}
