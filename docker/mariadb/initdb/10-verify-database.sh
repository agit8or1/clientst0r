# Sourced by the MariaDB image's entrypoint on the FIRST start of an empty
# data volume (files in /docker-entrypoint-initdb.d). Grants the application
# account a scratch database, <DB_NAME>_verify, that Client St0r restores
# each pre-upgrade backup into to prove it is complete before migrating.
# Without it the backup is still taken and checked, but only structurally.
#
# Existing installs (volume already initialised) can run, once:
#   docker compose exec db mariadb -uroot -p \
#     -e "GRANT ALL PRIVILEGES ON \`clientst0r_verify\`.* TO 'clientst0r'@'%';"
docker_process_sql --database=mysql <<-EOSQL
	GRANT ALL PRIVILEGES ON \`${MYSQL_DATABASE}_verify\`.* TO '${MYSQL_USER}'@'%';
	FLUSH PRIVILEGES;
EOSQL
