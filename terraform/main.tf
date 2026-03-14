terraform {
  required_version = ">= 1.0"

  required_providers {
    hcloud = {
      source  = "hetznercloud/hcloud"
      version = "~> 1.45"
    }
    cloudflare = {
      source  = "cloudflare/cloudflare"
      version = "~> 4.0"
    }
  }
}

# --- Providers ---

provider "hcloud" {
  token = var.hcloud_token
}

provider "cloudflare" {
  api_token = var.cloudflare_api_token
}

# --- SSH Key ---

resource "hcloud_ssh_key" "default" {
  name       = "langrag-deploy-key"
  public_key = file(var.ssh_public_key_path)
}

# --- Firewall ---

resource "hcloud_firewall" "langrag" {
  name = "langrag-firewall"

  # SSH
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "22"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTP (Cloudflare proxy → server)
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "80"
    source_ips = ["0.0.0.0/0", "::/0"]
  }

  # HTTPS (Cloudflare proxy → server)
  rule {
    direction = "in"
    protocol  = "tcp"
    port      = "443"
    source_ips = ["0.0.0.0/0", "::/0"]
  }
}

# --- Server ---

resource "hcloud_server" "langrag" {
  name        = "langrag-prod"
  server_type = var.server_type
  location    = var.server_location
  image       = "ubuntu-24.04"

  ssh_keys = [hcloud_ssh_key.default.id]

  firewall_ids = [hcloud_firewall.langrag.id]

  user_data = <<-EOF
    #!/bin/bash
    set -euo pipefail

    # Update system
    apt-get update && apt-get upgrade -y

    # Install Docker (official method)
    apt-get install -y ca-certificates curl gnupg
    install -m 0755 -d /etc/apt/keyrings
    curl -fsSL https://download.docker.com/linux/ubuntu/gpg | gpg --dearmor -o /etc/apt/keyrings/docker.gpg
    chmod a+r /etc/apt/keyrings/docker.gpg

    echo \
      "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/ubuntu \
      $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
      tee /etc/apt/sources.list.d/docker.list > /dev/null

    apt-get update
    apt-get install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

    # Enable and start Docker
    systemctl enable docker
    systemctl start docker

    # Create app directory
    mkdir -p /opt/langrag

    # Install fail2ban for SSH brute-force protection
    apt-get install -y fail2ban
    systemctl enable fail2ban
    systemctl start fail2ban
  EOF

  labels = {
    project     = "langrag"
    environment = "production"
  }
}

# --- Cloudflare DNS ---

resource "cloudflare_record" "root" {
  zone_id = var.cloudflare_zone_id
  name    = "@"
  content = hcloud_server.langrag.ipv4_address
  type    = "A"
  proxied = true
  ttl     = 1 # Auto (required when proxied)
}

resource "cloudflare_record" "www" {
  zone_id = var.cloudflare_zone_id
  name    = "www"
  content = hcloud_server.langrag.ipv4_address
  type    = "A"
  proxied = true
  ttl     = 1 # Auto (required when proxied)
}

# --- Cloudflare SSL ---
# NOTE: SSL mode set to "Full" manually in Cloudflare dashboard.
# The "Edit zone DNS" API token doesn't have permission for zone settings.
# To manage via Terraform, create a token with "Zone Settings: Edit" permission.
