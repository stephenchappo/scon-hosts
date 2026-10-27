# Secrets this host needs, and where they live
#
# VALUES ARE NEVER RECORDED HERE. This file is pushed to GitHub.
# It exists so a rebuild knows what to retrieve from escrow
# ([[Break Glass - Digital Life Recovery]], plan §6).

## Layer A — unrecoverable if lost
- ~/.age/key.txt                                 decrypts _project-meta/secrets/*.age
- n8n N8N_ENCRYPTION_KEY                         captured inside the nightly n8n backup tarball

## Layer B — reissuable from account access
- ~/.ssh/id_ed25519                              machine -> GitHub; regenerate on rebuild, do not hunt for it
- ~/.claude/.credentials.json                    re-auth via claude login

## Service .env files — present on disk, gitignored by design
- /srv/docker/deepthought/agentic-pipeline/.env  18 keys
- /srv/docker/deepthought/.env                   2 keys
- /srv/docker/deepthought/homelab-notify/.env    1 keys
- /srv/docker/deepthought/n8n/.env               5 keys
- /srv/docker/deepthought/snapcast/.env          2 keys
- /etc/photo-ingest.env                          keys listed in etc/photo-ingest.env.KEYS-ONLY

## Absent on this host (noted so its absence is not mistaken for loss)
- ~/.config/gocryptfs/personal-vault.pass        provisioned manually; personal vault not mounted here
