"""App-managed secret storage for the local Harness runtime."""

from __future__ import annotations

import os
import platform
import shutil
import subprocess
from dataclasses import asdict, dataclass
from typing import Callable, Iterable, Protocol


KEYCHAIN_SERVICE = "com.knoxanalytics.harness.local-runtime"


class LocalSecretError(ValueError):
    """Operator-readable local secret failure."""


class SecretNotFoundError(LocalSecretError):
    """Requested secret is not stored in the configured provider."""


class SecretProviderUnavailableError(LocalSecretError):
    """The configured secret provider cannot be used on this machine."""


class SecretStore(Protocol):
    def get_secret(self, name: str) -> str:
        """Return a secret value or raise a LocalSecretError."""

    def set_secret(self, name: str, value: str) -> None:
        """Store a secret value."""

    def delete_secret(self, name: str) -> bool:
        """Delete a stored secret. Return False when it was already absent."""


@dataclass(frozen=True)
class SecretDefinition:
    name: str
    env_var: str
    label: str
    purpose: str
    required_for: str


@dataclass(frozen=True)
class SecretStatus:
    name: str
    env_var: str
    label: str
    purpose: str
    required_for: str
    status: str
    source: str | None
    required: bool
    message: str
    next_action: str

    def asdict(self) -> dict[str, object]:
        return asdict(self)


SECRET_DEFINITIONS: tuple[SecretDefinition, ...] = (
    SecretDefinition(
        name="github_token",
        env_var="GITHUB_TOKEN",
        label="GitHub token",
        purpose="Validates repository, branch, commit, pull-request, and changed-file proof.",
        required_for="GitHub artifact verification and repair workflows.",
    ),
    SecretDefinition(
        name="linear_api_key",
        env_var="LINEAR_API_KEY",
        label="Linear API key",
        purpose="Reads and updates Linear work state when a workflow uses Linear coordination.",
        required_for="Linear synchronization and write-back workflows.",
    ),
    SecretDefinition(
        name="repair_callback_bearer_token",
        env_var="OPENCLAW_REPAIR_BEARER_TOKEN",
        label="Repair callback bearer token",
        purpose="Authenticates HTTP repair callbacks for the current desktop-agent bridge.",
        required_for="Bearer-protected repair callback workflows.",
    ),
)

SECRET_DEFINITIONS_BY_NAME = {definition.name: definition for definition in SECRET_DEFINITIONS}

CommandRunner = Callable[[list[str]], subprocess.CompletedProcess[str]]


def get_secret_definition(name: str) -> SecretDefinition:
    try:
        return SECRET_DEFINITIONS_BY_NAME[name]
    except KeyError as error:
        names = ", ".join(sorted(SECRET_DEFINITIONS_BY_NAME))
        raise LocalSecretError(f"Unknown Harness secret {name!r}. Expected one of: {names}.") from error


class MacOSKeychainSecretStore:
    """Store local app secrets in macOS Keychain through the `security` command."""

    def __init__(
        self,
        *,
        service: str = KEYCHAIN_SERVICE,
        command_runner: CommandRunner | None = None,
        platform_name: str | None = None,
        security_bin: str | None = None,
    ) -> None:
        self.service = service
        self._command_runner = command_runner or _run_command
        self._platform_name = platform_name or platform.system()
        self._security_bin = security_bin

    @property
    def provider_name(self) -> str:
        return "macos-keychain"

    def get_secret(self, name: str) -> str:
        definition = get_secret_definition(name)
        result = self._run_security(
            [
                "find-generic-password",
                "-s",
                self.service,
                "-a",
                definition.name,
                "-w",
            ]
        )
        if result.returncode == 0:
            value = result.stdout.rstrip("\n")
            if value:
                return value
            raise SecretNotFoundError(f"{definition.label} is empty in macOS Keychain.")
        if _security_result_is_missing(result):
            raise SecretNotFoundError(f"{definition.label} is not stored in macOS Keychain.")
        raise LocalSecretError(_security_error_message(result, f"Could not read {definition.label}."))

    def set_secret(self, name: str, value: str) -> None:
        definition = get_secret_definition(name)
        if not value:
            raise LocalSecretError(f"{definition.label} cannot be empty.")
        result = self._run_security(
            [
                "add-generic-password",
                "-U",
                "-s",
                self.service,
                "-a",
                definition.name,
                "-l",
                definition.label,
                "-w",
                value,
            ]
        )
        if result.returncode != 0:
            raise LocalSecretError(_security_error_message(result, f"Could not store {definition.label}."))

    def delete_secret(self, name: str) -> bool:
        definition = get_secret_definition(name)
        result = self._run_security(
            [
                "delete-generic-password",
                "-s",
                self.service,
                "-a",
                definition.name,
            ]
        )
        if result.returncode == 0:
            return True
        if _security_result_is_missing(result):
            return False
        raise LocalSecretError(_security_error_message(result, f"Could not delete {definition.label}."))

    def _run_security(self, args: list[str]) -> subprocess.CompletedProcess[str]:
        security_bin = self._resolve_security_bin()
        return self._command_runner([security_bin, *args])

    def _resolve_security_bin(self) -> str:
        if self._platform_name != "Darwin":
            raise SecretProviderUnavailableError(
                "macOS Keychain is unavailable on this platform. "
                "Use developer env-file mode until the Linux secret provider is implemented."
            )
        if self._security_bin:
            return self._security_bin
        resolved = shutil.which("security")
        if not resolved:
            raise SecretProviderUnavailableError("The macOS `security` command was not found.")
        return resolved


