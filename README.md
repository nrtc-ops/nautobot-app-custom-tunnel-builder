# Nautobot Custom Tunnel Builder

> **⚠️ Alpha Software**: This project is currently in **alpha** and is under active development. APIs, configuration options, and behavior may change between releases. Use in production environments is not recommended until a stable release is published.

An app for [Nautobot](https://github.com/nautobot/nautobot) that provides a ui/form for inputting tunnel configuration then builds device configurations and automated jobs to push to devices.

<p align="center">
  <img src="https://raw.githubusercontent.com/nrtc-ops/nautobot-app-custom-tunnel-builder/main/docs/images/icon-nautobot-custom-tunnel-builder.png" class="logo" height="200px">
  <br>
  <a href="https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions"><img src="https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/actions/workflows/ci.yml/badge.svg?branch=main"></a>
  <a href="https://pypi.org/project/nautobot-custom-tunnel-builder/"><img src="https://img.shields.io/pypi/v/nautobot-custom-tunnel-builder"></a>
  <a href="https://pypi.org/project/nautobot-custom-tunnel-builder/"><img src="https://img.shields.io/badge/status-alpha-orange"></a>
  <a href="https://pypi.org/project/nautobot-custom-tunnel-builder/"><img src="https://img.shields.io/pypi/dm/nautobot-custom-tunnel-builder"></a>
</p>

## Overview

A **Nautobot 3.x app** that provides a custom web form for building **policy-based IPsec tunnels** (IKEv1 or IKEv2) on Cisco IOS-XE devices (CSR 1000v, ASR 1000, ISR 4000).

Operators fill out the form, click **Build Tunnel**, and a Nautobot Job SSHes into the target device, generates and pushes the full crypto map–based IPsec configuration, then saves the running config — all without leaving the browser.

### Features

- Custom Nautobot form at `/plugins/tunnel-builder/`
- **Policy-based** IPsec using crypto maps and crypto ACLs
- **IKEv2** support: proposal → policy → keyring → profile → transform-set → crypto map
- **IKEv1** support: ISAKMP policy + pre-shared key → transform-set → crypto map
- Algorithm choices: AES-128/192/256, AES-GCM-128/256 (IKEv2), SHA-1/256/384/512, MD5, DH groups 2/5/14/19/20/21
- IKE version toggle with live show/hide of version-specific form sections
- Form-level validation including CIDR network parsing and GCM ↔ HMAC cross-field enforcement
- Nautobot Job (`BuildIpsecTunnel`) runnable from both the custom form and the Jobs UI
- SSH via [Netmiko](https://github.com/ktbyers/netmiko) — no RESTCONF or NETCONF required
- PSK redacted from all job logs
- Runs `copy running-config startup-config` automatically
- Navigation menu entry under **Network Tools → VPN**

## Requirements

- Nautobot >= 3.0.0+
- Python >= 3.10, < 3.13
- Netmiko >= 4.0

## Documentation

Full documentation for this App can be found in docs/.

### Contributing to the Documentation

You can find all the Markdown source for the App documentation under the [`docs`](https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder/tree/main/docs) folder in this repository. For simple edits, a Markdown capable editor is sufficient: clone the repository and edit away.

If you need to view the fully-generated documentation site, you can build it with [MkDocs](https://www.mkdocs.org/). A container hosting the documentation can be started using the `invoke` commands (details in the [Development Environment Guide](https://docs.nautobot.com/projects/custom-tunnel-builder/en/latest/dev/dev_environment/#docker-development-environment)) on [http://localhost:8001](http://localhost:8001). As your changes are saved, they will be automatically rebuilt and any pages currently being viewed will be reloaded in your browser.

## Questions

For any questions or comments, please check the [FAQ](https://docs.nautobot.com/projects/custom-tunnel-builder/en/latest/user/faq/) first. Feel free to also swing by the [Network to Code Slack](https://networktocode.slack.com/) (channel `#nautobot`), sign up [here](http://slack.networktocode.com/) if you don't have an account.

