# Installation

## Prerequisites

| Requirement | Version |
| ----------- | ------- |
| Python      | 3.11+   |
| Nautobot    | 3.0.0+  |
| Netmiko     | 4.0.0+  |

Nautobot must already be installed and operational before installing this app.

---

## 1. Install the Package

### From source (development)

```bash
git clone https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder.git
cd nautobot-app-custom-tunnel-builder
pip install -e .
```

### From a wheel/tarball (production)

```bash
pip install nautobot-custom-tunnel-builder-0.1.0-py3-none-any.whl
```

---

## 2. Register the App in Nautobot

Add the app to `PLUGINS` in your `nautobot_config.py`:

```python
PLUGINS = [
    "nautobot_custom_tunnel_builder",
]
```

Optional — override default settings (see [Configuration](configuration.md)):

```python
PLUGINS_CONFIG = {
    "nautobot_custom_tunnel_builder": {
        "device_ssh_port": 22,
        "connection_timeout": 30,
    }
}
```

---

## 3. Run Database Migrations

Nautobot needs to register the Job in its database. Run:

```bash
nautobot-server migrate
```

---

## 4. Collect Static Files

```bash
nautobot-server collectstatic --no-input
```

---

## 5. Set Device Credentials

The Job reads SSH credentials from **environment variables** at runtime. Set them in your Nautobot service environment (systemd unit, Docker `env_file`, Kubernetes Secret, etc.):

```bash
# Required
NAUTOBOT_DEVICE_USERNAME=admin
NAUTOBOT_DEVICE_PASSWORD=your-device-password

# Optional
NAUTOBOT_DEVICE_ENABLE_SECRET=your-enable-secret   # only if 'enable' is required
NAUTOBOT_DEVICE_SSH_PORT=22                        # default: 22
```

> **Security note:** Never hard-code credentials in source files. Use a secrets manager (HashiCorp Vault, Nautobot SecretsGroup, Kubernetes Secrets) to inject these variables into the process environment.

---

## 6. Restart Nautobot Services

```bash
sudo systemctl restart nautobot nautobot-worker
```

Or, with Docker Compose:

```bash
docker compose restart nautobot nautobot-worker
```

---

## 7. Verify the Installation

1. Log in to Nautobot.
2. Navigate to **Network Tools → VPN → Build IPsec Tunnel** in the navigation bar.
3. You should see the IPsec Tunnel Builder form.
4. Go to **Jobs** → search for `BuildIpsecTunnel` — it should appear in the list.

---

## Prepare Devices in Nautobot

For a device to appear in the form's device selector it must have:

1. **Platform** configured with `network_driver` set to `cisco_ios` or `cisco_xe`.

   Navigate to: **Devices → Platforms → (your platform) → Network Driver**

2. **Primary IPv4 address** assigned.

   Navigate to: **Devices → (your device) → Primary IP**

The Nautobot worker process (`nautobot-worker`) must be running to execute jobs asynchronously. Confirm with:

```bash
nautobot-server celery inspect active
```
