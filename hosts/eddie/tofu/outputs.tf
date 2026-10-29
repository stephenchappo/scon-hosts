output "droplet_id" {
  value = digitalocean_droplet.node.id
}

output "public_ipv4" {
  description = "For the record only. Nothing listens on it except Tailscale's UDP port."
  value       = digitalocean_droplet.node.ipv4_address
}

output "tailnet_name" {
  value = "${var.hostname}.batfish-pride.ts.net"
}
