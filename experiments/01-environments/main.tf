terraform {
  required_version = ">= 1.6.0"

  required_providers {
    docker = {
      source  = "registry.opentofu.org/kreuzwerker/docker"
      version = "4.6.0"
    }
  }
}

provider "docker" {}

locals {
  prefix      = "${var.env_name}-${var.environment_type}"
  is_minimal  = var.environment_type == "minimal"
  is_two_tier = var.environment_type == "two-tier"
  is_multi    = var.environment_type == "multi-worker"
}

resource "docker_network" "main" {
  name = "${local.prefix}-net"
}

resource "docker_network" "workers" {
  count = local.is_multi ? 1 : 0
  name  = "${local.prefix}-workers-net"
}

resource "docker_volume" "shared" {
  count = local.is_two_tier ? 1 : 0
  name  = "${local.prefix}-shared-vol"
}

resource "docker_image" "alpine" {
  name         = "alpine:3.20"
  keep_locally = true
}

resource "docker_image" "nginx" {
  name         = "nginx:1.27-alpine"
  keep_locally = true
}

resource "docker_container" "minimal" {
  count = local.is_minimal ? 1 : 0
  name  = "${local.prefix}-node"
  image = docker_image.alpine.image_id

  networks_advanced {
    name = docker_network.main.name
  }

  command = ["sh", "-c", "sleep 3600"]
}

resource "docker_container" "backend" {
  count = local.is_two_tier ? 1 : 0
  name  = "${local.prefix}-backend"
  image = docker_image.nginx.image_id

  networks_advanced {
    name = docker_network.main.name
  }

  mounts {
    target = "/usr/share/nginx/html"
    type   = "volume"
    source = docker_volume.shared[0].name
  }
}

resource "docker_container" "gateway" {
  count = local.is_two_tier ? 1 : 0
  name  = "${local.prefix}-gateway"
  image = docker_image.nginx.image_id

  networks_advanced {
    name = docker_network.main.name
  }

  ports {
    internal = 80
    external = var.gateway_port
  }

  mounts {
    target = "/usr/share/nginx/html"
    type   = "volume"
    source = docker_volume.shared[0].name
  }

  depends_on = [docker_container.backend]
}

resource "docker_container" "ingress" {
  count = local.is_multi ? 1 : 0
  name  = "${local.prefix}-ingress"
  image = docker_image.nginx.image_id

  networks_advanced {
    name = docker_network.main.name
  }

  networks_advanced {
    name = docker_network.workers[0].name
  }

  ports {
    internal = 80
    external = var.ingress_port
  }
}

resource "docker_container" "workers" {
  count = local.is_multi ? var.worker_count : 0
  name  = "${local.prefix}-worker-${count.index}"
  image = docker_image.alpine.image_id

  networks_advanced {
    name = docker_network.workers[0].name
  }

  command = ["sh", "-c", "sleep 3600"]
}
