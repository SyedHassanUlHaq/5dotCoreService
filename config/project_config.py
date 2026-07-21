import os
from dotenv import load_dotenv

load_dotenv()

# --- Database ---
DATABASE_URL = os.getenv("DATABASE_URL")

# --- JWT ---
SECRET_KEY = os.getenv("SECRET_KEY")
REFRESH_SECRET_KEY = os.getenv("REFRESH_SECRET_KEY", os.getenv("SECRET_KEY"))
ALGORITHM = "HS256"
ACCESS_TOKEN_EXPIRE_MINUTES = 60
REFRESH_TOKEN_EXPIRE_DAYS = 30

# --- Email / OTP ---
OTP_EXPIRE_MINUTES = 5
SMTP_SERVER = os.getenv("SMTP_SERVER")
SMTP_PORT = int(os.getenv("SMTP_PORT", "587"))
SMTP_USER = os.getenv("SMTP_USER")
SMTP_PASSWORD = os.getenv("SMTP_PASSWORD")

# --- OAuth ---
GOOGLE_CLIENT_ID = os.getenv("GOOGLE_CLIENT_ID")
APPLE_CLIENT_ID = os.getenv("APPLE_CLIENT_ID")   # Bundle ID / Service ID
FACEBOOK_APP_ID = os.getenv("FACEBOOK_APP_ID")
FACEBOOK_APP_SECRET = os.getenv("FACEBOOK_APP_SECRET")
MICROSOFT_CLIENT_ID = os.getenv("MICROSOFT_CLIENT_ID")   # Azure AD app (client) ID — used for Outlook auth
MICROSOFT_TENANT_ID = os.getenv("MICROSOFT_TENANT_ID", "common")   # "common" allows personal + work/school accounts

# --- AWS S3 ---
AWS_ACCESS_KEY_ID = os.getenv("AWS_ACCESS_KEY_ID")
AWS_SECRET_ACCESS_KEY = os.getenv("AWS_SECRET_ACCESS_KEY")
AWS_REGION = os.getenv("AWS_REGION", "us-east-1")
AWS_BUCKET_NAME = os.getenv("AWS_BUCKET_NAME", "5dot-storage")
CDN_BASE_URL = os.getenv("CDN_BASE_URL", "")  # optional CloudFront domain

# --- Stripe ---
STRIPE_SECRET_KEY = os.getenv("STRIPE_SECRET_KEY")
STRIPE_WEBHOOK_SECRET = os.getenv("STRIPE_WEBHOOK_SECRET")

# --- In-App Purchase: Apple (required for App Store review — see api/subscriptions.py) ---
APPLE_ISSUER_ID = os.getenv("APPLE_ISSUER_ID")
APPLE_IAP_KEY_ID = os.getenv("APPLE_IAP_KEY_ID")
APPLE_IAP_PRIVATE_KEY_PATH = os.getenv("APPLE_IAP_PRIVATE_KEY_PATH")   # path to the .p8 key from App Store Connect
APPLE_ROOT_CERTS_DIR = os.getenv("APPLE_ROOT_CERTS_DIR")   # dir of Apple root CA .cer files
APPLE_ENVIRONMENT = os.getenv("APPLE_ENVIRONMENT", "Sandbox")   # "Sandbox" or "Production"
APPLE_PRODUCT_PRO = os.getenv("APPLE_PRODUCT_PRO")
APPLE_PRODUCT_TEAM = os.getenv("APPLE_PRODUCT_TEAM")

# --- In-App Purchase: Google Play (required for Play Store review — see api/subscriptions.py) ---
GOOGLE_PLAY_PACKAGE_NAME = os.getenv("GOOGLE_PLAY_PACKAGE_NAME")
GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_PATH = os.getenv("GOOGLE_PLAY_SERVICE_ACCOUNT_JSON_PATH")
GOOGLE_PLAY_PRODUCT_PRO = os.getenv("GOOGLE_PLAY_PRODUCT_PRO")
GOOGLE_PLAY_PRODUCT_TEAM = os.getenv("GOOGLE_PLAY_PRODUCT_TEAM")

# --- YouTube Data API (trending feed enrichment) ---
YOUTUBE_API_KEY = os.getenv("YOUTUBE_API_KEY")

# --- WhatsApp OTP (blueprint only, see utils/whatsapp.py — not wired to any route yet) ---
WHATSAPP_PHONE_NUMBER_ID = os.getenv("WHATSAPP_PHONE_NUMBER_ID")
WHATSAPP_ACCESS_TOKEN = os.getenv("WHATSAPP_ACCESS_TOKEN")
WHATSAPP_OTP_TEMPLATE_NAME = os.getenv("WHATSAPP_OTP_TEMPLATE_NAME", "otp_verification")

# --- Model metadata (surfaced in user/stats responses) ---
MODEL_VERSION = os.getenv("MODEL_VERSION", "v3.2")

# --- Plan limits ---
PLAN_SCAN_LIMITS: dict[str, int | None] = {
    "free": 50,
    "pro": 500,
    "team": None,   # unlimited
}
