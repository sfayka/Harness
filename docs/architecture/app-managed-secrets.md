# Runtime-Managed Secrets

Harness local CLI/web usage must not ask operators to edit `.env.local`.
Non-secret runtime config lives in `config.json`; tokens and integration credentials live behind the runtime-managed secret provider.

## Secret Provider

On macOS, the local runtime uses Keychain through the Harness service namespace:

```text
com.knoxanalytics.harness.local-runtime
```

The runtime secret boundary is implemented in [`modules/local_secrets.py`](../../modules/local_secrets.py).
It exposes named secrets, redacted status output, and provider operations without writing secret values to `config.json`, logs, or JSON status payloads.

Current secret names:

- `github_token`: maps to `GITHUB_TOKEN`
- `linear_api_key`: maps to `LINEAR_API_KEY`
- `repair_callback_bearer_token`: maps to `OPENCLAW_REPAIR_BEARER_TOKEN`

The `OPENCLAW_REPAIR_BEARER_TOKEN` env name remains the current concrete repair-adapter variable. It is not the product boundary. The stable local runtime boundary is the named Harness secret.

Provider selection is platform-aware at the Python boundary:

- `macos-keychain` on Darwin
- `linux-secret-service` as the deferred Linux provider contract
- `unsupported-<platform>` on other local platforms until a provider exists

Linux Secret Service support is not implemented in this slice. The important part is that the runtime no longer hard-codes the macOS provider name into status or environment surfaces.

## CLI Contract

Future packaged CLI/web builds can call the same command surface that developers can run from a checkout:

```bash
python3 -m modules.proofline_runtime --json secrets status
python3 -m modules.proofline_runtime --json secrets status --require github_token
printf '%s' "$GITHUB_TOKEN" | python3 -m modules.proofline_runtime --json secrets set github_token --value-stdin
python3 -m modules.proofline_runtime --json secrets delete github_token
```

`secrets status` never prints secret values. When a workflow requires a credential, pass `--require <name>` so missing or unavailable credentials return a setup-required exit code instead of looking like a healthy state.

`secrets set` intentionally requires `--value-stdin` so operators and wrapper shells do not put tokens in shell history.

The native macOS shell is deprecated. New credential flows should use the portable CLI/runtime contract unless a future packaging decision explicitly introduces a different shell boundary.

## Runtime Behavior

`proofline start` and `proofline serve` apply runtime-managed config, then load available runtime-managed secrets into process environment variables before starting the backend. Compatibility `harness ...` commands may keep doing the same during the staged rename.

Existing environment variables win. This preserves developer mode:

- repo-root `.env.local` remains valid for local development
- exported shell variables remain valid for CI and one-off debugging
- runtime-managed Keychain secrets are the normal macOS local-runtime path
- an authenticated GitHub CLI session can provide `github_token` locally through `gh auth token`
  when neither `GITHUB_TOKEN` nor the runtime-managed secret is configured

Missing secrets do not block the local API from starting because GitHub, Linear, and executor integrations are optional until a chosen workflow needs them.
Workflows that need a credential should call `secrets status --require <name>` or surface the integration-specific setup error.

## Security Rules

- Do not write token values to `config.json`.
- Do not write token values to logs.
- Do not return token values from CLI JSON.
- Do not teach operators to edit `.env.local` for normal local setup.
- Do not treat the GitHub CLI fallback as a source of completion truth; it is only a local credential source.
- Do not couple the secret model to OpenClaw or Hermes. Use Harness secret names and map them to current env vars at the runtime boundary.

## Linux Portability

Linux support will use the same Harness secret names and CLI/status contract.
The provider can later be Secret Service/libsecret or an encrypted local fallback, but it should not change the runtime env mapping or the onboarding contract.

See [linux-portability-contract.md](linux-portability-contract.md).
