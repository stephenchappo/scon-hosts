variable "hostname" {
  description = "Node name on the tailnet and in DigitalOcean."
  type        = string
  default     = "eddie"
}

variable "region" {
  description = "DigitalOcean region. sfo3 = San Francisco."
  type        = string
  default     = "sfo3"
}

variable "size" {
  description = "Droplet size. s-2vcpu-4gb = Basic, 2 vCPU, 4 GB, 80 GB, $24/mo."
  type        = string
  default     = "s-2vcpu-4gb"
}

variable "image" {
  type    = string
  default = "ubuntu-24-04-x64"
}

variable "tailscale_auth_key" {
  description = "Single-use, pre-approved auth key tagged tag:cloud, expiring in 1 hour. Made fresh for each apply."
  type        = string
  sensitive   = true
}
