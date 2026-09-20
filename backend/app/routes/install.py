import secrets
import uuid

from fastapi import APIRouter

from app.auth import create_install
from app.db import get_conn, now_ms
from app.models import InstallResponse

router = APIRouter()


@router.post("/install", response_model=InstallResponse)
def install() -> InstallResponse:
    install_id = str(uuid.uuid4())
    token = secrets.token_urlsafe(32)
    create_install(get_conn(), install_id, token, now_ms())
    return InstallResponse(installId=install_id, installToken=token)
