ARG NAUTOBOT_VER="3.0.0"
ARG PYTHON_VER="3.12"
FROM ghcr.io/nautobot/nautobot-dev:${NAUTOBOT_VER}-py${PYTHON_VER}

ENV NAUTOBOT_ROOT=/opt/nautobot
ENV prometheus_multiproc_dir=/prom_cache
ENV PROMETHEUS_MULTIPROC_DIR=/prom_cache

# -----------------------------------------------
# SAFE-TO-MODIFY SECTION: App-specific system deps
# -----------------------------------------------
# Install system packages if needed (e.g., for LDAP)
# Example: RUN apt-get update && apt-get install -y libldap2-dev libsasl2-dev
# -----------------------------------------------

WORKDIR /source

# Install Poetry if not already installed
RUN which poetry || curl -sSL https://install.python-poetry.org | python3 -

# Copy only dependency files first (for Docker layer caching)
COPY pyproject.toml poetry.lock /source/

# Copy the rest of the source code
COPY . /source

# Install the project itself
RUN poetry install --no-interaction --no-ansi

COPY development/nautobot_config.py ${NAUTOBOT_ROOT}/nautobot_config.py
