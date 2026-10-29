resource "digitalocean_tag" "cloud" {
  name = "scon-cloud"
}

resource "digitalocean_droplet" "node" {
  name       = var.hostname
  region     = var.region
  size       = var.size
  image      = var.image
  ipv6       = true
  monitoring = true
  backups    = true # weekly, +20% ($4.80/mo on s-2vcpu-4gb)
  backup_policy {
    plan    = "weekly"
    weekday = "SUN"
    hour    = 12 # UTC, 04:00/05:00 Pacific
  }
  tags = [digitalocean_tag.cloud.id]

  user_data = templatefile("${path.module}/../cloud-init.yaml", {
    hostname           = var.hostname
    tailscale_auth_key = var.tailscale_auth_key
  })

  lifecycle {
    # A new key every apply must not rebuild the node; cloud-init only runs once.
    ignore_changes = [user_data]
  }
}

# Nothing comes in from the internet except Tailscale's direct-connection port.
# No SSH: admin is Tailscale SSH only. Break glass: the DigitalOcean web console.
resource "digitalocean_firewall" "node" {
  name        = "${var.hostname}-tailnet-only"
  droplet_ids = [digitalocean_droplet.node.id]

  inbound_rule {
    protocol         = "udp"
    port_range       = "41641"
    source_addresses = ["0.0.0.0/0", "::/0"]
  }

  outbound_rule {
    protocol              = "tcp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "udp"
    port_range            = "1-65535"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
  outbound_rule {
    protocol              = "icmp"
    destination_addresses = ["0.0.0.0/0", "::/0"]
  }
}
