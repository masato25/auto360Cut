#!/bin/bash

# macOS double-click (Finder) installation script
# Ensures we're running from the project directory regardless of how we were launched

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$SCRIPT_DIR"

printf "\033[1;34m▶ auto360Cut Installer\033[0m\n"
printf "\033[1;34m━━━━━━━━━━━━━━━━━━━━━━━━━━\033[0m\n\n"

bash "$SCRIPT_DIR/scripts/install.sh" || true

echo ""
printf "\033[1;32mInstallation finished.\033[0m\n"
printf "Press Enter to close this window."
read -r
