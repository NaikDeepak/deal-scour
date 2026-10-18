from datetime import datetime, timedelta
from typing import Annotated

from fastapi import APIRouter, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, col, select

from app.core import clock
from app.core.db import current_user, get_session
from app.core.security import generate_invite_code, hash_invite_code, verify_csrf
from app.domain.models import AppUser, AuthSession, HouseholdMember, Invite

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]
CurrentUserDep = Annotated[AppUser, Depends(current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]


class InviteOut(BaseModel):
    invite_code: str
    expires_at: datetime


class MemberOut(BaseModel):
    user_id: int
    email: str
    name: str | None = None
    role: str


@router.post(
    "/households/invites",
    response_model=InviteOut,
    status_code=status.HTTP_201_CREATED,
)
def create_invite(
    session: SessionDep,
    now_dt: ClockDep,
    user: CurrentUserDep,
    _csrf: CsrfDep,
) -> InviteOut:
    mem = session.exec(
        select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    ).first()
    if not mem or mem.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner permission required",
        )

    assert user.id is not None
    code = generate_invite_code()
    code_hash = hash_invite_code(code)
    expires_at = now_dt + timedelta(days=7)

    invite = Invite(
        code_hash=code_hash,
        household_id=mem.household_id,
        created_by=user.id,
        expires_at=expires_at,
    )
    session.add(invite)
    session.commit()

    return InviteOut(invite_code=code, expires_at=expires_at)


@router.get("/households/members", response_model=list[MemberOut])
def list_members(
    session: SessionDep,
    user: CurrentUserDep,
) -> list[MemberOut]:
    mem = session.exec(
        select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    ).first()
    if not mem:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to any household",
        )

    stmt = (
        select(HouseholdMember, AppUser)
        .join(AppUser, col(HouseholdMember.user_id) == col(AppUser.id))
        .where(HouseholdMember.household_id == mem.household_id)
    )
    results = session.exec(stmt).all()
    out: list[MemberOut] = []
    for member_row, user_row in results:
        assert user_row.id is not None
        out.append(
            MemberOut(
                user_id=user_row.id,
                email=user_row.email,
                name=user_row.name,
                role=member_row.role,
            )
        )
    return out


@router.delete("/households/members/{user_id}")
def remove_member(
    user_id: int,
    session: SessionDep,
    user: CurrentUserDep,
    _csrf: CsrfDep,
) -> dict[str, bool]:
    mem = session.exec(
        select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    ).first()
    if not mem or mem.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner permission required",
        )

    if user_id == user.id:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Owner cannot remove themselves",
        )

    target_mem = session.exec(
        select(HouseholdMember).where(
            HouseholdMember.household_id == mem.household_id,
            HouseholdMember.user_id == user_id,
        )
    ).first()
    if not target_mem:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail="Member not found in household",
        )

    session.delete(target_mem)

    # Delete all sessions for the removed user
    user_sessions = session.exec(
        select(AuthSession).where(AuthSession.user_id == user_id)
    ).all()
    for s in user_sessions:
        session.delete(s)

    session.commit()
    return {"ok": True}
