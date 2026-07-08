from fastapi import APIRouter, Depends, HTTPException, Request
from sqlalchemy import select
from sqlalchemy.orm import Session

from rag.api.deps import AuthenticatedUser, get_current_user
from rag.api.schemas.auth import (
    LoginRequest, LoginResponse, MeResponse, MfaEnrollResponse, MfaVerifyRequest,
    RefreshRequest, RefreshResponse, SessionNav, SessionResponse, SessionUser,
)
from rag.auth import local_auth, session_service
from rag.crosscutting.security.audit_events import record_mfa_enrolled
from rag.auth.mfa import encrypt_secret, generate_totp_secret, totp_uri
from rag.infra.stores.sql.base import get_db
from rag.infra.stores.sql.models import Department

router = APIRouter()


@router.post("/login", response_model=LoginResponse)
def login(body: LoginRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    try:
        result = local_auth.login(
            db, body.username, body.password,
            ip=request.client.host if request.client else "",
            request_id=getattr(request.state, "request_id", ""),
        )
    except local_auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return LoginResponse(**result.__dict__)


@router.post("/mfa/enroll", response_model=MfaEnrollResponse)
def mfa_enroll(current: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> MfaEnrollResponse:
    if current.user.mfa_enabled:
        raise HTTPException(status_code=409, detail="MFA is already enabled for this account")
    raw_secret = generate_totp_secret()
    current.user.mfa_secret_encrypted = encrypt_secret(db, raw_secret)
    current.user.mfa_enabled = True
    db.commit()
    record_mfa_enrolled(str(current.user.id))
    return MfaEnrollResponse(secret=raw_secret, provisioning_uri=totp_uri(raw_secret, current.user.username))


@router.post("/mfa/verify", response_model=LoginResponse)
def mfa_verify(body: MfaVerifyRequest, request: Request, db: Session = Depends(get_db)) -> LoginResponse:
    try:
        result = local_auth.verify_mfa(
            db, body.mfa_pending_token, body.totp_code,
            ip=request.client.host if request.client else "",
        )
    except local_auth.AuthError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return LoginResponse(**result.__dict__)


@router.post("/refresh", response_model=RefreshResponse)
def refresh(body: RefreshRequest, db: Session = Depends(get_db)) -> RefreshResponse:
    try:
        access, new_refresh = session_service.refresh(db, body.refresh_token)
    except session_service.SessionError as exc:
        raise HTTPException(status_code=401, detail=str(exc)) from exc
    return RefreshResponse(access_token=access, refresh_token=new_refresh)


@router.post("/logout", status_code=204)
def logout(current: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db)) -> None:
    session_service.logout(db, str(current.session_id), str(current.user.id))


@router.get("/me", response_model=MeResponse)
def me(current: AuthenticatedUser = Depends(get_current_user)) -> MeResponse:
    return MeResponse(
        id=str(current.user.id), username=current.user.username,
        roles=current.auth_subject.roles, effective_levels=current.auth_subject.effective_levels,
    )


session_router = APIRouter()


@session_router.get("/session", response_model=SessionResponse)
def get_session(
    current: AuthenticatedUser = Depends(get_current_user), db: Session = Depends(get_db),
) -> SessionResponse:
    department_name = None
    if current.user.department_id is not None:
        department_name = db.execute(
            select(Department.name).where(Department.id == current.user.department_id)
        ).scalar_one_or_none()

    role = current.auth_subject.roles[0] if current.auth_subject.roles else "—"
    is_admin = any(p.startswith("admin:") for p in current.auth_subject.permissions)

    return SessionResponse(
        user=SessionUser(
            id=str(current.user.id),
            username=current.user.username,
            name=current.user.username,
            role=role,
            department=department_name,
            status="active",
        ),
        edition="enterprise",
        nav=SessionNav(
            chat=True, search=True, documents=True,
            admin=is_admin, evaluation=is_admin, audit=is_admin, system=is_admin,
        ),
    )
