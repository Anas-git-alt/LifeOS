#!/bin/bash
# LifeOS Health Check — sends Discord webhook alert on failure
set -e

BACKEND_URL="${BACKEND_URL:-http://localhost:8000}"
DISCORD_WEBHOOK="${DISCORD_WEBHOOK_URL:-}"

check_health() {
    HTTP_CODE=$(curl -s -o /dev/null -w "%{http_code}" "$BACKEND_URL/api/health" 2>/dev/null || echo "000")
    if [ "$HTTP_CODE" = "200" ]; then
        echo "✅ Backend healthy"
        return 0
    else
        echo "❌ Backend unhealthy (HTTP $HTTP_CODE)"
        return 1
    fi
}

send_discord_alert() {
    if [ -n "$DISCORD_WEBHOOK" ]; then
        curl -s -H "Content-Type: application/json" \
            -d "{\"content\":\"🚨 **LifeOS Alert**: Backend health check failed! HTTP code: $1. Check \`docker compose logs backend\`.\"}" \
            "$DISCORD_WEBHOOK" > /dev/null
        echo "📨 Alert sent to Discord"
    fi
}

if ! check_health; then
    send_discord_alert "$HTTP_CODE"
    exit 1
fi
