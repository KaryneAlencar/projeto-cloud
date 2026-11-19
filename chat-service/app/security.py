import hashlib
import hmac
import secrets
from contextvars import ContextVar
from datetime import timedelta

from fastapi import HTTPException

from .models import BrowserSession, now

owner_context = ContextVar("session_owner", default=None)


def token_hash(token):
    return hashlib.sha256(token.encode()).hexdigest()


def active_session(session, raw_token):
    if not raw_token or len(raw_token) > 128:
        return None
    browser = session.get(BrowserSession, token_hash(raw_token))
    if browser and browser.expira_em > now():
        return browser
    return None


def check_origin(request, settings):
    origin = request.headers.get("origin")
    if origin and origin.rstrip("/") not in settings.allowed_origins:
        raise HTTPException(403, "Origem da solicitação não permitida.")


def verify_request(request, sessions, settings):
    with sessions() as session:
        browser = active_session(session, request.cookies.get(settings.cookie_name))
        if not browser:
            raise HTTPException(401, "Sua sessão expirou. Atualize a página para continuar.")
        if request.method not in {"GET", "HEAD", "OPTIONS"}:
            check_origin(request, settings)
            if not hmac.compare_digest(request.headers.get("x-csrf-token", ""), browser.csrf_token):
                raise HTTPException(403, "A sessão precisa ser atualizada antes de continuar.")
        return browser.token_hash


def start_session(request, response, sessions, settings):
    check_origin(request, settings)
    raw_token = request.cookies.get(settings.cookie_name)
    with sessions.begin() as session:
        browser = active_session(session, raw_token)
        if not browser:
            raw_token = secrets.token_urlsafe(32)
            browser = BrowserSession(token_hash=token_hash(raw_token), csrf_token=secrets.token_urlsafe(32),
                                     expira_em=now() + timedelta(days=settings.session_days))
            session.add(browser)
        max_age = max(1, int((browser.expira_em - now()).total_seconds()))
        response.set_cookie(settings.cookie_name, raw_token, max_age=max_age, httponly=True,
                            secure=settings.cookie_secure, samesite="lax", path="/")
        response.headers["Cache-Control"] = "no-store"
        # Referência pública para recuperação administrativa; não é credencial de acesso.
        return {"csrf_token": browser.csrf_token, "session_reference": browser.token_hash}
