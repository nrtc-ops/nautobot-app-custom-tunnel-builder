# PortalTunnelRequestView authorization

## Problem

`POST /api/plugins/tunnel-builder/api/portal-request/` is gated on
`IsAuthenticated` only. Any holder of a valid Nautobot token can drive the full
provisioning side effect: create the member Device/VPN/VPNTunnel/VPNProfile/
endpoints/prefixes/IPs + per-member namespace, generate a PSK into 1Password,
and enqueue `PortalBuildIpsecTunnel` — which SSHes IPsec crypto config onto a
real IOS-XE concentrator. This is a write/device-config capability, not a read;
arguably higher impact than the status-read gap already closed. The boundary
today rests on "only the portal service account has a token," not on Nautobot.

## Fix

Gate the create on the Nautobot **add** permission for VPNTunnel — the
representative capability for "provision a tunnel" — mirroring the status
endpoint's `view` gate:

```python
if not request.user.has_perm("vpn.add_vpntunnel"):
    return Response({"detail": "..."}, status=status.HTTP_403_FORBIDDEN)
```

`has_perm(perm)` with no object returns True for a superuser, or for a user
holding any ObjectPermission granting `add` on VPNTunnel (constrained or not),
and False otherwise — the correct gate for a create, where there is no
pre-existing object to `restrict()`. Runs after `IsAuthenticated`, so
unauthenticated still 401s; a token without the permission now 403s instead of
provisioning.

Gate on the single representative permission (`vpn.add_vpntunnel`), not `add`
on every model the flow touches — the ORM creates run server-side and aren't
per-model permission-enforced; requiring add on Device/Prefix/Secret/etc. would
be brittle and over-scoped.

## Behavior matrix

| Caller | Result |
|---|---|
| Superuser (dev harness `portal-svc`) | provisions — E2E unchanged |
| Service account with `add vpntunnel` | provisions — portal flow works |
| Token without `add vpntunnel` | 403, nothing created |
| Unauthenticated | 401 (unchanged) |

## Test ripple

Every existing build-endpoint test represents the properly-permissioned service
account, so each grants `vpn.add_vpntunnel` in `setUp` (same pattern as
`TunnelStatusTest` granting `view`): PortalTunnelCreationTest,
PortalTunnelTenancyTest, PortalRequestValidationTest, EndToEndConfigGenerationTest,
and TunnelStatusTest (its `_post_tunnel` helper posts a build). New RED test: a
token with `view` but not `add` gets 403 from POST.

## Prod

The portal service account needs `vpn.add_vpntunnel` alongside the
`vpn.view_vpntunnel` the status endpoint already requires. Document both as the
minimum grant. (Follows the tunnel-status authz design, 2026-07-22.)
