# App-Managed Secrets

Harness local app builds must not ask normal users to edit `.env.local`.
Non-secret runtime config lives in `config.json`; tokens and integration credentials live behind the app-managed secret provider.

## Secret Provider

macOS v1 uses Keychain through the Harness service namespace:

```text
com.knoxanalytics.harness.local-runtime
```

The runtime secret boundary is implemented in [`modules/local_secrets.py`](../../modules/local_secrets.py).
It exposes named secrets, redacted status output, and provider operations without writing secret values to `config.json`, logs, or JSON status payloads.

Current secret names:

- `github_token`: maps to `GITHUB_TOKEN`
- `linear_api_key`: maps to `LINEAR_API_KEY`
- `repair_callback_bearer_token`: maps to `OPENCLAW_REPAIR_BEARER_TOKEN`

The `OPENCLAW_REPAIR_BEARER_TOKEN` env name remains the current concrete repair-adapter variable. It is not the product boundary. The stable local-app boundary is the named Harness secret.

Provider selection is platform-aware at the Python boundary:

- `macos-keychain` on Darwin
- `linux-secret-service` as the deferred Linux provider contract
- `unsupported-<platform>` on other local-app platforms until a provider exists

Linux Secret Service support is not implemented in this slice. The important part is that the runtime no longer hard-codes the macOS provider name into status or environment surfaces.

## CLI Contract

The packaged app can call the same command surface that developers can run from a checkout:

```bash
python3 -m modules.local_runtime --json secrets status
python3 -m modules.local_runtime --json secrets status --require github_token
printf '%s' "$GITHUB_TOKEN" | python3 -m modules.local_runtime --json secrets set github_token --value-stdin
python3 -m modules.local_runtime --json secrets delete github_token
```

`secrets status` never prints secret values. When a workflow requires a credential, pass `--require <name>` so missing or unavailable credentials return a setup-required exit code instead of looking like a healthy state.

`secrets set` intentionally requires `--value-stdin` so users and app shells do not put tokens in shell history.

The future native macOS shell should prefer the Keychain APIs directly when storing user-entered tokens.
Use the same service value above and the Harness secret name as the Keychain account.
The Python CLI exists as a portable contract and developer fallback; the native app does not need to shell out to store secrets.

## Runtime Behavior

`harness start` and `harness serve` apply app-managed config, then load available app-managed secrets into process environment variables before starting the backend.

Existing environment variables win. This preserves developer mode:

- repo-root `.env.local` remains valid for native local development
- exported shell variables remain valid for CI and one-off debugging
- app-managed Keychain secrets are the normal packaged-app path

Missing secrets do not block the local API from starting because GitHub, Linear, and executor integrations are optional until a chosen workflow needs them.
Workflows that need a credential should call `secrets status --require <name>` or surface the integration-specific setup error.

## Security Rules

- Do not write token values to `config.json`.
- Do not write token values to logs.
- Do not return token values from CLI JSON.
- Do not teach packaged-app users to edit `.env.local`.
- Do not couple the secret model to OpenClaw or Hermes. Use Harness secret names and map them to current env vars at the runtime boundary.

## Linux Portability

Linux support will use the same Harness secret names and CLI/status contract.
The provider can later be Secret Service/libsecret or an encrypted local fallback, but it should not change the runtime env mapping or the onboarding contract.

See [linux-portability-contract.md](linux-portability-contract.md).
