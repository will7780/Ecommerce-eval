"""Central-only credentials; reads never hydrate os.environ or expose values."""

from __future__ import annotations

import ctypes
import hashlib
import hmac
import io
import os
import re
import secrets
import stat
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping

from dotenv.parser import parse_stream
from filelock import FileLock, Timeout
from pydantic import SecretStr

from .errors import ProviderError

MAX_ENV_BYTES = 128 * 1024
KEY_NAME = re.compile(r"^[A-Z][A-Z0-9_]{0,110}_API_KEY$")


def _no_links(path: Path) -> None:
    for item in (path, *path.parents):
        if item.is_symlink() or (hasattr(item, "is_junction") and item.is_junction()):
            raise ProviderError("central_env_link_forbidden")


def _parse(raw: bytes):
    try:
        text = raw.decode("utf-8-sig")
        bindings = list(parse_stream(io.StringIO(text)))
        keys = [item.key for item in bindings if item.key is not None]
        if any(item.error for item in bindings) or len(keys) != len(set(keys)):
            raise ValueError
        return text, bindings, {item.key: item.value for item in bindings if item.key is not None}
    except (ValueError, UnicodeError):
        raise ProviderError("central_env_invalid") from None


def _secure_new_fd(path: Path) -> int:
    if os.name != "nt":
        return os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    # Create the replacement with an owner-only DACL before any secret bytes exist.
    from ctypes import wintypes
    import msvcrt

    class SecurityAttributes(ctypes.Structure):
        _fields_ = [("length", wintypes.DWORD), ("descriptor", ctypes.c_void_p),
                    ("inherit", wintypes.BOOL)]

    advapi = ctypes.WinDLL("advapi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    convert = advapi.ConvertStringSecurityDescriptorToSecurityDescriptorW
    convert.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, ctypes.POINTER(ctypes.c_void_p),
                        ctypes.POINTER(wintypes.DWORD)]
    convert.restype = wintypes.BOOL
    create = kernel.CreateFileW
    create.argtypes = [wintypes.LPCWSTR, wintypes.DWORD, wintypes.DWORD,
                       ctypes.POINTER(SecurityAttributes), wintypes.DWORD,
                       wintypes.DWORD, wintypes.HANDLE]
    create.restype = wintypes.HANDLE
    kernel.LocalFree.argtypes = [ctypes.c_void_p]
    descriptor = ctypes.c_void_p()
    if not convert("D:P(A;;FA;;;OW)(A;;FA;;;SY)", 1, ctypes.byref(descriptor), None):
        raise OSError("secure_file_create_failed")
    try:
        attributes = SecurityAttributes(ctypes.sizeof(SecurityAttributes), descriptor, False)
        handle = create(str(path), 0x40000000, 0, ctypes.byref(attributes), 1, 0x80, None)
        if handle == wintypes.HANDLE(-1).value:
            raise OSError("secure_file_create_failed")
        return msvcrt.open_osfhandle(handle, os.O_WRONLY | os.O_BINARY)
    finally:
        kernel.LocalFree(descriptor)


def _replace_preserving_permissions(path: Path, temporary: Path, previous_stat) -> None:
    if os.name == "nt" and previous_stat is not None:
        from ctypes import wintypes

        replace = ctypes.WinDLL("kernel32", use_last_error=True).ReplaceFileW
        replace.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.LPCWSTR,
                            wintypes.DWORD, ctypes.c_void_p, ctypes.c_void_p]
        replace.restype = wintypes.BOOL
        # Do not set IGNORE_ACL_ERRORS or create a backup; failure is fail-closed.
        if not replace(str(path), str(temporary), None, 0, None, None):
            raise OSError("secure_file_replace_failed")
    else:
        if previous_stat is not None:
            current = temporary.stat()
            if (current.st_uid, current.st_gid) != (previous_stat.st_uid, previous_stat.st_gid):
                os.chown(temporary, previous_stat.st_uid, previous_stat.st_gid)
            os.chmod(temporary, stat.S_IMODE(previous_stat.st_mode))
            if hasattr(os, "listxattr"):
                for name in os.listxattr(path):
                    os.setxattr(temporary, name, os.getxattr(path, name))
        os.replace(temporary, path)


