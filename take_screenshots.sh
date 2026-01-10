#!/bin/bash
#
# HuduGlue Screenshot Generation Workflow
#
# This script automates the entire screenshot process:
# 1. Creates test data
# 2. Starts the development server
# 3. Generates screenshots
# 4. Launches interactive selector
#

set -e

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

# Colors for output
GREEN='\033[0;32m'
BLUE='\033[0;34m'
YELLOW='\033[1;33m'
RED='\033[0;31m'
NC='\033[0m' # No Color

# Configuration
SERVER_PORT=8000
SERVER_URL="http://localhost:$SERVER_PORT"
SCREENSHOT_DIR="screenshots"
SERVER_PID_FILE="/tmp/huduglue_screenshot_server.pid"

echo -e "${BLUE}================================================${NC}"
echo -e "${BLUE}  HuduGlue Screenshot Generation Workflow${NC}"
echo -e "${BLUE}================================================${NC}\n"

# Function to check if server is running
server_running() {
    if [ -f "$SERVER_PID_FILE" ]; then
        pid=$(cat "$SERVER_PID_FILE")
        if ps -p "$pid" > /dev/null 2>&1; then
            return 0
        fi
    fi
    return 1
}

# Function to start server
start_server() {
    echo -e "${YELLOW}🚀 Starting development server...${NC}"

    # Activate virtual environment
    source venv/bin/activate

    # Start server in background
    python manage.py runserver "$SERVER_PORT" > /tmp/huduglue_server.log 2>&1 &
    SERVER_PID=$!

    # Save PID
    echo "$SERVER_PID" > "$SERVER_PID_FILE"

    # Wait for server to be ready
    echo -e "${YELLOW}⏳ Waiting for server to be ready...${NC}"
    for i in {1..30}; do
        if curl -s "$SERVER_URL" > /dev/null 2>&1; then
            echo -e "${GREEN}✅ Server is ready!${NC}\n"
            return 0
        fi
        sleep 1
    done

    echo -e "${RED}❌ Server failed to start${NC}"
    return 1
}

# Function to stop server
stop_server() {
    if server_running; then
        pid=$(cat "$SERVER_PID_FILE")
        echo -e "${YELLOW}🛑 Stopping development server (PID: $pid)...${NC}"
        kill "$pid" 2>/dev/null || true
        rm -f "$SERVER_PID_FILE"
        echo -e "${GREEN}✅ Server stopped${NC}"
    fi
}

# Cleanup function
cleanup() {
    stop_server
}

# Register cleanup function
trap cleanup EXIT INT TERM

# Step 1: Create test data
echo -e "${BLUE}📝 Step 1: Creating test data${NC}"
source venv/bin/activate
python manage.py create_test_data

# Step 2: Start server if not running
if ! server_running; then
    start_server
else
    echo -e "${GREEN}✅ Server already running${NC}\n"
fi

# Step 3: Generate screenshots
echo -e "${BLUE}📸 Step 2: Generating screenshots${NC}"
python scripts/generate_screenshots.py --url "$SERVER_URL" --output "$SCREENSHOT_DIR"

# Step 4: Interactive selection
echo -e "\n${BLUE}🖱️  Step 3: Interactive Screenshot Selection${NC}"
echo -e "${YELLOW}You can now review and select screenshots for GitHub${NC}\n"

read -p "Launch interactive selector? (y/n): " -n 1 -r
echo
if [[ $REPLY =~ ^[Yy]$ ]]; then
    python scripts/screenshot_selector.py --dir "$SCREENSHOT_DIR"
else
    echo -e "${YELLOW}Skipping interactive selection${NC}"
    echo -e "${YELLOW}You can run it later with: python scripts/screenshot_selector.py${NC}"
fi

# Summary
echo -e "\n${BLUE}================================================${NC}"
echo -e "${GREEN}✅ Screenshot workflow complete!${NC}"
echo -e "${BLUE}================================================${NC}\n"

echo -e "${YELLOW}Next steps:${NC}"
echo -e "  1. Review screenshots in: ${BLUE}$SCREENSHOT_DIR/${NC}"
echo -e "  2. Select screenshots: ${BLUE}python scripts/screenshot_selector.py${NC}"
echo -e "  3. Export selected to: ${BLUE}screenshots_selected/${NC}"
echo -e "  4. Add to GitHub: ${BLUE}git add screenshots_selected/ && git commit${NC}\n"

# Ask if user wants to keep server running
read -p "Keep development server running? (y/n): " -n 1 -r
echo
if [[ ! $REPLY =~ ^[Yy]$ ]]; then
    stop_server
else
    echo -e "${GREEN}✅ Server will continue running at $SERVER_URL${NC}"
    echo -e "${YELLOW}To stop it later, run: kill $(cat $SERVER_PID_FILE)${NC}"
    # Don't run cleanup
    trap - EXIT INT TERM
fi
