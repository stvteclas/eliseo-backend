from typing import Literal

from pydantic import BaseModel, EmailStr, Field

PersonaName = Literal["eliseo", "elisse"]


class UserCreate(BaseModel):
    email: EmailStr
    password: str


class UserLogin(BaseModel):
    email: EmailStr
    password: str


class UserOut(BaseModel):
    id: int
    email: EmailStr
    persona: PersonaName = "eliseo"
    wake_name: str | None = None
    display_name: str = "Eliseo"
    quiet_mode: bool = False
    confirm_sends: bool = False
    meeting_mode: bool = False
    speak_slow: bool = False

    class Config:
        from_attributes = True


class PersonaUpdate(BaseModel):
    """PATCH /auth/me — campos opcionales."""

    persona: PersonaName | None = None
    wake_name: str | None = Field(default=None, max_length=40)
    quiet_mode: bool | None = None
    confirm_sends: bool | None = None
    speak_slow: bool | None = None
    clear_wake_name: bool = False


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
