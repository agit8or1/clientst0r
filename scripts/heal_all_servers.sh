#!/bin/bash
# Heal All Servers - Triggers emergency restart on multiple remote instances
# This script hits the emergency-restart webhook on all your servers

# INSTRUCTIONS:
# 1. Edit the SERVERS array below with your server URLs
# 2. Set EMERGENCY_RESTART_SECRET in each server's .env (the endpoint is
#    disabled without it) and export the same value here
# 3. Run: EMERGENCY_RESTART_SECRET=... ./scripts/heal_all_servers.sh

# Add your server URLs here
SERVERS=(
    "https://server1.example.com"
    "https://server2.example.com"
    "https://server3.example.com"
)

# Colors
GREEN='\033[0;32m'
RED='\033[0;31m'
YELLOW='\033[1;33m'
NC='\033[0m'

echo "=========================================="
echo "  Healing Multiple Servers"
echo "=========================================="
echo ""

SECRET="${EMERGENCY_RESTART_SECRET:-}"
if [ -z "$SECRET" ]; then
    echo -e "${RED}✗ Set EMERGENCY_RESTART_SECRET (the value in each server's .env)${NC}"
    exit 1
fi

# Function to heal a single server
heal_server() {
    local server_url=$1
    echo -e "${YELLOW}→${NC} Healing: $server_url"

    # First trigger update
    echo "  Step 1: Triggering update (pulls latest code)..."
    response=$(curl -s -X POST "$server_url/settings/updates/apply/" \
        -H "Content-Type: application/json" \
        --cookie-jar /tmp/cookies-$$.txt \
        --cookie /tmp/cookies-$$.txt \
        2>&1)

    sleep 5

    # Then trigger emergency restart
    echo "  Step 2: Triggering emergency restart..."
    response=$(curl -s -X POST "$server_url/emergency-restart/" \
        -H "X-Emergency-Secret: $SECRET" \
        2>&1)

    if echo "$response" | grep -q '"success": true'; then
        echo -e "  ${GREEN}✓ Success!${NC}"
        return 0
    else
        echo -e "  ${RED}✗ Failed${NC}"
        echo "  Response: $response"
        return 1
    fi
}

# Heal all servers
success_count=0
failed_count=0

for server in "${SERVERS[@]}"; do
    if heal_server "$server"; then
        ((success_count++))
    else
        ((failed_count++))
    fi
    echo ""
done

echo "=========================================="
echo "  Results"
echo "=========================================="
echo -e "${GREEN}✓ Successful: $success_count${NC}"
if [ $failed_count -gt 0 ]; then
    echo -e "${RED}✗ Failed: $failed_count${NC}"
fi
echo ""
echo "All servers should now be healed!"
echo "Check each server's System Updates page to verify."
