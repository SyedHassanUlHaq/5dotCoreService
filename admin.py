import os
import secrets

from fastapi import FastAPI
from sqladmin import Admin, ModelView
from sqladmin.authentication import AuthenticationBackend
from starlette.requests import Request

from database import engine
from models.chunk import Chunk
from models.detection_request import DetectionRequest
from models.feedback import Feedback
from models.notification import Notification
from models.payments import Payment
from models.refresh_token import RefreshToken
from models.subscription import Subscription
from models.user import User

ADMIN_USERNAME = os.getenv("ADMIN_USERNAME", "")
ADMIN_PASSWORD = os.getenv("ADMIN_PASSWORD", "")


class AdminAuth(AuthenticationBackend):
    async def login(self, request: Request) -> bool:
        form = await request.form()
        username = form.get("username", "")
        password = form.get("password", "")

        if not ADMIN_USERNAME or not ADMIN_PASSWORD:
            return False
        if not (secrets.compare_digest(username, ADMIN_USERNAME) and secrets.compare_digest(password, ADMIN_PASSWORD)):
            return False

        request.session.update({"admin_authenticated": True})
        return True

    async def logout(self, request: Request) -> bool:
        request.session.clear()
        return True

    async def authenticate(self, request: Request) -> bool:
        return bool(request.session.get("admin_authenticated"))


class UserAdmin(ModelView, model=User):
    column_list = "__all__"
    form_excluded_columns = [User.payments, User.refresh_tokens, User.scans, User.feedback, User.subscription, User.notifications]


class PaymentAdmin(ModelView, model=Payment):
    column_list = "__all__"


class RefreshTokenAdmin(ModelView, model=RefreshToken):
    column_list = "__all__"


class DetectionRequestAdmin(ModelView, model=DetectionRequest):
    column_list = "__all__"
    form_excluded_columns = [DetectionRequest.chunks, DetectionRequest.feedback]


class ChunkAdmin(ModelView, model=Chunk):
    column_list = "__all__"


class FeedbackAdmin(ModelView, model=Feedback):
    column_list = "__all__"


class SubscriptionAdmin(ModelView, model=Subscription):
    column_list = "__all__"


class NotificationAdmin(ModelView, model=Notification):
    column_list = "__all__"


def setup_admin(app: FastAPI) -> Admin:
    secret_key = os.getenv("SESSION_SECRET_KEY", "super-secret-key")
    admin = Admin(app, engine, authentication_backend=AdminAuth(secret_key=secret_key))

    for view in (
        UserAdmin,
        PaymentAdmin,
        RefreshTokenAdmin,
        DetectionRequestAdmin,
        ChunkAdmin,
        FeedbackAdmin,
        SubscriptionAdmin,
        NotificationAdmin,
    ):
        admin.add_view(view)

    return admin
