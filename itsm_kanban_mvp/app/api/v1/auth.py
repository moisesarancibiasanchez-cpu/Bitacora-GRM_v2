"""Endpoints de autenticación: login, logout, me."""
from __future__ import annotations
from fastapi import APIRouter, Depends, Form, HTTPException, Request, Response, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session
from sqlalchemy import select

from app.core.security import create_access_token, verify_password
from app.core.config import settings
from app.db.session import get_db
from app.models.usuario import Usuario, RolUsuario

router = APIRouter(prefix="/auth", tags=["auth"])
templates = Jinja2Templates(directory="app/templates")


@router.get("/login", response_class=HTMLResponse)
def login_form(request: Request, error: str | None = None):
    return templates.TemplateResponse(
        "auth/login.html", {"request": request, "error": error, "app_name": settings.app_name}
    )


@router.post("/login")
def login(
    request: Request,
    response: Response,
    username: str = Form(...),
    password: str = Form(...),
    db: Session = Depends(get_db),
):
    """Autentica al usuario, emite JWT, lo guarda en cookie y redirige al Kanban."""
    user = db.execute(select(Usuario).where(Usuario.username == username)).scalar_one_or_none()
    if not user or not user.activo or not verify_password(password, user.password_hash):
        return templates.TemplateResponse(
            "auth/login.html",
            {"request": request, "error": "Usuario o contraseña incorrectos", "app_name": settings.app_name},
            status_code=401,
        )

    token = create_access_token(user.id, extra_claims={"rol": user.rol.value, "username": user.username})
    response = RedirectResponse(url="/kanban", status_code=status.HTTP_303_SEE_OTHER)
    response.set_cookie(
        key="access_token",
        value=token,
        httponly=True,
        samesite="lax",
        secure=False,  # True en producción con HTTPS
        max_age=settings.jwt_expiration_minutes * 60,
    )
    return response


@router.post("/logout")
def logout():
    response = RedirectResponse(url="/auth/login", status_code=303)
    response.delete_cookie("access_token")
    return response


@router.get("/me")
def me(usuario: Usuario = Depends(__import__("app.api.v1.deps", fromlist=["get_current_user"]).get_current_user)):
    return {
        "id": usuario.id,
        "username": usuario.username,
        "rol": usuario.rol.value,
        "email": usuario.email,
    }
