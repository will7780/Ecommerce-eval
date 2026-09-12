"""Local-only provider administration with same-origin, signed-cookie CSRF."""

import hashlib
import hmac
import ipaddress
import secrets
import time
from urllib.parse import urlsplit

from fastapi import APIRouter, Request
from fastapi.exceptions import RequestValidationError
from fastapi.responses import JSONResponse
from fastapi.routing import APIRoute
from pydantic import ValidationError

from .errors import ProviderError
from .schemas import CredentialSave, ProviderCheck, ProviderSave
from .service import ProviderConfigService

COOKIE = "commerce_provider_csrf"
COOKIE_PATH = "/api/v1/providers"


class ProviderRoute(APIRoute):
    def get_route_handler(self):
        original = super().get_route_handler()

        async def handler(request):
            try:
                response = await original(request)
            except ProviderError as exc:
                response = JSONResponse({"detail": exc.code}, status_code=exc.status_code)
            except (ValidationError, RequestValidationError, ValueError, TypeError):
                response = JSONResponse({"detail": "provider_request_invalid"}, status_code=422)
            except Exception:
                response = JSONResponse({"detail": "provider_internal_error"}, status_code=500)
            response.headers["Cache-Control"] = "no-store"
            return response

        return handler


def _loopback(host):
    try:
        address = ipaddress.ip_address(host)
        address = getattr(address, "ipv4_mapped", None) or address
        return address.is_loopback
    except (ValueError, TypeError):
        return False


def _origin(value):
    parsed = urlsplit(value)
    if (parsed.scheme not in {"http", "https"} or not parsed.hostname or parsed.username is not None
            or parsed.password is not None or parsed.query or parsed.fragment or parsed.path not in {"", "/"}):
        raise ValueError
    if parsed.hostname != "localhost" and not _loopback(parsed.hostname):
        raise ValueError
    return parsed.scheme, parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)


class ProviderCSRF:
    def __init__(self, *, clock=time.time):
        self.key = secrets.token_bytes(32)
        self.clock = clock

    def local_origin(self, request: Request, *, mutation: bool):
        if not request.client or not _loopback(request.client.host):
            raise ProviderError("provider_local_management_required", 403)
        try:
            actual = _origin(f"{request.url.scheme}://{request.headers.get('host', '')}")
            supplied = request.headers.get("origin")
            if mutation and supplied is None:
                raise ValueError
            if supplied is not None and _origin(supplied) != actual:
                raise ValueError
            if request.headers.get("sec-fetch-site", "same-origin") not in {"same-origin", "none"}:
                raise ValueError
        except ValueError:
            raise ProviderError("provider_same_origin_required", 403) from None

    def issue(self, request: Request) -> JSONResponse:
        self.local_origin(request, mutation=False)
        payload = f"{int(self.clock())}:{secrets.token_hex(24)}"
        token = payload + ":" + hmac.new(self.key, payload.encode(), hashlib.sha256).hexdigest()
        response = JSONResponse({"csrf_token": token})
        response.set_cookie(COOKIE, token, httponly=True, secure=request.url.scheme == "https",
                            samesite="strict", max_age=1800, path=COOKIE_PATH)
        return response

    def verify(self, request: Request):
        self.local_origin(request, mutation=True)
        header, cookie = request.headers.get("x-csrf-token", ""), request.cookies.get(COOKIE, "")
        try:
            if not header or len(header) > 200 or not hmac.compare_digest(header, cookie):
                raise ValueError
            issued, nonce, signature = header.split(":")
            elapsed = self.clock() - int(issued)
            if elapsed < 0 or elapsed > 1800 or len(nonce) != 48:
                raise ValueError
            expected = hmac.new(self.key, f"{issued}:{nonce}".encode(), hashlib.sha256).hexdigest()
            if not hmac.compare_digest(expected, signature):
                raise ValueError
        except (ValueError, TypeError):
            raise ProviderError("provider_csrf_invalid", 403) from None


async def _body(request, schema):
    length = request.headers.get("content-length")
    if length is not None and int(length) > 16 * 1024:
        raise ProviderError("provider_request_too_large", 413)
    content = bytearray()
    async for chunk in request.stream():
        content.extend(chunk)
        if len(content) > 16 * 1024:
            raise ProviderError("provider_request_too_large", 413)
    if request.headers.get("content-type", "").split(";")[0].strip() != "application/json":
        raise ProviderError("provider_json_required", 415)
    try:
        return schema.model_validate_json(content)
    except (ValidationError, ValueError):
        raise ProviderError("provider_request_invalid", 422) from None


def build_provider_router(database, *, service=None) -> APIRouter:
    service = service if service is not None else ProviderConfigService(database)
    csrf = ProviderCSRF()
    router = APIRouter(prefix="/api/v1/providers", tags=["providers"], route_class=ProviderRoute)

    @router.get("")
    def list_providers():
        return service.list()

    @router.get("/csrf")
    def csrf_token(request: Request):
        return csrf.issue(request)

    @router.post("")
    async def save_provider(request: Request):
        csrf.verify(request)
        return service.save(await _body(request, ProviderSave))

    @router.post("/{provider_id}/credential")
    async def save_credential(provider_id: str, request: Request):
        csrf.verify(request)
        return service.set_credential(provider_id, await _body(request, CredentialSave))

    @router.post("/{provider_id}/check")
    async def check_provider(provider_id: str, request: Request):
        csrf.verify(request)
        return await service.check(provider_id, await _body(request, ProviderCheck))

    return router
