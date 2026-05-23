#!/bin/bash
set -e

echo "Starting Tailscale daemon..."
tailscaled --state=/var/lib/tailscale/tailscaled.state --socket=/var/run/tailscale/tailscaled.sock &
sleep 2

echo "Authenticating Tailscale..."
tailscale up --authkey="${TAILSCALE_AUTHKEY}" --hostname=cdp-harness-railway

echo "Tailscale status:"
tailscale status

echo "Testing CDP connection to ${CDP_HOST:-100.113.104.72}:${CDP_PORT:-19222}..."
curl -s --connect-timeout 5 "http://${CDP_HOST:-100.113.104.72}:${CDP_PORT:-19222}/json/version" || echo "Warning: CDP not reachable yet (will retry at runtime)"

echo "Starting web server on port ${PORT:-8080}..."
exec python app.py

