from typing import Literal

from pydantic import BaseModel, EmailStr

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

    class Config:
        from_attributes = True


class PersonaUpdate(BaseModel):
    persona: PersonaName


class Token(BaseModel):
    access_token: str
    token_type: str = "bearer"
