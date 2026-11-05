#!/usr/bin/env bash
# Copy hosts/eddie to eddie:~/eddie over Tailscale SSH and run install.sh there.
# Run from Trillian or Anjie: ./deploy.sh
set -euo pipefail
HERE=$(cd "$(dirname "$0")" && pwd)
WORK=${WORK:-$(cd "$HERE/../../.." && pwd)}      # ~/work: scon-fetch and scon-system sit next to scon-hosts
tar -C "$HERE" --exclude=tofu -czf - . | tailscale ssh scon@eddie 'mkdir -p ~/eddie && tar -C ~/eddie -xzf -'
# The browser's proxy needs scon-fetch and the site book (public records only: no Restricted book on eddie).
test -f "$WORK/scon-system/sources/index.json" && test -f "$WORK/scon-fetch/bin/scon-fetch"
tar -C "$WORK" --exclude='__pycache__' --exclude=tests -czf - scon-fetch/bin scon-fetch/scon_fetch scon-system/sources/index.json |
  tailscale ssh scon@eddie 'rm -rf ~/eddie/vendor && mkdir -p ~/eddie/vendor/stage && tar -C ~/eddie/vendor/stage -xzf - &&
    mv ~/eddie/vendor/stage/scon-fetch ~/eddie/vendor/scon-fetch && mkdir -p ~/eddie/vendor/sources &&
    mv ~/eddie/vendor/stage/scon-system/sources/index.json ~/eddie/vendor/sources/ && rm -rf ~/eddie/vendor/stage'
tailscale ssh scon@eddie 'bash ~/eddie/install.sh'
