output "environment_type" {
  value = var.environment_type
}

output "resource_prefix" {
  value = local.prefix
}

output "main_network_name" {
  value = docker_network.main.name
}

output "worker_network_name" {
  value = local.is_multi ? docker_network.workers[0].name : null
}

output "container_count" {
  value = (
    length(docker_container.minimal) +
    length(docker_container.backend) +
    length(docker_container.gateway) +
    length(docker_container.ingress) +
    length(docker_container.workers)
  )
}
