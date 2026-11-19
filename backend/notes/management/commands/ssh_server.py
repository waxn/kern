"""Serve git over SSH: ``python manage.py ssh_server``.

Runs as its own service next to the web server (docker-compose.yml "ssh").
"""
import asyncio
import logging
import signal

from django.core.management.base import BaseCommand

from notes import gitssh


class Command(BaseCommand):
    help = "Serve git repositories over SSH (public-key sign-in only)."

    def add_arguments(self, parser):
        parser.add_argument("--host", default="0.0.0.0")
        parser.add_argument("--port", type=int, default=2222)

    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        asyncio.run(self.main(opts["host"], opts["port"]))

    async def main(self, host, port):
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        await gitssh.run(host, port, stop)
