from fastapi import APIRouter, Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy.orm import Session

from app.core.database import get_db
from app.core.security import create_access_token, decode_access_token, hash_password, verify_password
from app.models.user import User
from app.schemas.user import PersonaUpdate, Token, UserCreate, UserLogin, UserOut
from app.services import prefs as prefs_service
from app.services.onboarding import get_onboarding_status

router = APIRouter(prefix="/auth", tags=["auth"])
bearer_scheme = HTTPBearer()


def _user_out(user: User) -> UserOut:
    prefs = prefs_service.prefs_public(user)
    return UserOut(
        id=user.id,
        email=user.email,
        persona=user.persona if user.persona in ("eliseo", "elisse") else "eliseo",
        wake_name=prefs["wake_name"],
        display_name=prefs["display_name"],
        quiet_mode=prefs["quiet_mode"],
        confirm_sends=prefs["confirm_sends"],
        meeting_mode=prefs["meeting_mode"],
        speak_slow=prefs["speak_slow"],
    )


@router.post("/register", response_model=UserOut, status_code=status.HTTP_201_CREATED)
def register(data: UserCreate, db: Session = Depends(get_db)):
    existing = db.query(User).filter(User.email == data.email).first()
    if existing:
        raise HTTPException(status_code=400, detail="Ese email ya está registrado.")

    user = User(email=data.email, hashed_password=hash_password(data.password))
    db.add(user)
    db.commit()
    db.refresh(user)
    return _user_out(user)


@router.post("/login", response_model=Token)
def login(data: UserLogin, db: Session = Depends(get_db)):
    user = db.query(User).filter(User.email == data.email).first()
    if not user or not verify_password(data.password, user.hashed_password):
        raise HTTPException(status_code=401, detail="Email o contraseña incorrectos.")

    token = create_access_token(user.id)
    return Token(access_token=token)


def get_current_user(
    credentials: HTTPAuthorizationCredentials = Depends(bearer_scheme),
    db: Session = Depends(get_db),
) -> User:
    """Dependency para proteger rutas: valida el JWT y devuelve el usuario."""
    user_id = decode_access_token(credentials.credentials)
    if user_id is None:
        raise HTTPException(status_code=401, detail="Token inválido o expirado.")

    user = db.query(User).filter(User.id == user_id).first()
    if user is None:
        raise HTTPException(status_code=401, detail="Usuario no encontrado.")

    return user


@router.get("/me", response_model=UserOut)
def me(current_user: User = Depends(get_current_user)):
    return _user_out(current_user)


@router.patch("/me", response_model=UserOut)
def update_me(
    data: PersonaUpdate,
    current_user: User = Depends(get_current_user),
    db: Session = Depends(get_db),
):
    if data.persona is not None:
        current_user.persona = data.persona
    if data.clear_wake_name:
        current_user.wake_name = None
    elif data.wake_name is not None:
        raw = data.wake_name.strip()
        current_user.wake_name = raw[:40] if raw else None
    if data.quiet_mode is not None:
        current_user.quiet_mode = data.quiet_mode
    if data.confirm_sends is not None:
        current_user.confirm_sends = data.confirm_sends
    if data.speak_slow is not None:
        current_user.speak_slow = data.speak_slow
    db.add(current_user)
    db.commit()
    db.refresh(current_user)
    return _user_out(current_user)


@router.get("/onboarding")
def onboarding(current_user: User = Depends(get_current_user), db: Session = Depends(get_db)):
    status_payload = get_onboarding_status(db, current_user.id)
    # Primera vez: sugerir elegir nombre si no tiene wake_name
    if not (current_user.wake_name or "").strip():
        status_payload = {
            **status_payload,
            "ask_wake_name": True,
            "guide": (
                status_payload.get("guide")
                + " También podés decirme cómo querés llamarme, aunque la app siga siendo Eliseo."
            ),
        }
    else:
        status_payload = {**status_payload, "ask_wake_name": False}
    return status_payload
