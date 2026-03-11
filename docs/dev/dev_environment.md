# Development Environment

## Project Structure

```
nautobot-app-custom-tunnel-builder/
├── pyproject.toml                              # Package metadata and build config (Poetry)
├── poetry.lock                                 # Locked dependencies
├── tasks.py                                    # Invoke tasks for development workflow
├── mkdocs.yml                                  # Documentation configuration
├── development/                                # Docker Compose dev environment
│   ├── Dockerfile
│   ├── docker-compose.base.yml
│   ├── docker-compose.dev.yml
│   ├── docker-compose.postgres.yml
│   ├── docker-compose.redis.yml
│   ├── nautobot_config.py
│   ├── creds.env / creds.example.env
│   └── development.env
├── docs/                                       # Documentation (mkdocs)
│   ├── admin/
│   ├── user/
│   └── dev/
└── nautobot_custom_tunnel_builder/             # Python package
    ├── __init__.py                             # NautobotAppConfig
    ├── forms.py                                # Django form
    ├── jobs.py                                 # Nautobot Job + config builder
    ├── navigation.py                           # Nav menu items
    ├── urls.py                                 # URL routing
    ├── views.py                                # Custom CBV
    └── templates/
        └── nautobot_custom_tunnel_builder/
            └── ipsec_tunnel_form.html          # Bootstrap 5 form template
```

---

## Docker Development Environment

The development environment uses Docker Compose with invoke tasks.

### Prerequisites

- Docker and Docker Compose
- Poetry (`pip install poetry`)
- Python 3.11+

### Getting Started

```bash
# Clone the repo
git clone https://github.com/nrtc-ops/nautobot-app-custom-tunnel-builder.git
cd nautobot-app-custom-tunnel-builder

# Install Python dependencies
poetry install

# Build and start the Docker environment
poetry run invoke build
poetry run invoke start

# Create a superuser
poetry run invoke createsuperuser
```

Nautobot will be available at [http://localhost:8080](http://localhost:8080).

### Common Invoke Commands

```bash
# Build Docker images
invoke build

# Start services in detached mode
invoke start

# Stop services
invoke stop

# Destroy containers and volumes
invoke destroy

# View logs
invoke logs --follow

# Run all tests
invoke tests

# Run unit tests only
invoke unittest

# Run linters
invoke ruff
invoke pylint
invoke yamllint

# Format code
invoke autoformat

# Launch a bash shell in the container
invoke cli

# Launch Nautobot shell
invoke nbshell
```

---

## Local Development (without Docker)

### 1. Create a virtual environment

```bash
python3.11 -m venv .venv
source .venv/bin/activate
```

### 2. Install with Poetry

```bash
poetry install
```

### 3. Point at an existing Nautobot instance

Set `NAUTOBOT_CONFIG` to your config file, then run the Nautobot development server:

```bash
export NAUTOBOT_CONFIG=/opt/nautobot/nautobot_config.py
nautobot-server runserver
```

Make sure the app is listed in `PLUGINS` in that config file.

---

## Code Style

```bash
# Format
poetry run ruff format nautobot_custom_tunnel_builder/

# Lint
poetry run ruff check nautobot_custom_tunnel_builder/
```

Max line length is 120 characters.
