package app.kern.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

/** The phone reads the apps API the way the web does (frontend/src/lib/apps/types.ts) and survives odd answers. */
class AppsTest {
    private val list = """
        {"apps": [
          {"id": 1, "slug": "chickens", "name": "Chickens", "icon": "🐔", "color": "orange", "path": "/chickens/", "access": "private",
           "enabled": true, "state": "running", "state_detail": "", "future_field": [1, 2],
           "live": {"number": 3, "status": "live", "short": "abc12345", "seconds": 12},
           "latest": {"number": 3, "status": "live", "short": "abc12345", "subject": "Fix it"},
           "metrics": {"running": true, "uptime": 125, "cpu": 0.4, "rss": 1048576, "restarts": 0, "held": false, "last_exit": null}},
          {"slug": "broken", "name": "Broken", "state": null, "icon": null, "live": "not an object"},
          {"id": 3, "name": "No slug"},
          {"slug": "shop", "name": "Shop", "enabled": false, "state": "stopped", "latest": null, "metrics": null}
        ], "worker": true, "isolated": false}
    """

    @Test fun parsesAListAndSkipsEntriesThatDoNotFit() {
        val l = parseApps(list)
        assertEquals(listOf("chickens", "shop"), l.apps.map { it.slug })
        val c = l.apps[0]
        assertEquals("🐔", c.icon)
        assertEquals(3, c.live?.number)
        assertEquals("Fix it", c.latest?.subject)
        assertEquals(125.0, c.metrics?.uptime ?: 0.0, 0.0)
        assertEquals(false, l.apps[1].enabled)
        assertTrue(l.worker)
    }

    @Test fun garbageIsAnEmptyList() {
        assertEquals(emptyList<HostedApp>(), parseApps("not json").apps)
        assertEquals(emptyList<HostedApp>(), parseApps("[]").apps)
        assertEquals(false, parseApps("""{"apps": [], "worker": false}""").worker)
    }

    @Test fun detailDecodesWithMissingAndExtraFields() {
        val a = KernJson.decodeFromString(HostedApp.serializer(), """{"slug": "x", "worker": false, "env_names": ["A"], "state": "failed", "state_detail": "Build failed."}""")
        assertEquals("x", a.displayName)
        assertEquals(false, a.worker)
        assertEquals("Build failed.", a.stateDetail)
    }

    private fun app(state: String, latest: String? = null, held: Boolean = false, live: Boolean = true) = HostedApp(
        slug = "a", state = state,
        latest = latest?.let { AppDeploy(number = 4, status = it) },
        live = if (live) AppDeploy(number = 3, status = "live") else null,
        metrics = AppMetrics(held = held),
    )

    @Test fun statusMatchesTheWeb() {
        assertEquals(AppView("Running", AppTone.Ok), appView(app("running", "live")))
        assertEquals(AppView("Stopped", AppTone.Off), appView(app("stopped")))
        assertEquals("Deploying", appView(app("running", "building")).label)
        assertEquals("Queued", appView(app("stopped", "queued")).label)
        assertEquals("Building", appView(app("stopped", "starting")).label)
        assertEquals("Crashed", appView(app("crashed", held = true)).label)
        assertEquals("Restarting", appView(app("crashed")).label)
        assertEquals(AppTone.Bad, appView(app("failed")).tone)
        assertEquals("Not deployed", appView(app("new", live = false)).label)
        assertEquals("Stopped", appView(app("new")).label)
        assertEquals("Service offline", appView(app("running"), worker = false).label)
    }

    @Test fun addressAndSummary() {
        val a = HostedApp(slug = "chickens", path = "/chickens/")
        assertEquals("https://kern.example.org/chickens/", appUrl("https://kern.example.org/", a))
        assertEquals("https://k.test/chickens/", appUrl("https://k.test", HostedApp(slug = "chickens")))
        val l = parseApps(list)
        assertEquals("1 running", appsSummary(l))
        assertEquals("No apps yet", appsSummary(AppsList()))
        assertEquals("2 apps, none running", appsSummary(AppsList(listOf(HostedApp("a", state = "stopped"), HostedApp("b", state = "failed")))))
        assertEquals("Service offline", appsSummary(AppsList(listOf(HostedApp("a", state = "running")), worker = false)))
    }

    @Test fun logKeepsTheLastLinesAndSplitsTheMarks() {
        val text = (1..150).joinToString("\n") { "2026-11-27T10:00:00Z   line $it" } +
            "\n2026-11-27T10:01:02Z ! \u001B[31mboom\u001B[0m\n2026-11-27T10:01:03Z # restarting\nno prefix here\n"
        val lines = parseAppLog(text, 100)
        assertEquals(100, lines.size)
        assertEquals(AppLogLine("10:01:02", "!", "boom"), lines.first { it.mark == "!" })
        assertEquals(AppLogLine("10:01:03", "#", "restarting"), lines[lines.size - 2])
        assertEquals(AppLogLine("", " ", "no prefix here"), lines.last())
        assertEquals(emptyList<AppLogLine>(), parseAppLog(""))
    }

    @Test fun uptimeReadsLikeTheWeb() {
        assertEquals("45s", appUptime(45.0))
        assertEquals("2m", appUptime(125.0))
        assertEquals("1h 1m", appUptime(3660.0))
        assertEquals("2d 3h", appUptime(2 * 86400.0 + 3 * 3600))
    }
}
