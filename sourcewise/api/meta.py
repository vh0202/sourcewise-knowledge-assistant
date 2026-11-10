"""Public metadata the UI needs before sign-in: product label, active engine, demo accounts."""

from __future__ import annotations

from fastapi import APIRouter
from sqlalchemy import select

from .. import HONESTY_LABEL, __version__
from ..models import User
from ..schemas import EngineInfo, MetaOut
from ..seed import DEMO_USERS
from .deps import ContainerDep, SessionDep

router = APIRouter(tags=["meta"])


@router.get("/meta", response_model=MetaOut)
def meta(container: ContainerDep, session: SessionDep) -> MetaOut:
    engine = container.answer_engine
    demo_accounts = []
    if container.settings.show_demo_accounts:
        # Only advertise the demo credentials while the seeded demo users actually exist.
        existing = set(session.execute(select(User.email)).scalars())
        demo_accounts = [
            {"name": u["name"], "email": u["email"], "password": u["password"], "role": u["role"]}
            for u in DEMO_USERS
            if u["email"] in existing
        ]
    return MetaOut(
        name="SourceWise",
        version=__version__,
        notice=HONESTY_LABEL,
        engine=EngineInfo(name=engine.name, label=engine.label, model=engine.model),
        retriever={"name": container.retriever.name, "label": container.retriever.label},
        demo_accounts=demo_accounts,
    )


@router.get("/health")
def health() -> dict[str, str]:
    return {"status": "ok"}
