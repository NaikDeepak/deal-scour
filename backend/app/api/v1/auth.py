from datetime import UTC, datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import BaseModel
from sqlmodel import Session, col, func, select

from app.core import clock
from app.core.config import Settings, get_settings
from app.core.db import current_user, get_session
from app.core.security import (
    clear_session_cookie,
    generate_login_code,
    generate_session_token,
    hash_invite_code,
    hash_login_code,
    hash_token,
    set_session_cookie,
    verify_csrf,
    verify_login_code,
)
from app.domain.models import AppUser, AuthSession, HouseholdMember, Invite, LoginCode
from app.notify.email import EmailSender, get_email_sender

router = APIRouter()

SettingsDep = Annotated[Settings, Depends(get_settings)]
SessionDep = Annotated[Session, Depends(get_session)]
EmailSenderDep = Annotated[EmailSender, Depends(get_email_sender)]
ClockDep = Annotated[datetime, Depends(clock.now)]


class RequestCodeRequest(BaseModel):
    email: str
    invite_code: str | None = None


class VerifyCodeRequest(BaseModel):
    email: str
    code: str
    invite_code: str | None = None
    name: str | None = None


class UserOut(BaseModel):
    id: int
    email: str
    name: str | None = None


class AuthOut(BaseModel):
    user: UserOut
    household_id: int
    role: str


@router.post("/auth/request-code", status_code=status.HTTP_202_ACCEPTED)
def request_code(
    req: RequestCodeRequest,
    session: SessionDep,
    settings: SettingsDep,
    sender: EmailSenderDep,
    now_dt: ClockDep,
) -> dict[str, bool]:
    email = req.email.strip().lower()

    # 1. Determine eligibility without account enumeration
    eligible = False
    existing_user = session.exec(select(AppUser).where(AppUser.email == email)).first()
    if existing_user is not None:
        eligible = True
    elif settings.owner_email and email == settings.owner_email:
        # Eligible if owner_email and no owner exists yet
        owner_member = session.exec(
            select(HouseholdMember).where(HouseholdMember.role == "owner")
        ).first()
        if owner_member is None:
            eligible = True
    elif req.invite_code:
        inv_hash = hash_invite_code(req.invite_code)
        inv = session.exec(
            select(Invite).where(Invite.code_hash == inv_hash, col(Invite.used_at).is_(None))
        ).first()
        if inv is not None:
            exp = inv.expires_at if inv.expires_at.tzinfo else inv.expires_at.replace(tzinfo=UTC)
            if exp > now_dt:
                eligible = True

    if not eligible:
        return {"sent": True}

    # 2. Rate limit: at most 5 codes per email per hour
    one_hour_ago = now_dt - timedelta(hours=1)
    count = session.exec(
        select(func.count(col(LoginCode.id))).where(
            LoginCode.email == email,
            LoginCode.created_at >= one_hour_ago,
        )
    ).one() or 0
    if count >= 5:
        return {"sent": True}

    # 3. Generate code and persist HMAC
    code = generate_login_code()
    code_hash = hash_login_code(email, code, settings.secret_key)
    login_code_row = LoginCode(
        email=email,
        code_hash=code_hash,
        expires_at=now_dt + timedelta(minutes=10),
        attempts=0,
        used_at=None,
        created_at=now_dt,
    )
    session.add(login_code_row)
    session.commit()

    sender.send_login_code(email, code)
    return {"sent": True}


