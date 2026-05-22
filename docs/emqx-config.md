# EMQX Configuration for IoT Device Management

# ===========================================

#

# This file documents the recommended EMQX configuration

# for the school bell IoT system with 10K+ devices.

#

# Place these settings in emqx.conf or configure via EMQX Dashboard.

# ===========================================

# AUTHENTICATION

# ===========================================

#

# Option 1: Built-in Database (for small deployments)

# Enable via EMQX Dashboard -> Authentication -> Built-in Database

#

# Option 2: PostgreSQL Backend (recommended for this project)

# This allows Django to manage device credentials directly.

# PostgreSQL Authentication Query:

# SELECT password_hash FROM devices WHERE device_id = ${username}

#

# Configure in EMQX:

# authentication {

# backend = "postgresql"

# mechanism = "password_based"

# server = "localhost:5432"

# database = "iot_devices"

# username = "emqx_auth"

# password = "secure-password"

# query = "SELECT mqtt_password_hash AS password_hash FROM devices WHERE device_id = ${username} LIMIT 1"

# password_hash_algorithm = "sha256"

# }

# ===========================================

# AUTHORIZATION (ACL)

# ===========================================

#

# Devices should only access their own topics:

# - Subscribe: object/{device_id}/cmd

# - Publish: object/diagnostics, object/{device_id}/ota_status

#

# Backend server can access all topics.

# ACL Rules (PostgreSQL backend):

# authorization {

# type = "postgresql"

# server = "localhost:5432"

# database = "iot_devices"

# username = "emqx_auth"

# password = "secure-password"

# query = "SELECT action, permission, topic FROM mqtt_acl WHERE device_id = ${username}"

# }

# Or use file-based ACL for simplicity:

#

# {allow, {user, "django_backend"}, all, ["#"]}.

# {allow, {user, "django_listener"}, subscribe, ["object/diagnostics", "object/+/ota_status"]}.

# {allow, all, subscribe, ["object/${clientid}/cmd"]}.

# {allow, all, publish, ["object/diagnostics", "object/${clientid}/ota_status"]}.

# {deny, all}.

# ===========================================

# PERFORMANCE TUNING (10K+ devices)

# ===========================================

# Increase connection limits

# listener.tcp.external.max_connections = 20000

# listener.tcp.external.max_conn_rate = 1000

# Memory settings

# node.process_limit = 2000000

# node.max_ports = 1000000

# Message queue

# mqtt.max_mqueue_len = 1000

# mqtt.mqueue_store_qos0 = false

# Session settings

# mqtt.session_expiry_interval = 7200

# mqtt.max_subscriptions = 10

# mqtt.upgrade_qos = false

# Rate limiting (prevent DoS)

# listener.tcp.external.rate_limit = "100KB,10s"

# listener.tcp.external.messages_rate = "100,1s"

# ===========================================

# TLS/SSL (Production)

# ===========================================

# Enable TLS for production:

# listener.ssl.external.port = 8883

# listener.ssl.external.keyfile = /etc/emqx/certs/key.pem

# listener.ssl.external.certfile = /etc/emqx/certs/cert.pem

# listener.ssl.external.cacertfile = /etc/emqx/certs/ca.pem

# ===========================================

# MONITORING

# ===========================================

# Enable Prometheus metrics:

# prometheus {

# push_gateway_server = "http://localhost:9091"

# interval = "15s"

# }

# Dashboard (default port 18083)

# dashboard.listeners.http.bind = 18083
