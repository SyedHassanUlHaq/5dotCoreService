from datetime import datetime, timedelta
from typing import Dict
from config.project_config import OTP_EXPIRE_MINUTES

otp_store: Dict[str, dict] = {}
# Structure:
# otp_store[email] = {
#     "otp": "123456",
#     "data": {first_name, last_name, email, password},
#     "expires_at": datetime
# }

def store_otp(email: str, otp: str, user_data: dict):
    otp_store[email] = {
        "otp": otp,
        "data": user_data,
        "expires_at": datetime.utcnow() + timedelta(minutes=OTP_EXPIRE_MINUTES)
    }

def verify_otp(email: str, otp: str):
    record = otp_store.get(email)
    if not record:
        return False, "No OTP found for this email"
    if datetime.utcnow() > record["expires_at"]:
        del otp_store[email]
        return False, "OTP expired"
    if record["otp"] != otp:
        return False, "Invalid OTP"
    return True, record["data"]

def delete_otp(email: str):
    if email in otp_store:
        del otp_store[email]