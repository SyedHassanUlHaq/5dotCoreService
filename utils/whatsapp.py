"""
WhatsApp OTP delivery — blueprint only, not wired into any route yet.

Mirrors utils/email.py's send_otp_email(to, otp) shape so it can be dropped
into the signup/forgot-password flows later with minimal changes (e.g. branch
on whether the user provided a phone number vs. relying on email).

Uses Meta's WhatsApp Business Cloud API (the standard way to send templated
WhatsApp messages programmatically): https://developers.facebook.com/docs/whatsapp/cloud-api

To activate:
  1. Create a WhatsApp Business app in Meta for Developers, get a phone
     number ID and a permanent access token.
  2. Register and get approval for a message template (Meta requires
     pre-approved templates for business-initiated messages — you cannot
     send free-form text for OTPs). A minimal "otp_verification" template
     body looks like: "Your 5dot verification code is {{1}}. It expires in
     5 minutes." with one body variable and a copy-code button component.
  3. Set WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, and (optionally)
     WHATSAPP_OTP_TEMPLATE_NAME in .env — see config/project_config.py.
  4. Call send_otp_whatsapp(phone_number, otp) from wherever signup should
     branch to WhatsApp instead of (or in addition to) email.
"""

import requests

from config.project_config import (
    WHATSAPP_PHONE_NUMBER_ID, WHATSAPP_ACCESS_TOKEN, WHATSAPP_OTP_TEMPLATE_NAME,
)

WHATSAPP_API_VERSION = "v19.0"


def send_otp_whatsapp(phone_number: str, otp: str) -> None:
    """Send a 6-digit OTP to `phone_number` (E.164 format, e.g. +14155552671)
    via a pre-approved WhatsApp template message. Raises RuntimeError if
    WhatsApp isn't configured, and raises for any non-2xx response from Meta.
    """
    if not WHATSAPP_PHONE_NUMBER_ID or not WHATSAPP_ACCESS_TOKEN:
        raise RuntimeError(
            "WhatsApp OTP isn't configured — set WHATSAPP_PHONE_NUMBER_ID and "
            "WHATSAPP_ACCESS_TOKEN before calling send_otp_whatsapp()."
        )

    url = f"https://graph.facebook.com/{WHATSAPP_API_VERSION}/{WHATSAPP_PHONE_NUMBER_ID}/messages"
    payload = {
        "messaging_product": "whatsapp",
        "to": phone_number,
        "type": "template",
        "template": {
            "name": WHATSAPP_OTP_TEMPLATE_NAME,
            "language": {"code": "en_US"},
            "components": [
                {
                    "type": "body",
                    "parameters": [{"type": "text", "text": otp}],
                },
                # Templates with a "copy code" quick-reply button also need a
                # button component referencing the same code, e.g.:
                # {"type": "button", "sub_type": "url", "index": "0",
                #  "parameters": [{"type": "text", "text": otp}]},
            ],
        },
    }
    headers = {"Authorization": f"Bearer {WHATSAPP_ACCESS_TOKEN}"}

    resp = requests.post(url, json=payload, headers=headers, timeout=10)
    resp.raise_for_status()
