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
	exec setpriv --reuid=kern --regid=kern --init-groups "$0" "$@"
fi

if ! touch "${KERN_DATA_DIR:-/data}/.write-test" 2>/dev/null; then
	echo "kern: cannot write to ${KERN_DATA_DIR:-/data} (running as uid $(id -u)). Check the volume's permissions." >&2
	exit 1
fi
rm -f "${KERN_DATA_DIR:-/data}/.write-test"

python manage.py kern_boot
exec gunicorn kern.wsgi:application --bind 0.0.0.0:8000 --workers 2 --threads 4 --timeout 600 \
	--no-control-socket --access-logfile - --error-logfile -
