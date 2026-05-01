# Bare-metal systemd deployment

```bash
# 1. Create a system user and directories
sudo useradd -r -s /usr/sbin/nologin pharos
sudo mkdir -p /opt/pharos /etc/pharos /var/lib/pharos
sudo chown -R pharos:pharos /opt/pharos /var/lib/pharos

# 2. Install Pharos into a venv at /opt/pharos/venv
sudo -u pharos python3 -m venv /opt/pharos/venv
sudo -u pharos /opt/pharos/venv/bin/pip install /path/to/pharos/backend

# 3. Configuration
sudo cp /path/to/pharos/.env.example /etc/pharos/pharos.env
sudo $EDITOR /etc/pharos/pharos.env
# Make sure PHAROS_DB_DIR=/var/lib/pharos

# 4. Initialize databases
sudo -u pharos /opt/pharos/venv/bin/pharos init
sudo -u pharos /opt/pharos/venv/bin/pharos adduser admin --admin

# 5. Install service units
sudo cp pharos-*.service pharos-*.timer /etc/systemd/system/
sudo systemctl daemon-reload
sudo systemctl enable --now \
    pharos-api.service \
    pharos-ingestion.service \
    pharos-lantern.service \
    pharos-archiver.timer

# 6. Optional: nginx reverse proxy
# Drop the snippet below into /etc/nginx/sites-available/pharos.conf,
# enable it, and restart nginx.
```

## Nginx snippet

```nginx
server {
    listen 443 ssl;
    server_name pharos.example.com;

    ssl_certificate     /etc/letsencrypt/live/pharos.example.com/fullchain.pem;
    ssl_certificate_key /etc/letsencrypt/live/pharos.example.com/privkey.pem;

    # Frontend (if running Next.js separately on :3000)
    location / {
        proxy_pass http://127.0.0.1:3000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }

    # Backend API
    location /api/ {
        proxy_pass http://127.0.0.1:8000;
        proxy_set_header Host $host;
        proxy_set_header X-Forwarded-For $proxy_add_x_forwarded_for;
        proxy_set_header X-Forwarded-Proto $scheme;
    }
}
```
