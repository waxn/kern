FROM python:3.13-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KERN_DATA_DIR=/data
WORKDIR /app

COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 --user-group --home-dir /data --no-create-home kern \
	&& mkdir -p /data && chown kern:kern /data && chmod +x /app/entrypoint.sh
VOLUME /data
EXPOSE 8000

# Starts as root only long enough to fix the data volume's ownership, then drops to "kern".
CMD ["/app/entrypoint.sh"]
