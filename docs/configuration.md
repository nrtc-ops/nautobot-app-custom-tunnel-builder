# Configuration

## App Settings (`PLUGINS_CONFIG`)

The following settings can be overridden in `nautobot_config.py` under `PLUGINS_CONFIG`:

```python
PLUGINS_CONFIG = {
    "nautobot_app_custom_tunnel_builder": {
        "device_ssh_port": 22,
        "connection_timeout": 30,
    }
}
```

| Setting              | Type  | Default | Description                                                                                                                     |
| -------------------- | ----- | ------- | ------------------------------------------------------------------------------------------------------------------------------- |
| `device_ssh_port`    | `int` | `22`    | Default SSH port used to connect to devices. Can be overridden per-job via the `NAUTOBOT_DEVICE_SSH_PORT` environment variable. |
| `connection_timeout` | `int` | `30`    | Netmiko connection timeout in seconds.                                                                                          |

---

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

---

## Nautobot SecretsGroup Integration (Recommended for Production)

For production environments, replace environment variable credential lookup in `jobs.py` with Nautobot's built-in **SecretsGroup** feature. This keeps credentials managed centrally within Nautobot and supports backends like HashiCorp Vault.

Modify the `_get_credentials()` section of `jobs.py`:

```python
from nautobot.extras.models import SecretsGroup

secrets_group = SecretsGroup.objects.get(name="device-ssh-creds")
username = secrets_group.get_secret_value(
    access_type=SecretsGroupAccessTypeChoices.TYPE_GENERIC,
    secret_type=SecretsGroupSecretTypeChoices.TYPE_USERNAME,
)
password = secrets_group.get_secret_value(
    access_type=SecretsGroupAccessTypeChoices.TYPE_GENERIC,
    secret_type=SecretsGroupSecretTypeChoices.TYPE_PASSWORD,
)
```

> Nautobot SecretsGroups can be associated with individual Device records for per-device credential management.

---

## Nautobot Permissions

The view and job both require the `extras.run_job` permission. Assign this to any user or group that should be allowed to build tunnels:

1. Navigate to **Admin → Users** (or **Groups**).
2. Open the user or group.
3. Under **Permissions**, ensure `extras | job | Can run job` is checked.

The navigation menu item is also hidden from users without this permission.
