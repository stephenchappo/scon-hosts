# tailscale-resolv-guard

Keeps Trillian's DNS working after a power loss.

## The failure (2026-10-22)

- Trillian uses Tailscale DNS in **direct** mode. Pi-hole owns `:53`, so
  `systemd-resolved` runs with `DNSStubListener=no` and tailscaled detects
  `rc=resolved resolved=not-in-use` -> direct.
- Direct mode overwrites `/etc/resolv.conf` with a Tailscale-generated file
  (`nameserver 100.100.100.100`) and restores the original
  (`-> ../run/systemd/resolve/stub-resolv.conf`) when tailscaled stops cleanly.
- After a **power loss** the restore never runs. On the next boot tailscaled reads
  its own leftover file, takes the `resolvconf` in its header URL to mean
  openresolv (`/usr/sbin/resolvconf` exists as systemd's resolvectl shim), fails to
  set DNS (`error setting DNS config ... exit status 1`), and runs with **no upstream
  resolvers**. Every non-tailnet lookup returns SERVFAIL, and `cloudflared`
  crash-loops.
- Signature: `journalctl -u tailscaled -b | grep "dns: using"` shows `openresolv`.

## The fix

An `ExecStartPre` drop-in on `tailscaled.service` runs `tailscale-resolv-guard`.
If `/etc/resolv.conf` is still a Tailscale-generated regular file, the guard puts
back the stub symlink before tailscaled starts. That is the same state a clean
stop leaves behind. Each restore is logged under the `tailscale-resolv-guard` tag
(`journalctl -t tailscale-resolv-guard`).

    bash ~/system/tailscale-resolv-guard/install.sh     # install / update
    bash ~/system/tailscale-resolv-guard/uninstall.sh   # remove

Installed copies: `/usr/local/sbin/tailscale-resolv-guard` and
`/etc/systemd/system/tailscaled.service.d/resolv-guard.conf`.
