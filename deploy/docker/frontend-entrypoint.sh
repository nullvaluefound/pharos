#!/bin/sh
# Templates /etc/nginx/conf.d/default.conf so PHAROS_API_URL can be set at
# container runtime.
#
# IMPORTANT: the upstream URL must NOT end with a slash. Pharos mounts all
# API routes under /api/v1/... so we want nginx to *preserve* the /api/
# prefix when forwarding, not strip it. With `proxy_pass http://host:port`
# (no trailing slash), nginx forwards the full original request URI; with
# a trailing slash, nginx replaces /api/ with the URI from proxy_pass and
# the backend ends up seeing /v1/auth/login (404).
set -eu

API_URL="${PHAROS_API_URL:-http://pharos:8000}"
# Strip any trailing slash; the location block in nginx.conf does the right
# thing by itself.
API_URL="${API_URL%/}"

CONF=/etc/nginx/conf.d/default.conf
sed -i "s|__PHAROS_API_URL__|${API_URL}|g" "$CONF"
echo "[pharos] frontend reverse-proxying /api/ -> ${API_URL}"
