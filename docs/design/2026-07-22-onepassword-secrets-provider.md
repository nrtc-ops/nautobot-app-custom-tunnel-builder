# 1Password secrets provider (read path) — dev parity with prod

## Context

The plugin writes PSKs to 1Password via `onepassword-sdk` and creates a
Nautobot `Secret` with `provider="one-password"`. Both readers — the build
job (`jobs.py`, pushes PSK to the device) and `TunnelStatusView` (one-shot
member display) — call `secret.get_value()`, which resolves through Nautobot's
secrets-provider registry.

Prod registers the `one-password` provider via **NTC
`nautobot-secrets-providers[one-password]`**. The plugin's dev instance does
not (only `text-file`/`environment-variable`), so the real read path is only
exercised in prod; dev relies on `OP_DEV_BYPASS` → `text-file`. This closes
that gap so dev matches prod.

## The contract (from NTC `providers/one_password.py`, v3.2.0)

- Provider slug: `one-password` (hyphen) — **matches** the plugin's write; no
  slug change needed.
- Secret parameters it reads: `vault` (required), `item` (required), `field`
  (required, "password"), `section` (optional). Resolves `op://{vault}/{item}/{field}`.
- Token: `PLUGINS_CONFIG["nautobot_secrets_providers"]["one_password"]["vaults"][<vault>]["token"]`
  (or a top-level `["one_password"]["token"]` fallback).

## Mismatch to fix

The plugin's `get_secret_provider_params` returns `{"item_id", "field"}` — the
NTC provider would `KeyError` on the missing `vault`/`item`. Realign the write
side to emit `{"vault", "item", "field"}`:

- `vault` = `OP_VAULT_UUID` (the SDK write target; also the `op://` vault ref).
- `item` = the SDK-created item id (resolvable as `op://{vault}/{id}/password`).
- `field` = `"password"`.

The `text-file` dev-bypass branch is unchanged.

## Changes

1. **Dep** (`pyproject.toml`, dev group): `nautobot-secrets-providers` with the
   `one-password` extra. Prod already installs it; this gives the dev image parity.
2. **Config** (`development/nautobot_config.py`): add `nautobot_secrets_providers`
   to `PLUGINS`; add `PLUGINS_CONFIG["nautobot_secrets_providers"]["one_password"]["vaults"]`
   keyed by `OP_VAULT_UUID` → `{token: OP_SERVICE_ACCOUNT_TOKEN}`, populated only
   when those env vars are set (bypass/offline dev leaves it empty).
3. **Write params** (`onepassword_utils.get_secret_provider_params`): emit the
   NTC-shaped `{vault, item, field}`.
4. **Rebuild** the dev image so the package is installed and the provider registers.

## Tests

- `get_secret_provider_params` returns `{vault, item, field}` with values from
  `OP_VAULT_UUID`/item id (bypass path still returns `text-file`).
- Provider registration: `one-password` present in the registry (integration,
  after rebuild).
- Existing `get_value()` consumers (build job, status endpoint) unchanged.

## Follow-on (separate step): dev 1Password logistics

Create a dedicated dev vault + a service account scoped to only that vault;
set `OP_DEV_BYPASS=false`, `OP_SERVICE_ACCOUNT_TOKEN`, `OP_VAULT_UUID` in
`creds.env` (gitignored); run a DEBUG-off E2E so a PSK round-trips through the
real provider. No `/tmp` plaintext.
