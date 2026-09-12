"""Confirm a base URL, validate every DNS result and pin the request address."""

import asyncio
import ipaddress
import socket
from urllib.parse import urlsplit, urlunsplit

import httpx

from .errors import ProviderError

MAX_RESPONSE_BYTES = 2 * 1024 * 1024


def _literal_loopback(host: str) -> bool:
    if host.lower().rstrip(".") == "localhost":
        return True
    try:
        address = ipaddress.ip_address(host)
        return address.is_loopback or bool(getattr(address, "ipv4_mapped", None) and address.ipv4_mapped.is_loopback)
    except ValueError:
        return False


def check_address(value: str, host: str, allow_localhost: bool) -> None:
    try:
        address = ipaddress.ip_address(value)
        address = getattr(address, "ipv4_mapped", None) or address
    except ValueError:
        raise ProviderError("provider_address_forbidden") from None
    if _literal_loopback(host):
        if address.is_loopback and allow_localhost:
            return
        raise ProviderError("provider_address_forbidden")
    if not address.is_global or address.is_multicast or address.is_unspecified:
        raise ProviderError("provider_address_forbidden")


def normalize_base_url(value: str, *, allow_localhost: bool = False) -> str:
    try:
        if not isinstance(value, str) or any(char.isspace() or ord(char) < 32 for char in value):
            raise ValueError
        parsed = urlsplit(value)
        host = parsed.hostname
        if (not host or parsed.scheme not in {"https", "http"} or parsed.username is not None
                or parsed.password is not None or parsed.query or parsed.fragment
                or "\\" in value or "%" in value or any(ord(char) > 127 for char in value)):
            raise ValueError
        if parsed.port is not None and not 1 <= parsed.port <= 65535:
            raise ValueError
        if parsed.scheme == "http" and not (allow_localhost and _literal_loopback(host)):
            raise ProviderError("provider_https_required")
        if host.lower().rstrip(".") in {"metadata", "metadata.google.internal", "instance-data"}:
            raise ProviderError("provider_address_forbidden")
        if "/../" in parsed.path + "/" or "/./" in parsed.path + "/" or parsed.path.endswith("/chat/completions"):
            raise ValueError
        try:
            ipaddress.ip_address(host)
        except ValueError:
            if _literal_loopback(host) and not allow_localhost:
                raise ProviderError("provider_address_forbidden")
        else:
            check_address(host, host, allow_localhost)
        authority = f"[{host.lower()}]" if ":" in host else host.lower()
        if parsed.port is not None:
            authority += f":{parsed.port}"
        return urlunsplit((parsed.scheme, authority, parsed.path.rstrip("/"), "", ""))
    except ValueError:
        raise ProviderError("provider_url_invalid") from None


def http_error(status: int) -> str | None:
    if status == 401:
        return "provider_authentication_denied"
    if status == 403:
        return "provider_permission_denied"
    if 300 <= status < 400:
        return "provider_redirect_refused"
    if status == 429:
        return "provider_rate_limited"
    if status >= 500:
        return "provider_backend_error"
    if status != 200:
        return "provider_request_rejected"
    return None


async def post_completion(config: dict, body: dict, secret: str, *, timeout_seconds: float,
                          transport=None, dns_resolver=None) -> bytes:
    parsed = urlsplit(normalize_base_url(config["base_url"], allow_localhost=config["allow_localhost"]))
    host, port = parsed.hostname, parsed.port or (443 if parsed.scheme == "https" else 80)
    if dns_resolver is None:
        resolved = await asyncio.get_running_loop().getaddrinfo(host, port, type=socket.SOCK_STREAM)
        addresses = [item[4][0] for item in resolved]
    else:
        addresses = await dns_resolver(host, port)
    if not addresses:
        raise ProviderError("provider_disconnected")
    for address in addresses:
        check_address(address, host, config["allow_localhost"])
    address = addresses[0]
    ip_host = f"[{address}]" if ":" in address else address
    host_header = f"[{host}]" if ":" in host else host
    url = urlunsplit((parsed.scheme, f"{ip_host}:{port}", parsed.path + "/chat/completions", "", ""))
    if not secret or any(ord(char) < 33 or ord(char) > 126 for char in secret):
        raise ProviderError("credential_reference_invalid")
    headers = {"Host": f"{host_header}:{port}", "Authorization": "Bearer " + secret,
               "Accept": "application/json", "Accept-Encoding": "identity"}
    async with httpx.AsyncClient(transport=transport, trust_env=False, follow_redirects=False,
                                timeout=timeout_seconds) as client:
        async with client.stream("POST", url, json=body, headers=headers,
                                 extensions={"sni_hostname": host}) as response:
            error = http_error(response.status_code)
            if error:
                raise ProviderError(error, 502)
            if response.headers.get("content-encoding", "identity").lower() != "identity":
                raise ProviderError("provider_invalid_response", 502)
            content_type = response.headers.get("content-type", "application/json").split(";")[0].strip()
            if content_type != "application/json" and not content_type.endswith("+json"):
                raise ProviderError("provider_invalid_response", 502)
            try:
                if int(response.headers.get("content-length", "0")) > MAX_RESPONSE_BYTES:
                    raise ProviderError("provider_response_too_large", 502)
            except ValueError:
                raise ProviderError("provider_invalid_response", 502) from None
            content = bytearray()
            async for chunk in response.aiter_bytes(chunk_size=8192):
                if len(content) + len(chunk) > MAX_RESPONSE_BYTES:
                    raise ProviderError("provider_response_too_large", 502)
                content.extend(chunk)
            return bytes(content)
