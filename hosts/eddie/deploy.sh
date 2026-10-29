#!/usr/bin/env bash
# Copy hosts/eddie to eddie:~/eddie over Tailscale SSH and run install.sh there.
# Run from Trillian or Anjie: ./deploy.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
tar -C "$HERE" --exclude=tofu -czf - . | tailscale ssh scon@eddie 'mkdir -p ~/eddie && tar -C ~/eddie -xzf -'
tailscale ssh scon@eddie 'bash ~/eddie/install.sh'
