from pydantic import BaseModel, EmailStr, field_validator

class PaymentIntentCreate(BaseModel):
    amount: int
    user_id: str
    order_id: str

class UserCreate(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, confirm_password, info):
        password = info.data.get("password")
        if password != confirm_password:
            raise ValueError("Passwords do not match")
        return confirm_password


class UserResponse(BaseModel):
    id: int
    first_name: str
    last_name: str
    email: EmailStr

    class Config:
        from_attributes = True
        
class UserLogin(BaseModel):
    email: EmailStr
    password: str


class Token(BaseModel):
    access_token: str
    token_type: str
    
class OTPRequest(BaseModel):
    first_name: str
    last_name: str
    email: EmailStr
    password: str
    confirm_password: str

class OTPVerify(BaseModel):
    email: EmailStr
    otp: str
    
class ResetPasswordRequest(BaseModel):
    email: EmailStr

class ResetPasswordVerify(BaseModel):
    email: EmailStr
    otp: str
    new_password: str
    confirm_password: str

    @field_validator("confirm_password")
    @classmethod
    def passwords_match(cls, confirm_password, info):
        password = info.data.get("new_password")
        if password != confirm_password:
            raise ValueError("Passwords do not match")
        return confirm_password