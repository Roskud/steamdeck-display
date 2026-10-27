#!/bin/bash
# Install script for Steam Deck plugin
# Makes sure we are in the script directory
DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
cd "$DIR"

echo "Installing DeckDisplay plugin..."
bash ./deploy-plugin.sh
