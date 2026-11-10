"""Auth: Bearer JWT (access) + refresh; exige sessão em prod no /search."""

from __future__ import annotations

from typing import Annotated

from fastapi import Depends, Header, HTTPException

from .db import billing_enabled
from .security import search_require_auth
from .sessions import get_user_from_access
from .wallet import User


def extract_token(
    authorization: str | None = None,
    x_vooai_token: str | None = None,
) -> str | None:
    if x_vooai_token and x_vooai_token.strip():
        return x_vooai_token.strip()
    if authorization:
        parts = authorization.split(None, 1)
        if len(parts) == 2 and parts[0].lower() == "bearer":
            return parts[1].strip()
        if len(parts) == 1:
            return parts[0].strip()
    return None


def optional_user(
    authorization: str | None = Header(default=None),
    x_vooai_token: str | None = Header(default=None, alias="X-VooAI-Token"),
) -> User | None:
    token = extract_token(authorization, x_vooai_token)
    if not token:
        return None
    user = get_user_from_access(token)
    if token and not user:
        raise HTTPException(status_code=401, detail={"code": "auth_invalid", "message": "Sessão inválida."})
    return user


def require_user(
    authorization: str | None = Header(default=None),
    x_vooai_token: str | None = Header(default=None, alias="X-VooAI-Token"),
) -> User:
    user = optional_user(authorization, x_vooai_token)
    if user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Entre na conta para continuar."},
        )
    return user


def require_user_if_billing(
    authorization: str | None = Header(default=None),
    x_vooai_token: str | None = Header(default=None, alias="X-VooAI-Token"),
) -> User | None:
    """Billing on OU search_require_auth → User obrigatório; senão opcional."""
    user = optional_user(authorization, x_vooai_token)
    need = billing_enabled() or search_require_auth()
    if need and user is None:
        raise HTTPException(
            status_code=401,
            detail={"code": "auth_required", "message": "Entre na conta para consultar o sinal."},
        )
    return user


UserRequired = Annotated[User, Depends(require_user)]
