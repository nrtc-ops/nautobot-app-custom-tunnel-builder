#!/usr/bin/env bash
# ---------------------------------------------------------------------------
# Manual end-to-end test for the portal tunnel API.
#
# Usage:
#   ./development/test-portal-api.sh
#
# Prerequisites:
#   1.  Dev stack + fake-cisco running:
#         invoke build --fake-cisco   # first time only
#         invoke start --fake-cisco
#   2.  A Nautobot API token.  Either:
#         - Create one in the UI at http://localhost:8080/user/api-tokens/
#         - Or export NAUTOBOT_TOKEN=<your-token>
#   4.  A hub device UUID and a template VPN profile UUID.
#       Copy them from the Nautobot UI and set the env vars below, or
#       override on the command line:
#         HUB_DEVICE_UUID=<uuid> TEMPLATE_PROFILE_UUID=<uuid> ./test-portal-api.sh
#
# What this script does:
#   Step 1 – POST a tunnel request → get back tunnel_id and status_url
#   Step 2 – GET the tunnel status URL until the job completes
#   Step 3 – Show the commands received by the fake-cisco device
# ---------------------------------------------------------------------------

set -euo pipefail

NAUTOBOT_URL="${NAUTOBOT_URL:-http://localhost:8080}"
NAUTOBOT_TOKEN="${NAUTOBOT_TOKEN:-}"
HUB_DEVICE_UUID="${HUB_DEVICE_UUID:-}"
TEMPLATE_PROFILE_UUID="${TEMPLATE_PROFILE_UUID:-}"

# ---- Validation ---------------------------------------------------------- #
if [[ -z "$NAUTOBOT_TOKEN" ]]; then
    echo "ERROR: Set NAUTOBOT_TOKEN to a valid Nautobot API token."
    echo "       Create one at ${NAUTOBOT_URL}/user/api-tokens/"
    exit 1
fi
_discover() {
    echo ""
    echo "  Eligible hub devices (platform must be cisco_ios or cisco_xe, device must have a primary IP):"
    python3 - <<'PYEOF'
import json, subprocess, sys, os
url = os.environ.get("NAUTOBOT_URL", "http://localhost:8080")
token = os.environ.get("NAUTOBOT_TOKEN", "")
for driver in ("cisco_xe", "cisco_ios"):
    r = subprocess.run(
        ["curl", "-s", "-H", f"Authorization: Token {token}",
         f"{url}/api/dcim/devices/?platform__network_driver={driver}&has_primary_ip=true&limit=10&depth=1"],
        capture_output=True, text=True)
    try:
        data = json.loads(r.stdout)
    except Exception:
        continue
    for d in data.get("results", []):
        ip = (d.get("primary_ip4") or {}).get("address", "NO-IP")
        plat = (d.get("platform") or {}).get("display", "?")
        print(f"  {d['id']}  {d['name']}  platform={plat}  primary_ip={ip}")
PYEOF
    echo ""
    echo "  If your device is not listed, open it in Nautobot and set:"
    echo "    Platform → (a platform with network_driver = cisco_ios or cisco_xe)"
    echo "    Primary IPv4 → the management IP"
    echo ""
    echo "  VPN profiles (template candidates):"
    curl -s -H "Authorization: Token ${NAUTOBOT_TOKEN}" \
         "${NAUTOBOT_URL}/api/vpn/vpn-profiles/?limit=10" \
         | python3 -c "
import json, sys
data = json.load(sys.stdin)
for p in data.get('results', []):
    print(f\"  {p['id']}  {p['name']}\")
"
}

if [[ -z "$HUB_DEVICE_UUID" || -z "$TEMPLATE_PROFILE_UUID" ]]; then
    echo "ERROR: Set HUB_DEVICE_UUID and TEMPLATE_PROFILE_UUID."
    _discover
    exit 1
fi

# Always verify the device passes the portal's queryset filter before posting
echo "Checking device eligibility..."
DEVICE_CHECK=$(curl -s -o /dev/null -w "%{http_code}" \
    -H "Authorization: Token ${NAUTOBOT_TOKEN}" \
    "${NAUTOBOT_URL}/api/dcim/devices/${HUB_DEVICE_UUID}/")
if [[ "$DEVICE_CHECK" == "404" ]]; then
    echo "ERROR: Device ${HUB_DEVICE_UUID} not found."
    _discover
    exit 1
fi
DEVICE_INFO=$(curl -s -H "Authorization: Token ${NAUTOBOT_TOKEN}" \
    "${NAUTOBOT_URL}/api/dcim/devices/${HUB_DEVICE_UUID}/?depth=1")
DEVICE_DRIVER=$(echo "$DEVICE_INFO" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); print((d.get('platform') or {}).get('network_driver','NONE'))" 2>/dev/null)
DEVICE_NAME=$(echo "$DEVICE_INFO" | python3 -c \
    "import json,sys; print(json.load(sys.stdin).get('name','?'))" 2>/dev/null)
DEVICE_IP=$(echo "$DEVICE_INFO" | python3 -c \
    "import json,sys; d=json.load(sys.stdin); ip=d.get('primary_ip4') or {}; print(ip.get('host') or ip.get('address','NONE'))" 2>/dev/null)

echo "  Name:           ${DEVICE_NAME}"
echo "  network_driver: ${DEVICE_DRIVER}"
echo "  primary_ip4:    ${DEVICE_IP}"
echo ""

if [[ "$DEVICE_DRIVER" != "cisco_ios" && "$DEVICE_DRIVER" != "cisco_xe" ]]; then
    echo "ERROR: Device platform network_driver is '${DEVICE_DRIVER}'."
    echo "       The portal only accepts devices with network_driver = cisco_ios or cisco_xe."
    echo "       Fix in Nautobot: Devices → ${DEVICE_NAME} → Edit → Platform"
    _discover
    exit 1
fi
if [[ "$DEVICE_IP" == "NONE" ]]; then
    echo "ERROR: Device has no primary IPv4 address. Set one in Nautobot before running."
    exit 1
fi

AUTH="Authorization: Token ${NAUTOBOT_TOKEN}"
PORTAL_URL="${NAUTOBOT_URL}/plugins/tunnel-builder/api/portal-request/"

echo "========================================================"
echo " Nautobot Portal Tunnel API — Manual End-to-End Test"
echo "========================================================"
echo ""
echo "Hub device:        ${HUB_DEVICE_UUID}"
echo "Template profile:  ${TEMPLATE_PROFILE_UUID}"
echo ""

# ---- Step 1: POST tunnel request ----------------------------------------- #
echo ">>> Step 1: POST ${PORTAL_URL}"
echo ""

RESPONSE=$(curl -s -w "\n%{http_code}" \
    -X POST "${PORTAL_URL}" \
    -H "${AUTH}" \
    -H "Content-Type: application/json" \
    -d "{
        \"member_name\": \"test-member\",
        \"member_display_name\": \"Test Member Corp\",
        \"location_city\": \"Jackson\",
        \"location_state\": \"MS\",
        \"device\": \"${HUB_DEVICE_UUID}\",
        \"template_vpn_profile\": \"${TEMPLATE_PROFILE_UUID}\",
        \"remote_peer_ip\": \"203.0.113.100\",
        \"hub_protected_prefix\": \"10.100.0.0/24\",
        \"member_protected_prefix\": \"192.168.200.0/24\"
    }")

HTTP_STATUS=$(echo "$RESPONSE" | tail -1)
BODY=$(echo "$RESPONSE" | sed '$d')

echo "HTTP ${HTTP_STATUS}"
echo "$BODY" | python3 -m json.tool 2>/dev/null || echo "$BODY"
echo ""

if [[ "$HTTP_STATUS" != "202" ]]; then
    echo "ERROR: Expected 202 Accepted, got ${HTTP_STATUS}."
    exit 1
fi

TUNNEL_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['tunnel_id'])")
JOB_ID=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['job_id'])")
STATUS_URL=$(echo "$BODY" | python3 -c "import json,sys; print(json.load(sys.stdin)['status_url'])")

