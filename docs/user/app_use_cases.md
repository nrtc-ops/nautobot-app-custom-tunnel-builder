# IOS-XE Configuration Reference

This document describes the exact IOS-XE configuration blocks that the `BuildIpsecTunnel` job generates and pushes to the device.

---

## Full Configuration Template

The following shows every command block in the order they are sent via `send_config_set()`. Placeholders correspond directly to form fields.

```text
! ============================================================
! IKEv2 Proposal
! ============================================================
crypto ikev2 proposal <ikev2_proposal_name>
 encryption <ike_encryption>
 integrity <ike_integrity>
 group <ike_dh_group>

! ============================================================
! IKEv2 Policy
! ============================================================
crypto ikev2 policy <ikev2_policy_name>
 proposal <ikev2_proposal_name>

! ============================================================
! IKEv2 Keyring  (pre-shared key per peer)
! ============================================================
crypto ikev2 keyring <ikev2_keyring_name>
 peer PEER_<remote_peer_ip_underscored>
  address <remote_peer_ip>
  pre-shared-key local <pre_shared_key>
  pre-shared-key remote <pre_shared_key>

! ============================================================
! IKEv2 Profile
! ============================================================
crypto ikev2 profile <ikev2_profile_name>
 match identity remote address <remote_peer_ip> 255.255.255.255
 authentication local pre-share
 authentication remote pre-share
 keyring local <ikev2_keyring_name>
 lifetime <ike_lifetime>

! ============================================================
! IPsec Transform-Set
! ============================================================
! (non-GCM)
crypto ipsec transform-set <ipsec_transform_set_name> <ipsec_encryption> <ipsec_integrity>
 mode tunnel

! (GCM — no separate integrity)
crypto ipsec transform-set <ipsec_transform_set_name> <ipsec_encryption>
 mode tunnel

! ============================================================
! IPsec Profile
! ============================================================
crypto ipsec profile <ipsec_profile_name>
 set transform-set <ipsec_transform_set_name>
 set ikev2-profile <ikev2_profile_name>
 set security-association lifetime seconds <ipsec_lifetime>

! ============================================================
! Tunnel Interface (VTI)
! ============================================================
interface Tunnel<tunnel_number>
 ip address <tunnel_ip> <tunnel_mask>
 tunnel source <tunnel_source_interface>
 tunnel destination <remote_peer_ip>
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile <ipsec_profile_name>
 no shutdown
```

After all configuration lines are pushed, `save_config()` runs `copy running-config startup-config`.

---

## Worked Example

**Form inputs:**

| Field | Value |
|-------|-------|
| Device | `csr1-lab` (primary IP `10.0.0.1`) |
| Tunnel Number | `100` |
| Tunnel Source | `GigabitEthernet1` |
| Tunnel IP | `10.255.0.1/30` |
| Remote Peer IP | `203.0.113.1` |
| IKEv2 Proposal Name | `IKEv2-PROPOSAL` |
| IKEv2 Policy Name | `IKEv2-POLICY` |
| IKEv2 Keyring Name | `IKEv2-KEYRING` |
| IKEv2 Profile Name | `IKEv2-PROFILE` |
| IKE Encryption | `aes-cbc-256` |
| IKE Integrity | `sha256` |
| IKE DH Group | `19` |
| IKE Lifetime | `86400` |
| Transform-Set Name | `IPSEC-TS` |
| IPsec Profile Name | `IPSEC-PROFILE` |
| IPsec Encryption | `esp-aes 256` |
| IPsec Integrity | `esp-sha256-hmac` |
| IPsec Lifetime | `3600` |
| Pre-Shared Key | `MySuperSecretKey` |

**Generated configuration:**

```text
crypto ikev2 proposal IKEv2-PROPOSAL
 encryption aes-cbc-256
 integrity sha256
 group 19
crypto ikev2 policy IKEv2-POLICY
 proposal IKEv2-PROPOSAL
crypto ikev2 keyring IKEv2-KEYRING
 peer PEER_203_0_113_1
  address 203.0.113.1
  pre-shared-key local MySuperSecretKey
  pre-shared-key remote MySuperSecretKey
crypto ikev2 profile IKEv2-PROFILE
 match identity remote address 203.0.113.1 255.255.255.255
 authentication local pre-share
 authentication remote pre-share
 keyring local IKEv2-KEYRING
 lifetime 86400
crypto ipsec transform-set IPSEC-TS esp-aes 256 esp-sha256-hmac
 mode tunnel
crypto ipsec profile IPSEC-PROFILE
 set transform-set IPSEC-TS
 set ikev2-profile IKEv2-PROFILE
 set security-association lifetime seconds 3600
interface Tunnel100
 ip address 10.255.0.1 255.255.255.252
 tunnel source GigabitEthernet1
 tunnel destination 203.0.113.1
 tunnel mode ipsec ipv4
 tunnel protection ipsec profile IPSEC-PROFILE
 no shutdown
```

---

## Verifying the Tunnel on IOS-XE

After the job completes successfully, run these commands on the device to verify:

```text
! Check IKEv2 SA state
show crypto ikev2 sa

! Check IPsec SA state (should show encaps/decaps incrementing)
show crypto ipsec sa

! Check tunnel interface status
show interfaces Tunnel100

! Check IKEv2 profile
show crypto ikev2 profile IKEv2-PROFILE
```

---

## Encryption Algorithm Reference

### IKEv2 (Phase 1)

| Form Value | IOS-XE Keyword | Notes |
|-----------|----------------|-------|
| `aes-cbc-128` | `encryption aes-cbc-128` | Acceptable; prefer 256 |
| `aes-cbc-256` | `encryption aes-cbc-256` | Recommended |
| `aes-gcm-128` | `encryption aes-gcm-128` | Provides integrity natively for IKE |
| `aes-gcm-256` | `encryption aes-gcm-256` | Recommended for GCM |

### IPsec (Phase 2)

| Form Value | IOS-XE Keyword | HMAC Required? |
|-----------|----------------|---------------|
| `esp-aes 128` | `esp-aes 128` | Yes |
| `esp-aes 256` | `esp-aes 256` | Yes |
| `esp-gcm 128` | `esp-gcm 128` | **No** (select None) |
| `esp-gcm 256` | `esp-gcm 256` | **No** (select None) |

### DH Groups

| Form Value | Group | Key Material |
|-----------|-------|-------------|
| `14` | MODP 2048-bit | Acceptable; legacy |
| `19` | ECP 256-bit | Recommended |
| `20` | ECP 384-bit | High-security |
| `21` | ECP 521-bit | Maximum security |

---

## Removing a Tunnel

The app does not currently implement tunnel removal. To remove a tunnel manually:

```text
no interface Tunnel100
no crypto ipsec profile IPSEC-PROFILE
no crypto ipsec transform-set IPSEC-TS
no crypto ikev2 profile IKEv2-PROFILE
no crypto ikev2 keyring IKEv2-KEYRING
no crypto ikev2 policy IKEv2-POLICY
no crypto ikev2 proposal IKEv2-PROPOSAL
```

Run `copy running-config startup-config` after cleanup.
