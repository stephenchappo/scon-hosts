# docker-user-blocklist

Keeps Trillian's container-traffic blocks in place after a reboot.

## Why

After the 2026-10-17 Plex incident, `217.60.194.116` and `45.194.92.222` were
dropped in ufw and in Docker's `DOCKER-USER` chain. ufw rules persist, but the
`DOCKER-USER` rules were added by hand and vanished on every reboot. ufw doesn't
cover container traffic, because Docker's published ports go through FORWARD.

## The fix

`docker-user-blocklist.service` is a oneshot tied to `docker.service`
(`WantedBy` + `PartOf`), so it runs whenever Docker starts. It inserts
`DROP` rules for each address in `/etc/docker-user-blocklist`, as source and as
destination, skipping any rule already there. Each addition is logged under the
`docker-user-blocklist` tag (`journalctl -t docker-user-blocklist`).

    sh ~/system/docker-user-blocklist/install.sh     # install / update
    sh ~/system/docker-user-blocklist/uninstall.sh   # remove

To block another address, add a line to `blocklist` and re-run `install.sh`.
Removing a line doesn't remove its live rule; do that with
`sudo iptables -D DOCKER-USER -s <ip> -j DROP` (and `-d`), or reboot.

Installed copies: `/usr/local/sbin/docker-user-blocklist`,
`/etc/docker-user-blocklist` and
`/etc/systemd/system/docker-user-blocklist.service`.
