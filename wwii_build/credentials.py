"""Secret storage for TypeSafe credentials.

The official SDK environment variable is checked first. A key entered through the
dashboard is stored in the current user's macOS Keychain and is never written to
SQLite, logs, config files, command arguments, or the repository.
"""
from __future__ import annotations

import ctypes
import os
import platform
import pwd

API_KEY_ENV = "TYPESAFE_API_KEY"  # verified against typesafe_sdk.constants.API_KEY_ENV
KEYCHAIN_SERVICE = "typesafe-delivers"
KEYCHAIN_ACCOUNT = pwd.getpwuid(os.getuid()).pw_name
LEGACY_KEYCHAIN_ENTRIES = (("wwii-build.typesafe.api-key", "typesafe-api"),)
ERR_ITEM_NOT_FOUND = -25300
ERR_INTERACTION_NOT_ALLOWED = -25308   # locked keychain in a headless session (CI, SSH)


class CredentialError(RuntimeError):
    pass


class TypeSafeCredentialStore:
    def __init__(self, env: dict[str, str] | None = None):
        self.env = os.environ if env is None else env

    def source(self) -> str | None:
        if str(self.env.get(API_KEY_ENV, "")).strip():
            return "environment"
        return "macos_keychain" if self._keychain_get() is not None else None

    def present(self) -> bool:
        return self.source() is not None

    def get(self) -> str | None:
        value = str(self.env.get(API_KEY_ENV, "")).strip()
        return value or self._keychain_get()

    def set(self, value: str) -> None:
        value = value.strip()
        if not value or any(ord(ch) < 33 or ord(ch) > 126 for ch in value):
            raise CredentialError("TypeSafe API key is empty or contains invalid characters")
        if platform.system() != "Darwin":
            raise CredentialError("dashboard credential storage requires macOS Keychain")
        security, core = self._frameworks()
        service = KEYCHAIN_SERVICE.encode("utf-8")
        account = KEYCHAIN_ACCOUNT.encode("utf-8")
        item = ctypes.c_void_p()
        status = security.SecKeychainFindGenericPassword(
            None, len(service), service, len(account), account, None, None, ctypes.byref(item))
        secret = value.encode("ascii")
        secret_buffer = ctypes.create_string_buffer(secret)
        if status == 0:
            result = security.SecKeychainItemModifyAttributesAndData(
                item, None, len(secret), ctypes.cast(secret_buffer, ctypes.c_void_p))
            core.CFRelease(item)
        elif status == ERR_ITEM_NOT_FOUND:
            result = security.SecKeychainAddGenericPassword(
                None, len(service), service, len(account), account, len(secret),
                ctypes.cast(secret_buffer, ctypes.c_void_p), None)
        else:
            raise CredentialError(f"macOS Keychain lookup failed ({status})")
        if result != 0:
            raise CredentialError(f"macOS Keychain write failed ({result})")

    def _keychain_get(self) -> str | None:
        if platform.system() != "Darwin":
            return None
        security, core = self._frameworks()
        # Never let a read raise an unlock dialog: without a screen (CI, SSH, launchd) nobody can answer it and
        # the lookup blocks forever. A locked keychain simply reads as "no stored credential".
        previous = ctypes.c_ubyte(1)
        security.SecKeychainGetUserInteractionAllowed(ctypes.byref(previous))
        security.SecKeychainSetUserInteractionAllowed(0)
        try:
            for service, account in ((KEYCHAIN_SERVICE, KEYCHAIN_ACCOUNT), *LEGACY_KEYCHAIN_ENTRIES):
                value = self._keychain_get_entry(security, core, service, account)
                if value:
                    return value
            return None
        finally:
            security.SecKeychainSetUserInteractionAllowed(previous.value)

    @staticmethod
    def _keychain_get_entry(security, core, service_name: str, account_name: str) -> str | None:
        """Read one trusted Keychain entry without logging or persisting it."""
        service = service_name.encode("utf-8")
        account = account_name.encode("utf-8")
        length = ctypes.c_uint32()
        data = ctypes.c_void_p()
        item = ctypes.c_void_p()
        status = security.SecKeychainFindGenericPassword(
            None, len(service), service, len(account), account,
            ctypes.byref(length), ctypes.byref(data), ctypes.byref(item))
        if status in (ERR_ITEM_NOT_FOUND, ERR_INTERACTION_NOT_ALLOWED):
            return None
        if status != 0:
            raise CredentialError(f"macOS Keychain lookup failed ({status})")
        try:
            raw = ctypes.string_at(data, length.value)
            return raw.decode("ascii").strip() or None
        except (UnicodeDecodeError, ValueError) as exc:
            raise CredentialError("stored TypeSafe credential is invalid") from exc
        finally:
            security.SecKeychainItemFreeContent(None, data)
            if item:
                core.CFRelease(item)

    @staticmethod
    def _frameworks():
        try:
            security = ctypes.CDLL("/System/Library/Frameworks/Security.framework/Security")
            core = ctypes.CDLL("/System/Library/Frameworks/CoreFoundation.framework/CoreFoundation")
        except OSError as exc:
            raise CredentialError("macOS Keychain API is unavailable") from exc
        security.SecKeychainFindGenericPassword.restype = ctypes.c_int32
        security.SecKeychainFindGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.POINTER(ctypes.c_uint32), ctypes.POINTER(ctypes.c_void_p), ctypes.POINTER(ctypes.c_void_p)]
        security.SecKeychainAddGenericPassword.restype = ctypes.c_int32
        security.SecKeychainAddGenericPassword.argtypes = [
            ctypes.c_void_p, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_char_p,
            ctypes.c_uint32, ctypes.c_void_p, ctypes.POINTER(ctypes.c_void_p)]
        security.SecKeychainItemModifyAttributesAndData.restype = ctypes.c_int32
        security.SecKeychainItemModifyAttributesAndData.argtypes = [
            ctypes.c_void_p, ctypes.c_void_p, ctypes.c_uint32, ctypes.c_void_p]
        security.SecKeychainItemFreeContent.restype = ctypes.c_int32
        security.SecKeychainItemFreeContent.argtypes = [ctypes.c_void_p, ctypes.c_void_p]
        security.SecKeychainSetUserInteractionAllowed.restype = ctypes.c_int32
        security.SecKeychainSetUserInteractionAllowed.argtypes = [ctypes.c_ubyte]
        security.SecKeychainGetUserInteractionAllowed.restype = ctypes.c_int32
        security.SecKeychainGetUserInteractionAllowed.argtypes = [ctypes.POINTER(ctypes.c_ubyte)]
        core.CFRelease.argtypes = [ctypes.c_void_p]
        return security, core
