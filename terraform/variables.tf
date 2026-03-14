variable "hcloud_token" {
  description = "Hetzner Cloud API token (Read & Write)"
  type        = string
  sensitive   = true
}

variable "cloudflare_api_token" {
  description = "Cloudflare API token with Edit zone DNS permission"
  type        = string
  sensitive   = true
}

variable "cloudflare_zone_id" {
  description = "Cloudflare Zone ID for langrag.ai"
  type        = string
}

variable "ssh_public_key_path" {
  description = "Path to SSH public key for server access"
  type        = string
  default     = "~/.ssh/id_ed25519.pub"
}

variable "server_type" {
  description = "Hetzner server type (cx22 = 2 vCPU, 4GB RAM, ~$5/mo)"
  type        = string
  default     = "cx23"
}

variable "server_location" {
  description = "Hetzner datacenter location"
  type        = string
  default     = "nbg1" # Nuremberg, Germany
}