class CentralEnvStore:
    def __init__(self, path: Path | str | None = None, *, environ: Mapping[str, str] | None = None,
                 home: Path | None = None, platform_name: str | None = None,
                 lock_timeout: float = 2.0):
        self.environ = os.environ if environ is None else environ
        self.lock_timeout = lock_timeout
        self._version_key = secrets.token_bytes(32)
        pointer = self.environ.get("AGENT_API_ENV_FILE")
        disabled = self.environ.get("COMMERCE_EVAL_DISABLE_CENTRAL_ENV", "").lower() in {"1", "true", "yes"}
        self.source = "explicit" if path is not None else "pointer" if pointer else "default"
        selected = Path(path).expanduser() if path is not None else Path(pointer).expanduser() if pointer else None
        if selected is None and (platform_name or os.name) == "nt":
            selected = (home or Path.home()) / "Desktop" / "api" / ".env"
        self.path = Path(os.path.abspath(selected)) if selected is not None and not disabled else None
        self.disabled = disabled

    def _read(self) -> tuple[bytes, os.stat_result | None]:
        if self.path is None:
            code = "central_env_disabled" if self.disabled else "central_env_path_required"
            raise ProviderError(code)
        _no_links(self.path)
        try:
            fd = os.open(self.path, os.O_RDONLY | getattr(os, "O_BINARY", 0) | getattr(os, "O_NOFOLLOW", 0))
        except FileNotFoundError:
            return b"", None
        try:
            with os.fdopen(fd, "rb") as stream:
                info = os.fstat(stream.fileno())
                if not stat.S_ISREG(info.st_mode) or info.st_size > MAX_ENV_BYTES:
                    raise ProviderError("central_env_invalid")
                raw = stream.read(MAX_ENV_BYTES + 1)
                if len(raw) > MAX_ENV_BYTES:
                    raise ProviderError("central_env_too_large")
                return raw, info
        except OSError:
            raise ProviderError("central_env_unavailable") from None

    def _version(self, raw: bytes, exists: bool) -> str:
        return "env_" + hmac.new(self._version_key, (b"1" if exists else b"0") + raw, hashlib.sha256).hexdigest()

    def status(self) -> dict:
        try:
            raw, info = self._read()
            _parse(raw)
            parent = self.path.parent
            while not parent.exists() and parent != parent.parent:
                parent = parent.parent
            writable = os.access(parent, os.W_OK) and (info is None or os.access(self.path, os.W_OK))
            return {"version": self._version(raw, info is not None), "available": info is not None,
                    "writable": writable, "source": self.source, "error_type": None}
        except (OSError, ValueError, ProviderError) as exc:
            return {"version": None, "available": False, "writable": False, "source": self.source,
                    "error_type": exc.code if isinstance(exc, ProviderError) else "central_env_unavailable"}

    def _get_secret(self, name: str) -> SecretStr:
        try:
            raw, _ = self._read()
            value = _parse(raw)[2].get(name)
            return SecretStr(value or "")
        except (OSError, ValueError):
            raise ProviderError("central_env_unavailable") from None

    def set_secret(self, name: str, value: str | SecretStr, *, expected_version: str) -> dict:
        secret = value.get_secret_value() if isinstance(value, SecretStr) else value
        if not isinstance(name, str) or not KEY_NAME.fullmatch(name):
            raise ProviderError("credential_reference_invalid")
        if (not isinstance(secret, str) or not 1 <= len(secret) <= 4096
                or any(ord(char) < 33 or ord(char) > 126 for char in secret)
                or any(char in secret for char in "'\"\\$`")):
            raise ProviderError("credential_value_invalid")
        if not isinstance(expected_version, str) or not expected_version:
            raise ProviderError("central_env_version_required", 409)
        if self.path is None:
            raise ProviderError("central_env_path_required")
        temporary = None
        try:
            _no_links(self.path)
            self.path.parent.mkdir(parents=True, exist_ok=True)
            lock_path = self.path.with_name(self.path.name + ".lock")
            _no_links(lock_path)
            with FileLock(str(lock_path), timeout=self.lock_timeout):
                raw, info = self._read()
                if not hmac.compare_digest(expected_version, self._version(raw, info is not None)):
                    raise ProviderError("central_env_version_conflict", 409)
                text, bindings, _ = _parse(raw)
                newline = "\r\n" if "\r\n" in text else "\n"
                replacement = f"{name}='{secret}'{newline}"
                chunks, found = [], False
                for item in bindings:
                    if item.key == name:
                        chunks.append(replacement)
                        found = True
                    else:
                        chunks.append(item.original.string)
                updated = "".join(chunks)
                if not found:
                    updated += (newline if updated and not updated.endswith(("\n", "\r")) else "") + replacement
                encoded = (b"\xef\xbb\xbf" if raw.startswith(b"\xef\xbb\xbf") else b"") + updated.encode("utf-8")
                if len(encoded) > MAX_ENV_BYTES:
                    raise ProviderError("central_env_too_large")
                temporary = self.path.with_name(".env-write-" + secrets.token_hex(16))
                with os.fdopen(_secure_new_fd(temporary), "wb") as stream:
                    stream.write(encoded)
                    stream.flush()
                    os.fsync(stream.fileno())
                # Check again for non-cooperating writers before the atomic replacement.
                latest, latest_info = self._read()
                if latest != raw or (latest_info is None) != (info is None):
                    raise ProviderError("central_env_version_conflict", 409)
                _replace_preserving_permissions(self.path, temporary, info)
                temporary = None
                return self.status()
        except Timeout:
            raise ProviderError("central_env_locked", 409) from None
        except OSError:
            raise ProviderError("central_env_write_failed", 403) from None
        finally:
            if temporary is not None:
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass


@dataclass(frozen=True)
class ResolvedCredential:
    value: SecretStr
    source: str
    error_type: str | None = None

    @property
    def configured(self) -> bool:
        return bool(self.value.get_secret_value())


class CredentialResolver:
    def __init__(self, store: CentralEnvStore | None = None, *, environ: Mapping[str, str] | None = None):
        self.environ = (store.environ if store is not None else os.environ) if environ is None else environ
        self.store = store if store is not None else CentralEnvStore(environ=self.environ)

    def resolve(self, name: str) -> ResolvedCredential:
        if not isinstance(name, str) or not KEY_NAME.fullmatch(name):
            raise ProviderError("credential_reference_invalid")
        if name in self.environ:
            return ResolvedCredential(SecretStr(self.environ[name]), "process_env")
        try:
            value = self.store._get_secret(name)
            return ResolvedCredential(value, "central_env" if value.get_secret_value() else "missing")
        except ProviderError as exc:
            return ResolvedCredential(SecretStr(""), "missing", exc.code)