class InMemorySecretStore:
    """Small test and fixture secret store. Not used for persisted app secrets."""

    provider_name = "memory"

    def __init__(self, values: dict[str, str] | None = None) -> None:
        self.values = dict(values or {})

    def get_secret(self, name: str) -> str:
        get_secret_definition(name)
        value = self.values.get(name)
        if not value:
            raise SecretNotFoundError(f"{name} is not stored.")
        return value

    def set_secret(self, name: str, value: str) -> None:
        get_secret_definition(name)
        if not value:
            raise LocalSecretError(f"{name} cannot be empty.")
        self.values[name] = value

    def delete_secret(self, name: str) -> bool:
        get_secret_definition(name)
        return self.values.pop(name, None) is not None


def load_app_managed_secrets_into_environment(
    *,
    store: SecretStore | None = None,
    overwrite: bool = False,
) -> list[SecretStatus]:
    """Populate missing runtime env vars from app-managed secrets.

    Existing environment variables win by default so developer env-file mode and
    explicitly exported variables keep working.
    """

    secret_store = store or MacOSKeychainSecretStore()
    statuses: list[SecretStatus] = []
    for definition in SECRET_DEFINITIONS:
        current_value = os.environ.get(definition.env_var)
        if current_value and not overwrite:
            statuses.append(_configured_status(definition, source="environment", required=False))
            continue
        try:
            value = secret_store.get_secret(definition.name)
        except SecretNotFoundError:
            statuses.append(_missing_status(definition, required=False))
        except SecretProviderUnavailableError as error:
            statuses.append(_unavailable_status(definition, str(error), required=False))
        except LocalSecretError as error:
            statuses.append(_error_status(definition, str(error), required=False))
        else:
            os.environ[definition.env_var] = value
            statuses.append(_configured_status(definition, source=_provider_name(secret_store), required=False))
    return statuses


def collect_secret_statuses(
    *,
    store: SecretStore | None = None,
    required_names: Iterable[str] = (),
) -> list[SecretStatus]:
    secret_store = store or MacOSKeychainSecretStore()
    required = set(required_names)
    for name in required:
        get_secret_definition(name)

    statuses: list[SecretStatus] = []
    for definition in SECRET_DEFINITIONS:
        is_required = definition.name in required
        if os.environ.get(definition.env_var):
            statuses.append(_configured_status(definition, source="environment", required=is_required))
            continue
        try:
            secret_store.get_secret(definition.name)
        except SecretNotFoundError:
            statuses.append(_missing_status(definition, required=is_required))
        except SecretProviderUnavailableError as error:
            statuses.append(_unavailable_status(definition, str(error), required=is_required))
        except LocalSecretError as error:
            statuses.append(_error_status(definition, str(error), required=is_required))
        else:
            statuses.append(_configured_status(definition, source=_provider_name(secret_store), required=is_required))
    return statuses


def secret_status_payload(statuses: list[SecretStatus]) -> dict[str, object]:
    missing_required = [
        status.name for status in statuses if status.required and status.status != "configured"
    ]
    provider_errors = [status.name for status in statuses if status.status in {"error", "unavailable"}]
    if missing_required:
        status = "missing_required_secrets"
    elif provider_errors:
        status = "degraded"
    else:
        status = "ok"
    return {
        "status": status,
        "provider": "app-managed-secret-store",
        "missing_required": missing_required,
        "secrets": [status_item.asdict() for status_item in statuses],
    }


def _configured_status(definition: SecretDefinition, *, source: str, required: bool) -> SecretStatus:
    return SecretStatus(
        name=definition.name,
        env_var=definition.env_var,
        label=definition.label,
        purpose=definition.purpose,
        required_for=definition.required_for,
        status="configured",
        source=source,
        required=required,
        message=f"{definition.label} is configured.",
        next_action="No action needed.",
    )


def _missing_status(definition: SecretDefinition, *, required: bool) -> SecretStatus:
    return SecretStatus(
        name=definition.name,
        env_var=definition.env_var,
        label=definition.label,
        purpose=definition.purpose,
        required_for=definition.required_for,
        status="missing",
        source=None,
        required=required,
        message=f"{definition.label} is not configured.",
        next_action=(
            f"Connect {definition.label} during setup or run "
            f"`harness secrets set {definition.name} --value-stdin`."
        ),
    )


def _unavailable_status(definition: SecretDefinition, message: str, *, required: bool) -> SecretStatus:
    return SecretStatus(
        name=definition.name,
        env_var=definition.env_var,
        label=definition.label,
        purpose=definition.purpose,
        required_for=definition.required_for,
        status="unavailable",
        source=None,
        required=required,
        message=message,
        next_action="Use developer env-file mode or install a supported local app secret provider.",
    )


def _error_status(definition: SecretDefinition, message: str, *, required: bool) -> SecretStatus:
    return SecretStatus(
        name=definition.name,
        env_var=definition.env_var,
        label=definition.label,
        purpose=definition.purpose,
        required_for=definition.required_for,
        status="error",
        source=None,
        required=required,
        message=message,
        next_action="Open Harness setup and reconnect this integration.",
    )


def _provider_name(store: SecretStore) -> str:
    return str(getattr(store, "provider_name", store.__class__.__name__))


def _run_command(command: list[str]) -> subprocess.CompletedProcess[str]:
    return subprocess.run(command, check=False, capture_output=True, text=True)


def _security_result_is_missing(result: subprocess.CompletedProcess[str]) -> bool:
    stderr = (result.stderr or "").lower()
    return result.returncode == 44 or "could not be found" in stderr or "not be found" in stderr


def _security_error_message(result: subprocess.CompletedProcess[str], fallback: str) -> str:
    stderr = (result.stderr or "").strip()
    if not stderr:
        return fallback
    return f"{fallback} Keychain returned: {stderr}"
