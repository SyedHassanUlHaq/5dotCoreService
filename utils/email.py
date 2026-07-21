import os
import random
from email.message import EmailMessage
from typing import Literal
import aiosmtplib
from dotenv import load_dotenv
from config.project_config import SMTP_SERVER, SMTP_PORT, SMTP_USER, SMTP_PASSWORD

load_dotenv()

OtpPurpose = Literal["signup", "reset"]

_COPY: dict[OtpPurpose, dict[str, str]] = {
    "signup": {
        "subject": "Verify your email for 5dot",
        "intro": "Enter this code to verify your email and finish creating your account. It expires in 5 minutes.",
        "footer": "If you didn't create a 5dot account, you can safely ignore this email.",
    },
    "reset": {
        "subject": "Your 5dot verification code",
        "intro": "Enter this code to reset your password. It expires in 5 minutes.",
        "footer": "If you didn't request this, you can safely ignore this email — your password won't be changed.",
    },
}

def generate_otp(length: int = 6) -> str:
    return str(random.randint(10**(length-1), 10**length - 1))

def _otp_email_html(otp: str, purpose: OtpPurpose) -> str:
    copy = _COPY[purpose]
    return f"""\
<!DOCTYPE html>
<html>
  <head>
    <meta charset="utf-8" />
    <meta name="viewport" content="width=device-width, initial-scale=1.0" />
    <title>{copy["subject"]}</title>
  </head>
  <body style="margin:0; padding:0; background-color:#F2F2F7; font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, Helvetica, Arial, sans-serif;">
    <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="background-color:#F2F2F7;">
      <tr>
        <td align="center" style="padding: 40px 16px;">
          <table role="presentation" width="100%" cellpadding="0" cellspacing="0" style="max-width:420px; background-color:#FFFFFF; border-radius:20px; overflow:hidden; box-shadow:0 2px 12px rgba(0,0,0,0.06);">
            <tr>
              <td style="background-color:#C0376B; background-image:linear-gradient(135deg, #C0376B, #7C3AED); padding:28px 32px;">
                <span style="display:inline-block; width:8px; height:8px; border-radius:4px; background-color:#52A87C; margin-right:8px; vertical-align:middle;">&nbsp;</span>
                <span style="color:#FFFFFF; font-size:15px; font-weight:700; vertical-align:middle; letter-spacing:0.2px;">5dot</span>
              </td>
            </tr>
            <tr>
              <td style="padding:32px;">
                <p style="margin:0 0 8px; font-size:22px; font-weight:800; color:#000000;">Verify it's you</p>
                <p style="margin:0 0 24px; font-size:15px; color:#6B7280; line-height:22px;">
                  {copy["intro"]}
                </p>
                <div style="background-color:#F2F2F7; border-radius:14px; padding:22px; text-align:center; margin-bottom:24px;">
                  <span style="font-size:34px; font-weight:800; letter-spacing:10px; color:#C0376B; font-family: 'Courier New', Courier, monospace;">{otp}</span>
                </div>
                <p style="margin:0; font-size:13px; color:#9CA3AF; line-height:19px;">
                  {copy["footer"]}
                </p>
              </td>
            </tr>
            <tr>
              <td style="padding:20px 32px; border-top:1px solid #E5E7EB;">
                <p style="margin:0; font-size:12px; color:#9CA3AF;">5dot &middot; AI-generated content detection</p>
              </td>
            </tr>
          </table>
        </td>
      </tr>
    </table>
  </body>
</html>
"""

async def send_otp_email(to_email: str, otp: str, purpose: OtpPurpose = "reset"):
    copy = _COPY[purpose]
    message = EmailMessage()
    message["From"] = SMTP_USER
    message["To"] = to_email
    message["Subject"] = copy["subject"]
    message.set_content(f"Your 5dot verification code is: {otp}\nIt will expire in 5 minutes.")
    message.add_alternative(_otp_email_html(otp, purpose), subtype="html")

    await aiosmtplib.send(
        message,
        hostname=SMTP_SERVER,
        port=SMTP_PORT,
        start_tls=True,
        username=SMTP_USER,
        password=SMTP_PASSWORD,
    )
