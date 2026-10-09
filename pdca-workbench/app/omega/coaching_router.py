"""Owner-only coaching HTTP contract."""
from typing import Annotated

from fastapi import APIRouter, Depends
from sqlmodel import Session, select

from app.auth.deps import get_current_user
from app.auth.models import User
from app.database import get_session
from app.omega.coaching import private_session, queue_hint
from app.omega.coaching_models import OmegaCoachHint
from app.omega.router import enabled, job_view
from app.omega.schemas import OperationRequest

router = APIRouter(prefix="/api/omega", tags=["omega"], dependencies=[Depends(enabled)])


@router.post("/sessions/{session_id}/coach-hints", status_code=202)
def request_hint(session_id: str, body: OperationRequest,
                 user: Annotated[User, Depends(get_current_user)],
                 db: Annotated[Session, Depends(get_session)]):
    return job_view(queue_hint(db, user, session_id, body.request_key))


@router.get("/sessions/{session_id}/coach-hints")
def list_hints(session_id: str, user: Annotated[User, Depends(get_current_user)],
               db: Annotated[Session, Depends(get_session)]):
    private_session(db, user, session_id)
    return [{"id": hint.id, "request_key": hint.request_key, "status": hint.status,
             "text": hint.text, "context_revision": hint.context_revision,
             "created_at": hint.created_at.isoformat()}
            for hint in db.exec(select(OmegaCoachHint).where(OmegaCoachHint.session_id == session_id)
                                .order_by(OmegaCoachHint.created_at)).all()]
