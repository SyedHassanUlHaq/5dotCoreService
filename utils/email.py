import os
import random
from email.message import EmailMessage
import aiosmtplib
from dotenv import load_dotenv
from config.project_config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

load_dotenv()

def generate_otp(length: int = 6) -> str:
    return str(random.randint(10**(length-1), 10**length - 1))

async def send_otp_email(to_email: str, otp: str):
    message = EmailMessage()
    message["From"] = SMTP_USER
    message["To"] = to_email
    message["Subject"] = "Your OTP Code"
    message.set_content(f"Your OTP code is: {otp}\nIt will expire in 5 minutes.")

    await aiosmtplib.send(
        message,
        hostname=SMTP_SERVER,
        port=SMTP_PORT,
        start_tls=True,
        username=SMTP_USER,
        password=SMTP_PASSWORD,
    )