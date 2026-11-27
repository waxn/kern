#!/bin/sh
# Start Kern: make sure the data volume is writable, then run as the unprivileged "kern" user.
set -e

if [ "$(id -u)" = "0" ]; then
	mkdir -p "${KERN_DATA_DIR:-/data}"
	# A new or copied volume can belong to root; hand it to the app user.
	if [ "$(stat -c %u "${KERN_DATA_DIR:-/data}")" != "$(id -u kern)" ]; then
		echo "kern: fixing ownership of ${KERN_DATA_DIR:-/data}"
		chown -R kern:kern "${KERN_DATA_DIR:-/data}"
	fi
	groups="--init-groups"
	if [ "${1:-}" = "apps-worker" ]; then
		# The apps service starts every app as a user of its own (kernapps/isolation.py), so it keeps
		# exactly the capabilities that needs: switching users, handing an app its folder, stopping it.
		caps="+setuid,+setgid,+chown,+kill"
		exec setpriv --reuid=kern --regid=kern --init-groups --inh-caps="$caps" --ambient-caps="$caps" \
			--bounding-set="-all,$caps" "$0" "$@"
	fi
	sock="${KERN_DOCKER_SOCKET:-/var/run/docker.sock}"
	if [ "${1:-}" = "ci-worker" ] && [ -S "$sock" ]; then
		# The CI worker needs the Docker socket, which belongs to the host's docker group.
		groups="--groups=$(stat -c %g "$sock"),$(id -g kern)"
	fi
	exec setpriv --reuid=kern --regid=kern "$groups" "$0" "$@"
fi

# Files Kern writes are not readable by other users (apps run as users of their own).
umask 027

if ! touch "${KERN_DATA_DIR:-/data}/.write-test" 2>/dev/null; then
	echo "kern: cannot write to ${KERN_DATA_DIR:-/data} (running as uid $(id -u)). Check the volume's permissions." >&2
	exit 1
fi
rm -f "${KERN_DATA_DIR:-/data}/.write-test"

if [ "${1:-}" = "mail-worker" ]; then
	# The mail service (docker-compose.yml): the backend has already migrated everything.
	exec python manage.py mail_worker
fi
if [ "${1:-}" = "ci-worker" ]; then
	# The ci service (docker-compose.yml): runs queued CI pipelines of the git server.
	exec python manage.py ci_worker
fi
if [ "${1:-}" = "apps-worker" ]; then
	# The apps service (docker-compose.yml): runs your apps and serves them at /<path>/.
	export KERN_APPS_BIND="${KERN_APPS_BIND:-0.0.0.0}"
	exec python manage.py apps_worker
fi
if [ "${1:-}" = "ssh-server" ]; then
	# The ssh service (docker-compose.yml): git over SSH with public keys.
	exec python manage.py ssh_server --port 2222
fi
if [ "$#" -gt 0 ]; then
	# One-off commands: docker compose run --rm backend python manage.py …
	exec "$@"
fi

python manage.py kern_boot
exec gunicorn kern.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 12 --timeout 600 \
	--no-control-socket --access-logfile - --error-logfile -
