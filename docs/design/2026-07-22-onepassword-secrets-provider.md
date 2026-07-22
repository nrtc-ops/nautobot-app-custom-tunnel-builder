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

## Version reality (important)

Only the **4.x** line of `nautobot-secrets-providers` supports Nautobot 3.x
(`nautobot >=3.0.0,<4.0.0`). The newest release **on PyPI is 3.2.0, which is
Nautobot-2.x only** (`max_version 2.9999`) — installing it makes Nautobot 3.x
refuse to start. 4.x is not published to PyPI yet, so we install it from the
NTC git `develop` branch (currently `4.0.2a0`), which is what prod runs.

Wrinkle: the provider's `onepassword` extra advertises a stale
`onepassword-sdk >=0.1.2,<0.2.0`, but the develop-branch provider code targets
the same 0.4.x async `Client` API the plugin's write side uses. The plugin's
direct `onepassword-sdk >=0.3.0,<1.0.0` wins resolution; the lock settles on
0.4.0, which both read and write code actually use. Don't "fix" the lock toward
the extra's 0.1.x cap.

## Changes

1. **Dep** (`pyproject.toml`, dev group): `nautobot-secrets-providers` from
   `git = ...@develop` with the `one-password` extra — the 3.x-compatible 4.x
   line. Prod installs the same provider alongside Nautobot; this is dev parity.
   (Runtime/prod installation is managed at the Nautobot-deployment level, not
   as a runtime dep of this plugin — hence dev-group only.)
2. **Config** (`development/nautobot_config.py`): add `nautobot_secrets_providers`
   to `PLUGINS`; add `PLUGINS_CONFIG["nautobot_secrets_providers"]["one_password"]["vaults"]`
   keyed by `OP_VAULT_UUID` → `{token: OP_SERVICE_ACCOUNT_TOKEN}`, populated only
   when those env vars are set (bypass/offline dev leaves it empty).
3. **Write params** (`onepassword_utils.get_secret_provider_params`): emit the
   NTC-shaped `{vault, item, field}`.
4. **Rebuild** the dev image so the package is installed and the provider registers.

**Confirm the pin against prod:** dev pins `@develop` (a moving branch). If prod
pins a specific commit/tag or an internal-index build, align this dep to that
exact ref so dev and prod can't drift.

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
