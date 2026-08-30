#!/usr/bin/env bash
# Source bashrc to pick up OPENCODE_SERVER_PASSWORD, GEMINI_API_KEY, etc.
if [ -f ~/.bashrc ]; then
  source ~/.bashrc
fi

# Kill any existing opencode serve instance
pkill -f "opencode serve" 2>/dev/null || true

echo "Starting opencode serve..."
exec opencode serve --hostname 0.0.0.0 --port 4096
