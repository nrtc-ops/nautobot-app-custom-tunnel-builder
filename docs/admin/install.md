# Installing the App in Nautobot

!!! warning "Alpha Software"
    This app is in **alpha** status. APIs, configuration options, and behaviors may change between releases without notice. Use in production at your own risk.

Here you will find detailed instructions on how to **install** and **configure** the App within your Nautobot environment.

## Prerequisites

- The app is compatible with Nautobot 3.0.0 and higher.
- Databases supported: PostgreSQL

!!! note
    Please check the [dedicated page](compatibility_matrix.md) for a full compatibility matrix and the deprecation policy.

| Requirement | Version |
| ----------- | ------- |
| Python      | 3.11+   |
| Nautobot    | 3.0.0+  |
| Netmiko     | 4.0.0+  |

Nautobot must already be installed and operational before installing this app.

## Install Guide

!!! note
    Apps can be installed from the [Python Package Index](https://pypi.org/) or locally. See the [Nautobot documentation](https://docs.nautobot.com/projects/core/en/stable/user-guide/administration/installation/app-install/) for more details. The pip package name for this app is [`nautobot-custom-tunnel-builder`](https://pypi.org/project/nautobot-custom-tunnel-builder/).

The app is available as a Python package via PyPI and can be installed with `pip`:

```shell
pip install nautobot-custom-tunnel-builder
```

To ensure Custom Tunnel Builder is automatically re-installed during future upgrades, create a file named `local_requirements.txt` (if not already existing) in the Nautobot root directory (alongside `requirements.txt`) and list the `nautobot-custom-tunnel-builder` package:

```shell
echo nautobot-custom-tunnel-builder >> local_requirements.txt
```

Once installed, the app needs to be enabled in your Nautobot configuration. The following block of code below shows the additional configuration required to be added to your `nautobot_config.py` file:

- Append `"nautobot_custom_tunnel_builder"` to the `PLUGINS` list.
- Append the `"nautobot_custom_tunnel_builder"` dictionary to the `PLUGINS_CONFIG` dictionary and override any defaults.

```python
# In your nautobot_config.py
PLUGINS = ["nautobot_custom_tunnel_builder"]

PLUGINS_CONFIG = {
    "nautobot_custom_tunnel_builder": {
        "device_ssh_port": 22,
        "connection_timeout": 30,
    }
}
```

Once the Nautobot configuration is updated, run the Post Upgrade command (`nautobot-server post_upgrade`) to run migrations and clear any cache:

```shell
nautobot-server post_upgrade
```

Then restart (if necessary) the Nautobot services which may include:

- Nautobot
- Nautobot Workers
- Nautobot Scheduler

```shell
sudo systemctl restart nautobot nautobot-worker nautobot-scheduler
```

## App Configuration

The app behavior can be controlled with the following list of settings:

| Key | Default | Description |
| --- | ------- | ----------- |
| `device_ssh_port` | `22` | Default SSH port used to connect to devices. Can be overridden per-job via the `NAUTOBOT_DEVICE_SSH_PORT` environment variable. |
| `connection_timeout` | `30` | Netmiko connection timeout in seconds. |

## Environment Variables

Device credentials are **never stored in Nautobot**. They are read from the environment at job execution time.

| Variable                        | Required | Default   | Description                                                      |
| ------------------------------- | -------- | --------- | ---------------------------------------------------------------- |
| `NAUTOBOT_DEVICE_USERNAME`      | Yes      | `admin`   | SSH username for device login.                                   |
| `NAUTOBOT_DEVICE_PASSWORD`      | Yes      | _(empty)_ | SSH password for device login.                                   |
| `NAUTOBOT_DEVICE_ENABLE_SECRET` | No       | _(empty)_ | Enable-mode secret. Required if the device prompts for `enable`. |
| `NAUTOBOT_DEVICE_SSH_PORT`      | No       | `22`      | SSH port. Useful for non-standard port environments.             |

### Setting variables in systemd

```ini
# /etc/systemd/system/nautobot-worker.service
[Service]
Environment="NAUTOBOT_DEVICE_USERNAME=netauto"
Environment="NAUTOBOT_DEVICE_PASSWORD=s3cr3t"
Environment="NAUTOBOT_DEVICE_ENABLE_SECRET=en4bl3"
```

### Setting variables in Docker Compose

```yaml
# docker-compose.yml
services:
  nautobot-worker:
    env_file:
      - .env.devices
```

```bash
# .env.devices
NAUTOBOT_DEVICE_USERNAME=netauto
NAUTOBOT_DEVICE_PASSWORD=s3cr3t
NAUTOBOT_DEVICE_ENABLE_SECRET=en4bl3
```

### Setting variables in Kubernetes

```yaml
apiVersion: v1
kind: Secret
metadata:
  name: nautobot-device-creds
stringData:
  NAUTOBOT_DEVICE_USERNAME: netauto
  NAUTOBOT_DEVICE_PASSWORD: s3cr3t
```

```yaml
# In the worker Deployment
envFrom:
  - secretRef:
      name: nautobot-device-creds
```

## Nautobot Permissions

The view and job both require the `extras.run_job` permission. Assign this to any user or group that should be allowed to build tunnels:

1. Navigate to **Admin > Users** (or **Groups**).
2. Open the user or group.
3. Under **Permissions**, ensure `extras | job | Can run job` is checked.

The navigation menu item is also hidden from users without this permission.

## Verify the Installation

1. Log in to Nautobot.
2. Navigate to **Network Tools > VPN > Build IPsec Tunnel** in the navigation bar.
3. You should see the IPsec Tunnel Builder form.
4. Go to **Jobs** > search for `BuildIpsecTunnel` — it should appear in the list.

### Prepare Devices in Nautobot

For a device to appear in the form's device selector it must have:

1. **Platform** configured with `network_driver` set to `cisco_ios` or `cisco_xe`.
2. **Primary IPv4 address** assigned.