@router.post("/auth/verify", response_model=AuthOut)
def verify(
    req: VerifyCodeRequest,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    now_dt: ClockDep,
) -> AuthOut:
    email = req.email.strip().lower()

    # Look up most recent unused login code for this email
    code_row = session.exec(
        select(LoginCode)
        .where(LoginCode.email == email, col(LoginCode.used_at).is_(None))
        .order_by(col(LoginCode.created_at).desc())
    ).first()

    if code_row is None:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        )

    # After 5 wrong attempts, the code is dead
    if code_row.attempts >= 5:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        )

    # Check expiry
    exp = code_row.expires_at if code_row.expires_at.tzinfo else code_row.expires_at.replace(tzinfo=UTC)
    if exp <= now_dt:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        )

    # Constant-time HMAC comparison
    if not verify_login_code(email, req.code, code_row.code_hash, settings.secret_key):
        code_row.attempts += 1
        session.add(code_row)
        session.commit()
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid or expired code",
        )

    # Valid! Mark code as used
    code_row.used_at = now_dt
    session.add(code_row)

    # User resolution or bootstrap
    user = session.exec(select(AppUser).where(AppUser.email == email)).first()
    household_id = 1
    role = "member"

    if user is None:
        if settings.owner_email and email == settings.owner_email:
            # Owner bootstrap
            user = AppUser(
                email=email,
                name=req.name,
                created_at=now_dt,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            assert user.id is not None
            household_id = 1
            role = "owner"
            session.add(
                HouseholdMember(household_id=household_id, user_id=user.id, role=role)
            )
            session.commit()
        elif req.invite_code:
            inv_hash = hash_invite_code(req.invite_code)
            invite = session.exec(
                select(Invite).where(Invite.code_hash == inv_hash, col(Invite.used_at).is_(None))
            ).first()
            if not invite:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired invite",
                )
            inv_exp = invite.expires_at if invite.expires_at.tzinfo else invite.expires_at.replace(tzinfo=UTC)
            if inv_exp <= now_dt:
                raise HTTPException(
                    status_code=status.HTTP_400_BAD_REQUEST,
                    detail="Invalid or expired invite",
                )
            user = AppUser(
                email=email,
                name=req.name,
                created_at=now_dt,
            )
            session.add(user)
            session.commit()
            session.refresh(user)
            assert user.id is not None
            household_id = invite.household_id
            role = "member"
            session.add(
                HouseholdMember(household_id=household_id, user_id=user.id, role=role)
            )
            invite.used_by = user.id
            invite.used_at = now_dt
            session.add(invite)
            session.commit()
        else:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Registration requires invite or owner email",
            )
    else:
        assert user.id is not None
        if req.name and not user.name:
            user.name = req.name
            session.add(user)
            session.commit()
        member = session.exec(
            select(HouseholdMember).where(HouseholdMember.user_id == user.id)
        ).first()
        if member:
            household_id = member.household_id
            role = member.role
        elif req.invite_code:
            inv_hash = hash_invite_code(req.invite_code)
            invite = session.exec(
                select(Invite).where(Invite.code_hash == inv_hash, col(Invite.used_at).is_(None))
            ).first()
            if invite:
                household_id = invite.household_id
                role = "member"
                session.add(
                    HouseholdMember(household_id=household_id, user_id=user.id, role=role)
                )
                invite.used_by = user.id
                invite.used_at = now_dt
                session.add(invite)
                session.commit()

    # Create session
    token = generate_session_token()
    token_h = hash_token(token)
    session_row = AuthSession(
        token_hash=token_h,
        user_id=user.id,
        created_at=now_dt,
        expires_at=now_dt + timedelta(days=30),
        last_seen_at=now_dt,
    )
    session.add(session_row)
    session.commit()

    set_session_cookie(response, token, settings.cookie_secure)
    return AuthOut(
        user=UserOut(id=user.id, email=user.email, name=user.name),
        household_id=household_id,
        role=role,
    )


CurrentUserDep = Annotated[AppUser, Depends(current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]


@router.post("/auth/logout")
def logout(
    request: Request,
    response: Response,
    session: SessionDep,
    settings: SettingsDep,
    user: CurrentUserDep,
    _csrf: CsrfDep,
) -> dict[str, bool]:
    user_sessions = session.exec(
        select(AuthSession).where(AuthSession.user_id == user.id)
    ).all()
    for s in user_sessions:
        session.delete(s)
    session.commit()
    clear_session_cookie(response, settings.cookie_secure)
    return {"ok": True}


@router.get("/auth/me", response_model=AuthOut)
def me(
    session: SessionDep,
    user: CurrentUserDep,
) -> AuthOut:
    member = session.exec(
        select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    ).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to any household",
        )
    assert user.id is not None
    return AuthOut(
        user=UserOut(id=user.id, email=user.email, name=user.name),
        household_id=member.household_id,
        role=member.role,
    )