echo "Tunnel ID:  ${TUNNEL_ID}"
echo "Job ID:     ${JOB_ID}"
echo "Status URL: ${STATUS_URL}"
echo ""

# ---- Step 2: Poll tunnel status ------------------------------------------ #
echo ">>> Step 2: Poll ${STATUS_URL}"
echo ""

MAX_WAIT=60
WAITED=0
TUNNEL_STATUS=""

while [[ $WAITED -lt $MAX_WAIT ]]; do
    STATUS_RESPONSE=$(curl -s -H "${AUTH}" "${STATUS_URL}")
    TUNNEL_STATUS=$(echo "$STATUS_RESPONSE" | python3 -c "import json,sys; print(json.load(sys.stdin).get('status','unknown'))" 2>/dev/null || echo "unknown")

    echo "  [${WAITED}s] Tunnel status: ${TUNNEL_STATUS}"

    if [[ "$TUNNEL_STATUS" == "Active" ]]; then
        break
    fi
    if [[ "$TUNNEL_STATUS" == "Decommissioning" ]]; then
        echo ""
        echo "ERROR: Job failed — tunnel set to Decommissioning."
        echo "Check worker logs: docker compose logs worker"
        exit 1
    fi

    sleep 3
    WAITED=$((WAITED + 3))
done

echo ""
if [[ "$TUNNEL_STATUS" != "Active" ]]; then
    echo "WARNING: Tunnel did not reach Active status within ${MAX_WAIT}s (still: ${TUNNEL_STATUS})."
    echo "Job may still be running.  Check: ${NAUTOBOT_URL}/extras/job-results/${JOB_ID}/"
fi

# ---- Step 3: Show device output ------------------------------------------ #
echo ">>> Step 3: Commands received by fake-cisco device"
echo ""

if docker ps --format '{{.Names}}' 2>/dev/null | grep -q "^fake-cisco$"; then
    echo "--- /output/commands.txt ---"
    docker exec fake-cisco cat /output/commands.txt 2>/dev/null || echo "(file empty or not found)"
    echo ""
    echo "--- docker logs (last 30 lines) ---"
    docker logs fake-cisco --tail 30 2>&1
else
    echo "(fake-cisco container not running — skipping device output check)"
    echo "Start it with the docker-compose.fake-cisco.yml overlay."
fi

echo ""
echo "========================================================"
echo " Done. Tunnel ID: ${TUNNEL_ID}"
echo " Job result: ${NAUTOBOT_URL}/extras/job-results/${JOB_ID}/"
echo "========================================================"
