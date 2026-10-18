import logging
import threading
import time
from datetime import UTC, datetime
from typing import Annotated

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, status
from pydantic import BaseModel
from sqlmodel import Session, select

from app.core import clock
from app.core.config import get_settings
from app.core.db import current_user, get_engine, get_session
from app.core.security import verify_csrf
from app.domain.models import AppUser, HouseholdMember, SourceStatus
from app.sources.fetcher import fetch_url, get_due_listings, refresh_due_listings

logger = logging.getLogger(__name__)

router = APIRouter()

SessionDep = Annotated[Session, Depends(get_session)]
ClockDep = Annotated[datetime, Depends(clock.now)]
CurrentUserDep = Annotated[AppUser, Depends(current_user)]
CsrfDep = Annotated[None, Depends(verify_csrf)]

_in_progress_households: set[int] = set()
_lock = threading.Lock()


class PlatformStatusOut(BaseModel):
    platform: str
    enabled_by_config: bool
    consecutive_failures: int
    disabled_until: datetime | None = None
    last_success_at: datetime | None = None
    last_error: str | None = None


class SourcesStatusResponse(BaseModel):
    platforms: list[PlatformStatusOut]
    quick_commerce: str = "manual only (blocked by the sites)"


class RefreshQueuedResponse(BaseModel):
    queued: int


def _run_refresh_task(household_id: int, interval_hours: int) -> None:
    try:
        with Session(get_engine()) as session:
            refresh_due_listings(
                session,
                household_id,
                http_get=fetch_url,
                now=lambda: datetime.now(UTC),
                sleep=time.sleep,
                interval_hours=interval_hours,
            )
    except Exception:
        logger.exception("Background refresh failed for household %s", household_id)
    finally:
        with _lock:
            _in_progress_households.discard(household_id)


@router.get("/sources/status", response_model=SourcesStatusResponse)
def get_sources_status(
    session: SessionDep,
    _user: CurrentUserDep,
) -> SourcesStatusResponse:
    settings = get_settings()
    platforms_out: list[PlatformStatusOut] = []

    for platform_name in ("amazon", "flipkart"):
        st = session.get(SourceStatus, platform_name)
        if st is not None:
            platforms_out.append(
                PlatformStatusOut(
                    platform=platform_name,
                    enabled_by_config=settings.fetchers_enabled,
                    consecutive_failures=st.consecutive_failures,
                    disabled_until=st.disabled_until,
                    last_success_at=st.last_success_at,
                    last_error=st.last_error,
                )
            )
        else:
            platforms_out.append(
                PlatformStatusOut(
                    platform=platform_name,
                    enabled_by_config=settings.fetchers_enabled,
                    consecutive_failures=0,
                    disabled_until=None,
                    last_success_at=None,
                    last_error=None,
                )
            )

    return SourcesStatusResponse(
        platforms=platforms_out,
        quick_commerce="manual only (blocked by the sites)",
    )


@router.post(
    "/sources/refresh",
    response_model=RefreshQueuedResponse,
    status_code=status.HTTP_202_ACCEPTED,
)
def refresh_sources(
    background_tasks: BackgroundTasks,
    session: SessionDep,
    user: CurrentUserDep,
    now_dt: ClockDep,
    _csrf: CsrfDep,
) -> RefreshQueuedResponse:
    mem = session.exec(
        select(HouseholdMember).where(HouseholdMember.user_id == user.id)
    ).first()
    if not mem or mem.role != "owner":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail="Owner permission required",
        )

    household_id = mem.household_id
    settings = get_settings()

    with _lock:
        if household_id in _in_progress_households:
            raise HTTPException(
                status_code=status.HTTP_409_CONFLICT,
                detail=f"Refresh already in progress for household {household_id}",
            )
        _in_progress_households.add(household_id)

    try:
        due = get_due_listings(
            session,
            household_id,
            now_dt=now_dt,
            interval_hours=settings.fetch_interval_hours,
            limit=30,
        )
        n_due = len(due)
        background_tasks.add_task(_run_refresh_task, household_id, settings.fetch_interval_hours)
    except Exception:
        with _lock:
            _in_progress_households.discard(household_id)
        raise

    return RefreshQueuedResponse(queued=n_due)
