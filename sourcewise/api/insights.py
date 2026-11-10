"""Insights (admin only)."""

from __future__ import annotations

from typing import Annotated

from fastapi import APIRouter, Query

from ..insights import InsightsOut, compute_insights
from .deps import AdminUser, SessionDep

router = APIRouter(prefix="/insights", tags=["insights"])


@router.get("", response_model=InsightsOut)
def insights(
    session: SessionDep, _admin: AdminUser, days: Annotated[int, Query(ge=1, le=90)] = 14
) -> InsightsOut:
    return compute_insights(session, days=days)
