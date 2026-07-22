# TunnelStatusView authorization

## Problem

`GET /api/plugins/tunnel-builder/api/tunnel-status/<id>/` authorizes with
`IsAuthenticated` only and looks the tunnel up with an unrestricted
`VPNTunnel.objects.get(pk=...)`. Any holder of a valid Nautobot token can read
any tunnel's status — and its pre-shared key on the first post-provision poll —
by UUID. The tenancy boundary is enforced only by the portal (which never hands
a member another member's tunnel id) and by "only the service account has a
token." Nautobot itself does not enforce it.

## Fix

Make the lookup honor Nautobot ObjectPermissions:

```python
tunnel = VPNTunnel.objects.restrict(request.user, "view").get(pk=tunnel_id)
```

`restrict(user, "view")` returns only the tunnels the user's ObjectPermissions
grant for the view action (all, for a superuser; a tenant/attribute-constrained
subset for a scoped account; nothing for a token with no VPNTunnel view
permission). A token that cannot view the tunnel gets the same 404 as a missing
tunnel — no existence or PSK leak.

This moves the boundary from "any authenticated token" to "principals explicitly
granted `vpn.view_vpntunnel`," and lets operators scope *other* tokens away from
member PSKs without any further code. The portal service account legitimately
polls every member's tunnel, so it holds an unconstrained (or
`member_connect_managed`-constrained) view permission; that is deliberate and
documented, not a hole.

## Behavior matrix

| Caller | Result |
|---|---|
| Superuser (dev harness `portal-svc`) | sees all — E2E unchanged |
| Service account with `view vpntunnel` | sees all member tunnels — poll works |
| Token without `view vpntunnel` | 404 for every tunnel — fail closed |

## Out of scope

Per-member scoping of the portal service account (it is cross-tenant by
design); PSK-specific permission beyond view; authorization on
`PortalTunnelRequestView` (build) — tracked separately.
