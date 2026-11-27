"""Run every app: ``python manage.py apps_worker`` (the ``apps`` service in docker-compose.yml).

Starts the supervisor (processes, deployments, the AI builder) and two HTTP servers: the gateway that
serves ``/<slug>/`` (KERN_APPS_PORT, 8100) and the control port the backend talks to
(KERN_APPS_CONTROL_PORT, 8101). Both listen on KERN_APPS_BIND (127.0.0.1; 0.0.0.0 in Docker).
"""
import asyncio
import logging
import os
import signal

from aiohttp import web
from django.core.management.base import BaseCommand


class Command(BaseCommand):
    help = "Run the apps supervisor and gateway."

    def handle(self, *args, **opts):
        logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
        logging.getLogger("aiohttp.access").setLevel(logging.WARNING)
        asyncio.run(self.main())

    async def main(self):
        from kernapps import isolation
        from kernapps.builder import Builder
        from kernapps.gateway import Control, Gateway
        from kernapps.supervisor import Supervisor

        os.umask(0o027)
        log = logging.getLogger("kern.apps")
        sup = Supervisor()
        sup.builder = Builder(sup)
        gw = Gateway(sup)
        await gw.start()
        bind = os.environ.get("KERN_APPS_BIND", "127.0.0.1")
        port = int(os.environ.get("KERN_APPS_PORT", 8100))
        cport = int(os.environ.get("KERN_APPS_CONTROL_PORT", 8101))
        runners = []
        for app, p in ((gw.app(), port), (Control(sup).app(), cport)):
            r = web.AppRunner(app, access_log=None, handle_signals=False)
            await r.setup()
            await web.TCPSite(r, bind, p).start()
            runners.append(r)
        log.info("apps: gateway on %s:%s, control on %s:%s, %s", bind, port, bind, cport,
                 "each app runs as its own user" if isolation.isolated() else "apps are NOT isolated (same user as Kern)")
        stop = asyncio.Event()
        loop = asyncio.get_running_loop()
        for sig in (signal.SIGTERM, signal.SIGINT):
            loop.add_signal_handler(sig, stop.set)
        task = asyncio.create_task(sup.run())
        await stop.wait()
        log.info("apps: stopping every app")
        await sup.shutdown()
        task.cancel()
        await sup.builder.shutdown()
        for r in runners:
            await r.cleanup()
        await gw.close()
