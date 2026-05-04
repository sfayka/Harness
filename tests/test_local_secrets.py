from __future__ import annotations

import os
import subprocess
import unittest
from unittest.mock import patch

from modules.local_secrets import (
    create_secret_store,
    InMemorySecretStore,
    LinuxSecretServiceSecretStore,
    MacOSKeychainSecretStore,
    SecretNotFoundError,
    SecretProviderUnavailableError,
    UnsupportedPlatformSecretStore,
    collect_secret_statuses,
    load_runtime_managed_secrets_into_environment,
    secret_status_payload,
)


class MacOSKeychainSecretStoreTests(unittest.TestCase):
    def test_reads_secret_from_security_command(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ghp_secret\n", stderr="")

        store = MacOSKeychainSecretStore(
            command_runner=runner,
            platform_name="Darwin",
            security_bin="/usr/bin/security",
        )

        value = store.get_secret("github_token")

        self.assertEqual(value, "ghp_secret")
        self.assertEqual(calls[0][:2], ["/usr/bin/security", "find-generic-password"])
        self.assertIn("github_token", calls[0])

    def test_missing_keychain_item_raises_not_found(self) -> None:
        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                44,
                stdout="",
                stderr="security: SecKeychainSearchCopyNext: The specified item could not be found.",
            )

        store = MacOSKeychainSecretStore(
            command_runner=runner,
            platform_name="Darwin",
            security_bin="/usr/bin/security",
        )

        with self.assertRaises(SecretNotFoundError):
            store.get_secret("linear_api_key")

    def test_non_macos_keychain_is_unavailable(self) -> None:
        store = MacOSKeychainSecretStore(platform_name="Linux", security_bin="/usr/bin/security")

        with self.assertRaises(SecretProviderUnavailableError):
            store.get_secret("github_token")

    def test_stores_and_deletes_secret_without_shell(self) -> None:
        calls: list[list[str]] = []

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            calls.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="", stderr="")

        store = MacOSKeychainSecretStore(
            command_runner=runner,
            platform_name="Darwin",
            security_bin="/usr/bin/security",
        )

        store.set_secret("github_token", "ghp_secret")
        deleted = store.delete_secret("github_token")

        self.assertTrue(deleted)
        self.assertEqual(calls[0][1], "add-generic-password")
        self.assertEqual(calls[1][1], "delete-generic-password")
        self.assertNotIn("shell=True", " ".join(calls[0]))


class LocalSecretStatusTests(unittest.TestCase):
    def test_create_secret_store_selects_macos_keychain_on_darwin(self) -> None:
        store = create_secret_store(platform_name="Darwin")

        self.assertIsInstance(store, MacOSKeychainSecretStore)
        self.assertEqual(store.provider_name, "macos-keychain")

    def test_create_secret_store_selects_linux_placeholder_on_linux(self) -> None:
        store = create_secret_store(platform_name="Linux")

        self.assertIsInstance(store, LinuxSecretServiceSecretStore)
        self.assertEqual(store.provider_name, "linux-secret-service")

    def test_create_secret_store_falls_back_on_unsupported_platform(self) -> None:
        store = create_secret_store(platform_name="FreeBSD")

        self.assertIsInstance(store, UnsupportedPlatformSecretStore)
        self.assertEqual(store.provider_name, "unsupported-freebsd")

    def test_linux_secret_store_reports_unavailable_until_implemented(self) -> None:
        store = LinuxSecretServiceSecretStore(platform_name="Linux")

        with self.assertRaises(SecretProviderUnavailableError):
            store.get_secret("github_token")

    def test_loads_runtime_managed_secrets_into_missing_environment_vars(self) -> None:
        store = InMemorySecretStore(
            {
                "github_token": "ghp_secret",
                "linear_api_key": "lin_secret",
            }
        )

        with patch.dict(os.environ, {}, clear=True):
            statuses = load_runtime_managed_secrets_into_environment(store=store)

            self.assertEqual(os.environ["GITHUB_TOKEN"], "ghp_secret")
            self.assertEqual(os.environ["LINEAR_API_KEY"], "lin_secret")

        status_by_name = {status.name: status for status in statuses}
        self.assertEqual(status_by_name["github_token"].status, "configured")
        self.assertEqual(status_by_name["github_token"].source, "memory")
        self.assertEqual(status_by_name["repair_callback_bearer_token"].status, "missing")

    def test_loads_github_token_from_authenticated_github_cli_when_secret_missing(self) -> None:
        commands: list[list[str]] = []

        def keychain_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                44,
                stdout="",
                stderr="security: SecKeychainSearchCopyNext: The specified item could not be found.",
            )

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            commands.append(command)
            return subprocess.CompletedProcess(command, 0, stdout="ghp_from_cli\n", stderr="")

        store = MacOSKeychainSecretStore(
            command_runner=keychain_runner,
            platform_name="Darwin",
            security_bin="/usr/bin/security",
        )

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_secrets.shutil.which", return_value="/usr/bin/gh"),
        ):
            statuses = load_runtime_managed_secrets_into_environment(
                store=store,
                command_runner=runner,
            )

            self.assertEqual(os.environ["GITHUB_TOKEN"], "ghp_from_cli")

        status_by_name = {status.name: status for status in statuses}
        self.assertEqual(status_by_name["github_token"].status, "configured")
        self.assertEqual(status_by_name["github_token"].source, "github-cli")
        self.assertEqual(commands, [["/usr/bin/gh", "auth", "token"]])

    def test_existing_environment_vars_win_over_runtime_managed_secrets(self) -> None:
        store = InMemorySecretStore({"github_token": "keychain-secret"})

        with patch.dict(os.environ, {"GITHUB_TOKEN": "env-secret"}, clear=True):
            load_runtime_managed_secrets_into_environment(store=store)

            self.assertEqual(os.environ["GITHUB_TOKEN"], "env-secret")

    def test_secret_status_payload_marks_required_missing_without_values(self) -> None:
        store = InMemorySecretStore({"github_token": "ghp_secret"})

        with patch.dict(os.environ, {}, clear=True):
            statuses = collect_secret_statuses(store=store, required_names=["linear_api_key"])

        payload = secret_status_payload(statuses)
        serialized = str(payload)

        self.assertEqual(payload["status"], "missing_required_secrets")
        self.assertEqual(payload["missing_required"], ["linear_api_key"])
        self.assertNotIn("ghp_secret", serialized)

    def test_secret_status_reports_github_cli_source_without_values(self) -> None:
        def keychain_runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(
                command,
                44,
                stdout="",
                stderr="security: SecKeychainSearchCopyNext: The specified item could not be found.",
            )

        def runner(command: list[str]) -> subprocess.CompletedProcess[str]:
            return subprocess.CompletedProcess(command, 0, stdout="ghp_from_cli\n", stderr="")

        store = MacOSKeychainSecretStore(
            command_runner=keychain_runner,
            platform_name="Darwin",
            security_bin="/usr/bin/security",
        )

        with (
            patch.dict(os.environ, {}, clear=True),
            patch("modules.local_secrets.shutil.which", return_value="/usr/bin/gh"),
        ):
            statuses = collect_secret_statuses(
                store=store,
                command_runner=runner,
            )

        payload = secret_status_payload(statuses)
        serialized = str(payload)
        status_by_name = {status.name: status for status in statuses}

        self.assertEqual(status_by_name["github_token"].status, "configured")
        self.assertEqual(status_by_name["github_token"].source, "github-cli")
        self.assertNotIn("ghp_from_cli", serialized)


if __name__ == "__main__":
    unittest.main()
