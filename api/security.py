"""Защита веб-приложения:
- заголовки безопасности (CSP без внешних источников, запрет фреймов, nosniff, no-referrer);
- ограничение частоты запросов к LLM (защита от перерасхода ключа и перебора);
- опциональный токен доступа API (переменная API_TOKEN; если не задана — доступ без токена, как на демо);
- идентификация аналитика для журнала действий (заголовок X-Analyst)."""
import hmac
import os
import re
import time
from collections import defaultdict, deque

from fastapi import Request
from fastapi.responses import JSONResponse
from starlette.middleware.base import BaseHTTPMiddleware

API_TOKEN = os.getenv("API_TOKEN", "").strip()
LLM_PATHS = re.compile(r"^/api/(assistant|node/\d+/card)$")
LLM_LIMIT, LLM_WINDOW = int(os.getenv("LLM_RATE_PER_MIN", "20")), 60.0

CSP = ("default-src 'self'; script-src 'self'; style-src 'self' 'unsafe-inline'; img-src 'self' data:; "
       "connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'; frame-ancestors 'none'; form-action 'self'")
HEADERS = {
    "Content-Security-Policy": CSP,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=()",
    "Cross-Origin-Opener-Policy": "same-origin",
}

_hits: dict[str, deque] = defaultdict(deque)


def analyst(request: Request) -> str:
    """Имя аналитика из заголовка — только буквы, цифры, пробел, точка, дефис; до 64 символов."""
    from urllib.parse import unquote
    raw = unquote(request.headers.get("x-analyst", ""))   # фронтенд кодирует имя через encodeURIComponent
    clean = re.sub(r"[^\w .\-]", "", raw, flags=re.UNICODE).strip()[:64]
    return clean or "аноним"


class SecurityMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next):
        path = request.url.path
        if path.startswith("/api/"):
            # 1) токен доступа (если включён)
            if API_TOKEN:
                sent = request.headers.get("x-api-token", "")
                if not hmac.compare_digest(sent, API_TOKEN):
                    return JSONResponse({"detail": "нужен токен доступа (X-Api-Token)"}, status_code=401)
            # 2) лимит частоты для LLM
            if request.method == "POST" and LLM_PATHS.match(path):
                ip = request.client.host if request.client else "?"
                q, now = _hits[ip], time.monotonic()
                while q and now - q[0] > LLM_WINDOW:
                    q.popleft()
                if len(q) >= LLM_LIMIT:
                    return JSONResponse({"detail": f"слишком много запросов к AI: не более {LLM_LIMIT} в минуту"},
                                        status_code=429, headers={"Retry-After": "60"})
                q.append(now)
        resp = await call_next(request)
        for k, v in HEADERS.items():
            resp.headers.setdefault(k, v)
        if path.startswith("/api/"):
            resp.headers["Cache-Control"] = "no-store"     # данные клиентов не кэшируются браузером
        return resp


def status() -> dict:
    return {"token_required": bool(API_TOKEN), "llm_rate_per_min": LLM_LIMIT, "csp": CSP,
            "headers": list(HEADERS)}
