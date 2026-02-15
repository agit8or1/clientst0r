# Client St0r Docker Deployment

This directory contains Docker deployment configurations for Client St0r.

## Quick Start

### 1. Create `.env` File

Copy `.env.example` to `.env` and configure:

```bash
cp .env.example .env
nano .env
```

Required environment variables:
```env
# Django
DEBUG=False
SECRET_KEY=your-secret-key-here
ALLOWED_HOSTS=localhost,yourdomain.com
SITE_URL=https://yourdomain.com

# Database
DB_NAME=clientst0r
DB_USER=clientst0r
DB_PASSWORD=secure-password-here
DB_HOST=db
DB_PORT=3306
DB_ROOT_PASSWORD=secure-root-password-here

# Encryption
APP_MASTER_KEY=your-master-key-here
API_KEY_SECRET=your-api-secret-here

# Superuser (optional, for initial setup)
DJANGO_SUPERUSER_USERNAME=admin
DJANGO_SUPERUSER_PASSWORD=secure-admin-password
DJANGO_SUPERUSER_EMAIL=admin@example.com

# Ports
WEB_PORT=8000
NGINX_HTTP_PORT=80
NGINX_HTTPS_PORT=443
```

### 2. Build and Start

```bash
# Build images
docker-compose build

# Start services
docker-compose up -d

# View logs
docker-compose logs -f web

# Check status
docker-compose ps
```

### 3. Access Application

- **Web UI**: http://localhost (or configured port)
- **Health Check**: http://localhost/health/

## Services

### Core Services (Always Running)

- **db**: MariaDB 10.11 database
- **redis**: Redis cache for sessions and caching
- **web**: Client St0r Django application (Gunicorn)
- **nginx**: Reverse proxy and static file server

### Optional Services (Profiles)

Enable Celery workers for background tasks:

```bash
docker-compose --profile celery up -d
```

This starts:
- **celery**: Background task worker
- **celery-beat**: Periodic task scheduler

## Volumes

Data is persisted in named volumes:

- `clientst0r-mariadb-data`: Database files
- `clientst0r-redis-data`: Redis persistence
- `clientst0r-media`: Uploaded files
- `clientst0r-static`: Static files (CSS, JS, images)

## Management Commands

### Run Django Commands

```bash
docker-compose exec web python manage.py <command>
```

Examples:
```bash
# Create superuser
docker-compose exec web python manage.py createsuperuser

# Run migrations
docker-compose exec web python manage.py migrate

# Collect static files
docker-compose exec web python manage.py collectstatic

# Django shell
docker-compose exec web python manage.py shell
```

### Database Backup

```bash
# Backup database
docker-compose exec db mysqldump -u$DB_USER -p$DB_PASSWORD $DB_NAME > backup.sql

# Restore database
docker-compose exec -T db mysql -u$DB_USER -p$DB_PASSWORD $DB_NAME < backup.sql
```

### View Logs

```bash
# All services
docker-compose logs -f

# Specific service
docker-compose logs -f web
docker-compose logs -f db
docker-compose logs -f nginx
```

## SSL/TLS Configuration

### Using Let's Encrypt

1. Install certbot:
```bash
apt-get install certbot
```

2. Generate certificates:
```bash
certbot certonly --standalone -d yourdomain.com
```

3. Copy certificates:
```bash
cp /etc/letsencrypt/live/yourdomain.com/fullchain.pem docker/nginx/ssl/cert.pem
cp /etc/letsencrypt/live/yourdomain.com/privkey.pem docker/nginx/ssl/key.pem
```

4. Uncomment HTTPS server block in `docker/nginx/conf.d/clientst0r.conf`

5. Restart nginx:
```bash
docker-compose restart nginx
```

### Certificate Auto-Renewal

Add to crontab:
```bash
0 0 1 * * certbot renew --quiet && cp /etc/letsencrypt/live/yourdomain.com/*.pem /path/to/docker/nginx/ssl/ && docker-compose restart nginx
```

## Scaling

### Horizontal Scaling

Scale web workers:
```bash
docker-compose up -d --scale web=4
```

### Resource Limits

Add to `docker-compose.yml`:
```yaml
services:
  web:
    deploy:
      resources:
        limits:
          cpus: '2'
          memory: 2G
        reservations:
          cpus: '1'
          memory: 1G
```

## Monitoring

### Health Checks

All services have health checks configured:

```bash
# Check service health
docker-compose ps

# View health check logs
docker inspect clientst0r-web --format='{{json .State.Health}}' | jq
```

### Container Stats

```bash
docker stats
```

## Troubleshooting

### Services Won't Start

```bash
# Check logs
docker-compose logs

# Rebuild without cache
docker-compose build --no-cache

# Remove volumes and start fresh
docker-compose down -v
docker-compose up -d
```

### Database Connection Issues

```bash
# Check database is running
docker-compose ps db

# Test database connection
docker-compose exec web python manage.py dbshell

# View database logs
docker-compose logs db
```

### Permission Issues

```bash
# Fix ownership
docker-compose exec web chown -R clientst0r:clientst0r /app/media /app/logs
```

## Production Recommendations

1. **Use external database**: For better performance and backups
2. **Configure SSL/TLS**: Always use HTTPS in production
3. **Set up monitoring**: Use tools like Prometheus + Grafana
4. **Regular backups**: Automate database and media backups
5. **Resource limits**: Set appropriate CPU and memory limits
6. **Log rotation**: Configure log rotation for container logs
7. **Security scanning**: Regularly scan images for vulnerabilities
8. **Update regularly**: Keep base images and dependencies updated

## Backup Strategy

### Automated Backups

Create backup script (`backup.sh`):

```bash
#!/bin/bash
BACKUP_DIR="/backups/$(date +%Y%m%d)"
mkdir -p $BACKUP_DIR

# Database backup
docker-compose exec -T db mysqldump -u$DB_USER -p$DB_PASSWORD $DB_NAME | gzip > $BACKUP_DIR/database.sql.gz

# Media files backup
docker cp clientst0r-web:/app/media $BACKUP_DIR/media

# Keep last 30 days
find /backups -type d -mtime +30 -exec rm -rf {} \;
```

Schedule with cron:
```bash
0 2 * * * /path/to/backup.sh
```

## Updates

### Updating Client St0r

```bash
# Pull latest changes
git pull

# Rebuild and restart
docker-compose build
docker-compose up -d

# Run migrations
docker-compose exec web python manage.py migrate
```

## Support

For issues and questions:
- GitHub Issues: https://github.com/agit8or1/clientst0r/issues
- Discussions: https://github.com/agit8or1/clientst0r/discussions
