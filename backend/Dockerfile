# Universal Parcel Scraper (Peek's open-source tracking engine) for live package tracking with
# no account or key: Node and the npm package, copied into the same image below so the mail
# worker can run it (mail/trackers/scraper.py). The pinned version is the newest under Apache-2.0;
# from 0.1294.0 it's PolyForm Noncommercial (fine for personal use). Change it with
#   docker compose build --build-arg PARCEL_SCRAPER_VERSION=<version>
# USPS, UPS, FedEx and others only answer a real browser, so the image also carries Chromium and
# the scraper's optional browser packages (adds roughly 400 MB). Leave them out with
#   --build-arg PARCEL_SCRAPER_BROWSER=0   (those carriers then can't be tracked live)
FROM node:24-slim AS parcel-scraper
ARG PARCEL_SCRAPER_VERSION=0.1225.0
ARG PARCEL_SCRAPER_BROWSER=1
RUN npm install --prefix /opt/parcel-scraper --omit=dev --no-audit --no-fund \
	"universal-parcel-scraper@${PARCEL_SCRAPER_VERSION}" \
	&& if [ "$PARCEL_SCRAPER_BROWSER" = 1 ]; then \
		cd /opt/parcel-scraper && npm install --omit=dev --no-audit --no-fund \
		$(node -p "Object.entries(require('./node_modules/universal-parcel-scraper/package.json').peerDependencies||{}).map(([n,v])=>n+'@'+v).join(' ')"); \
	fi \
	&& npm cache clean --force

# 3.14: the mail worker uses imaplib IDLE (added in 3.14).
FROM python:3.14-slim

ENV PYTHONDONTWRITEBYTECODE=1 PYTHONUNBUFFERED=1 KERN_DATA_DIR=/data
WORKDIR /app

# ffmpeg merges yt-dlp downloads; git powers the built-in git server (git http-backend);
# libstdc++6 is what the copied Node binary links against; chromium is the parcel scraper's browser.
ARG PARCEL_SCRAPER_BROWSER=1
RUN apt-get update && apt-get install -y --no-install-recommends ffmpeg git libstdc++6 \
	$(if [ "$PARCEL_SCRAPER_BROWSER" = 1 ]; then echo chromium fonts-liberation; fi) \
	&& rm -rf /var/lib/apt/lists/*
COPY --from=parcel-scraper /usr/local/bin/node /usr/local/bin/node
COPY --from=parcel-scraper /opt/parcel-scraper /opt/parcel-scraper
ENV KERN_PARCEL_SCRAPER=/opt/parcel-scraper/node_modules/universal-parcel-scraper/dist/cli/index.js
# Passed to the scraper only when the browser is really there (mail/trackers/scraper.py).
ENV TRACKING_CHROMIUM_PATH=/usr/bin/chromium
COPY requirements.txt .
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN useradd --system --uid 10001 --user-group --home-dir /data --no-create-home kern \
	&& mkdir -p /data && chown kern:kern /data && chmod +x /app/entrypoint.sh
VOLUME /data
EXPOSE 8000

# Starts as root only long enough to fix the data volume's ownership, then drops to "kern".
ENTRYPOINT ["/app/entrypoint.sh"]
