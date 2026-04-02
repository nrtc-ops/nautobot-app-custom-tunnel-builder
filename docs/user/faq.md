# Frequently Asked Questions

## What platforms are supported?

Currently only Cisco IOS-XE devices are supported. The device must have a `platform.network_driver` set to `cisco_ios` or `cisco_xe` in Nautobot and must have a primary IPv4 address assigned for SSH connectivity.

## Should I use IKEv1 or IKEv2?

IKEv2 is strongly recommended for all new deployments. It offers improved security, built-in NAT traversal, and better performance during re-keying. Use IKEv1 only when the remote peer does not support IKEv2.

## What type of IPsec tunnel does this app build?

This app builds **policy-based** IPsec tunnels using crypto maps and crypto ACLs. It does **not** build route-based (VTI) tunnels.

## How are device credentials managed?

SSH credentials are read from environment variables on the Nautobot server:

- `NAUTOBOT_DEVICE_USERNAME` — SSH username
- `NAUTOBOT_DEVICE_PASSWORD` — SSH password
- `NAUTOBOT_DEVICE_ENABLE_SECRET` — Enable secret (optional)
- `NAUTOBOT_DEVICE_SSH_PORT` — SSH port (defaults to 22)

The pre-shared key (PSK) is treated as a `SensitiveVariable` and is never stored in Nautobot or logged in job output.

## Why can't I select DH groups 2 or 5 with IKEv2?

DH groups 2 (1024-bit MODP) and 5 (1536-bit MODP) are considered insecure by modern standards and are not supported in IKEv2 proposals on IOS-XE. Use group 14 or higher.

## Why does GCM encryption require "None" for integrity?

GCM (Galois/Counter Mode) is an authenticated encryption algorithm that provides both confidentiality and integrity in a single operation. Specifying a separate HMAC integrity algorithm alongside GCM is redundant and not supported by IOS-XE.

## What happens if the configuration push fails?

If the device returns an error during the SSH config push, the job will detect the IOS-XE error pattern (lines beginning with `%`) and raise an `IosXeConfigError`. The job result in Nautobot will show a failure status with the error details. The device configuration may be partially applied — review the device running config to assess the state.

## Can I use this app without the Portal API?

Yes. The web form at **Network Tools > VPN > Build IPsec Tunnel** and the Nautobot Job can be used independently of the Portal API. The Portal API is an optional REST interface for automated/self-service provisioning.
