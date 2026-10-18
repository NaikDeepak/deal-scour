import sqlite3
from collections.abc import Generator
from datetime import UTC, datetime, timedelta
from functools import lru_cache
from pathlib import Path
from typing import Annotated, Any

from fastapi import Depends, HTTPException, Request, status
from sqlalchemy import event
from sqlalchemy.engine import Engine
from sqlmodel import Session, create_engine, select

from app.core import clock
from app.core.config import get_settings
from app.core.security import SESSION_COOKIE_NAME, hash_token, verify_csrf
from app.domain.models import AppUser, AuthSession, HouseholdMember


def _set_sqlite_pragma(dbapi_connection: Any, connection_record: Any) -> None:
    if isinstance(dbapi_connection, sqlite3.Connection):
        cursor = dbapi_connection.cursor()
        cursor.execute("PRAGMA foreign_keys=ON")
        cursor.execute("PRAGMA journal_mode=WAL")
        cursor.close()


def create_db_engine(db_path_or_url: Path | str | None = None) -> Engine:
    if db_path_or_url is None:
        settings = get_settings()
        settings.ensure_db_dir()
        url = settings.db_url
    elif isinstance(db_path_or_url, Path):
        url = f"sqlite:///{db_path_or_url.resolve()}"
    else:
        url = db_path_or_url

    eng = create_engine(
        url,
        connect_args={"check_same_thread": False},
    )
    event.listen(eng, "connect", _set_sqlite_pragma)
    return eng


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    # Created on first use, not at import: importing the app must not touch the filesystem.
    return create_db_engine()


def get_session() -> Generator[Session, None, None]:
    with Session(get_engine()) as session:
        yield session


SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]


def current_user(
    request: Request,
    session: SessionDep,
    now_dt: ClockDep,
) -> AppUser:
    """Extract authenticated AppUser from the ds_session cookie."""
    token = request.cookies.get(SESSION_COOKIE_NAME)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated",
        )
    token_hash = hash_token(token)
    stmt = select(AuthSession).where(AuthSession.token_hash == token_hash)
    auth_sess = session.exec(stmt).first()
    if not auth_sess:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid or expired session",
        )

    expires_at = auth_sess.expires_at
    if expires_at.tzinfo is None:
        expires_at = expires_at.replace(tzinfo=UTC)
    if expires_at <= now_dt:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Session expired",
        )

    last_seen = auth_sess.last_seen_at
    if last_seen.tzinfo is None:
        last_seen = last_seen.replace(tzinfo=UTC)
    if (now_dt - last_seen) > timedelta(hours=1):
        auth_sess.last_seen_at = now_dt
        session.add(auth_sess)
        session.commit()

    user = session.get(AppUser, auth_sess.user_id)
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="User not found",
        )
    return user


CurrentUserDep = Annotated[AppUser, Depends(current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]


def current_household_id(
    user: CurrentUserDep,
    session: SessionDep,
    _csrf: CsrfDep,
) -> int:
    """Return the household_id of the current authenticated user."""
    stmt = select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    member = session.exec(stmt).first()
    if not member:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="User does not belong to any household",
        )
    return member.household_id
