from pydantic import BaseModel, EmailStr


class SignUpRequest(BaseModel):
    email: EmailStr
    password: str


class SignInRequest(BaseModel):
    email: EmailStr
    password: str


class GoogleAuthRequest(BaseModel):
    idToken: str


class AppleAuthRequest(BaseModel):
    identityToken: str
    fullName: dict | None = None   # {"givenName": "...", "familyName": "..."}


class FacebookAuthRequest(BaseModel):
    accessToken: str   # user access token from the Facebook Login SDK


class OutlookAuthRequest(BaseModel):
    idToken: str   # Microsoft identity platform (Azure AD) id_token, JWT


class RefreshRequest(BaseModel):
    refreshToken: str


class ForgotPasswordRequest(BaseModel):
    email: EmailStr


class ResetPasswordRequest(BaseModel):
    email: EmailStr
    otp: str
    newPassword: str
