variable "puppet_server_count" {
  description = "Number of Puppet Server instances to create"
  type        = number
  default     = 1
}

variable "region_instance_map" {
  type = map(number)
  description = "Map of region to number of compute instances"
  default = {
    source = 0,
    replica = 0
  }
}

variable "region_router_map" {
  type = map(number)
  description = "Map of region to number of compute router instances"
  default = {
    source = 0,
    replica = 0
  }
}

variable "region_map" {
  type = map(string)
  default = {
    source = "us-ashburn-1"
    replica = "eu-frankfurt-1"
  }
}
