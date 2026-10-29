terraform {
  required_version = ">= 1.8"
  required_providers {
    digitalocean = {
      source  = "digitalocean/digitalocean"
      version = "~> 2.0"
    }
  }
  # Local state on purpose: it holds the droplet id and the (single-use, expired)
  # Tailscale key. Keep it on Trillian or Anjie, never in git (see .gitignore).
}

provider "digitalocean" {
  # Reads DIGITALOCEAN_TOKEN from the environment (the scoped "scon-cloud" token).
}
