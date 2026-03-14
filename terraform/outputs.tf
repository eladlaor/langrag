output "server_ip" {
  description = "Public IPv4 address of the LangRAG server"
  value       = hcloud_server.langrag.ipv4_address
}

output "server_status" {
  description = "Server status"
  value       = hcloud_server.langrag.status
}

output "domain_url" {
  description = "Production URL"
  value       = "https://www.langrag.ai"
}

output "ssh_command" {
  description = "SSH into the server"
  value       = "ssh root@${hcloud_server.langrag.ipv4_address}"
}
