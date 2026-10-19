import hashlib
import hmac
import secrets
from datetime import datetime
from typing import Annotated

from fastapi import Depends, HTTPException, Request, status
from sqlmodel import Session, col, select

from app.core import clock
from app.core.db import get_session
from app.domain.models import RadarExtensionToken

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


def generate_extension_token() -> str:
    """Create a random 32-byte urlsafe extension bearer token."""
    return secrets.token_urlsafe(32)


def hash_extension_token(token: str) -> str:
    """Compute SHA-256 hex digest of an extension token."""
    return hashlib.sha256(token.strip().encode()).hexdigest()


def issue_extension_token(
    session: Session,
    household_id: int,
    now_dt: datetime,
) -> tuple[str, RadarExtensionToken]:
    """Revoke any existing active tokens for household_id and issue a new one."""
    active = session.exec(
        select(RadarExtensionToken).where(
            RadarExtensionToken.household_id == household_id,
            col(RadarExtensionToken.revoked).is_(False),
        )
    ).all()
    for existing in active:
        existing.revoked = True
        session.add(existing)

    raw_token = generate_extension_token()
    row = RadarExtensionToken(
        household_id=household_id,
        token_hash=hash_extension_token(raw_token),
        created_at=now_dt,
        last_used_at=None,
        revoked=False,
    )
    session.add(row)
    session.commit()
    session.refresh(row)
    return raw_token, row


def verify_extension_bearer_token(
    auth_header: str | None,
    session: Session,
    now_dt: datetime,
) -> int:
    """Validate Authorization: Bearer <token> using constant-time hash comparison.

    Returns the household_id or raises 401. Never accepts session cookies.
    """
    if not auth_header:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing Authorization Bearer token",
        )
    scheme, _, raw_token = auth_header.partition(" ")
    if scheme.lower() != "bearer" or not raw_token.strip():
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid Authorization header format",
        )

    candidate_hash = hash_extension_token(raw_token)
    active_tokens = session.exec(
        select(RadarExtensionToken).where(col(RadarExtensionToken.revoked).is_(False))
    ).all()

    matched: RadarExtensionToken | None = None
    for row in active_tokens:
        if hmac.compare_digest(row.token_hash, candidate_hash):
            matched = row

    if matched is None or matched.revoked:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or revoked extension token",
        )

    matched.last_used_at = now_dt
    session.add(matched)
    session.commit()
    return matched.household_id


def extension_household_id(
    request: Request,
    session: SessionDep,
    now_dt: ClockDep,
) -> int:
    """FastAPI dependency accepting ONLY Authorization: Bearer <token>."""
    return verify_extension_bearer_token(
        request.headers.get("Authorization"),
        session,
        now_dt,
    )


ExtensionHouseholdIdDep = Annotated[int, Depends(extension_household_id)]
