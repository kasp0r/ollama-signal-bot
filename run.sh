#!/bin/bash
# Signal Bot for Ollama - Run Script

set -e

BLUE='\033[0;34m'
YELLOW='\033[1;33m'
GREEN='\033[0;32m'
RED='\033[0;31m'
CYAN='\033[0;36m'
NC='\033[0m' # No Color

echo -e "${BLUE}===== Signal Bot for Ollama =====${NC}"
echo ""

# Build
echo -e "${YELLOW}Building...${NC}"
docker-compose build --no-cache

# Start Signal API first
echo -e "${YELLOW}Starting Signal API...${NC}"
docker-compose up -d signal-api
sleep 5

# Wait for API to be ready
echo -e "${YELLOW}Waiting for Signal API...${NC}"
ready=false
for i in $(seq 1 30); do
    if curl -sf --max-time 3 http://localhost:18080/v1/about > /dev/null 2>&1; then
        ready=true
        break
    fi
    sleep 2
done

if [ "$ready" = false ]; then
    echo -e "${RED}ERROR: Signal API not ready${NC}"
    exit 1
fi
echo -e "${GREEN}Signal API is ready!${NC}"

# Check if account is linked
needs_setup=true
accounts=$(curl -sf --max-time 5 http://localhost:18080/v1/accounts 2>/dev/null || echo "[]")
if [ "$accounts" != "[]" ] && [ -n "$accounts" ]; then
    echo -e "${GREEN}Account already linked: ${accounts}${NC}"
    needs_setup=false
fi

# Run setup if needed
if [ "$needs_setup" = true ]; then
    echo ""
    echo -e "${YELLOW}No Signal account linked. Running setup...${NC}"
    echo ""
    python3 signal-setup.py
fi

# Start the bot
echo ""
echo -e "${YELLOW}Starting bot...${NC}"
docker-compose up -d
echo ""
echo -e "${GREEN}Bot is running!${NC}"
echo -e "${CYAN}View logs: docker-compose logs -f ollama-signal-bot${NC}"
echo ""
docker-compose logs -f ollama-signal-bot