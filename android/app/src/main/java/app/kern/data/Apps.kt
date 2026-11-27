package app.kern.data

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull

/** How an app looks right now. Mirrors `view()` in the web's frontend/src/lib/apps/types.ts. */
enum class AppTone { Ok, Busy, Off, Bad }

data class AppView(val label: String, val tone: AppTone, val detail: String = "")

private fun AppDeploy.inProgress() = status == "queued" || status == "building" || status == "starting"

/** The state, refined by what the apps service and the newest deployment say. */
fun appView(a: HostedApp, worker: Boolean = true): AppView {
    val dep = a.latest
    val deploying = dep != null && dep.inProgress()
    return when {
        !worker -> AppView("Service offline", AppTone.Bad, "The apps service is not running.")
        deploying && a.state == "running" -> AppView("Deploying", AppTone.Busy, "Deployment #${dep!!.number} is ${dep.status}.")
        deploying -> AppView(if (dep!!.status == "queued") "Queued" else "Building", AppTone.Busy, "Deployment #${dep.number}")
        else -> when (a.state) {
            "running" -> AppView("Running", AppTone.Ok)
            "starting" -> AppView("Starting", AppTone.Busy, a.stateDetail)
            "building" -> AppView("Building", AppTone.Busy, a.stateDetail)
            "crashed" -> AppView(if (a.metrics?.held == true) "Crashed" else "Restarting", AppTone.Bad, a.stateDetail)
            "failed" -> AppView("Failed", AppTone.Bad, a.stateDetail)
            "stopped" -> AppView("Stopped", AppTone.Off)
            else -> AppView(if (a.live != null) "Stopped" else "Not deployed", AppTone.Off, a.stateDetail)
        }
    }
}

/** Where the app is served: `https://<server>/<path>/`. */
fun appUrl(base: String, a: HostedApp): String {
    val p = a.path.trim('/').ifBlank { a.slug }
    return base.trimEnd('/') + "/" + p + "/"
}

/** The subtitle of the Apps tile in More. */
fun appsSummary(list: AppsList): String {
    val running = list.apps.count { it.state == "running" }
    return when {
        list.apps.isEmpty() -> "No apps yet"
        !list.worker -> "Service offline"
        running > 0 -> "$running running"
        list.apps.size == 1 -> "1 app, stopped"
        else -> "${list.apps.size} apps, none running"
    }
}

/** Decodes `GET /apps`, skipping an entry that doesn't parse instead of failing the whole list. */
fun parseApps(text: String): AppsList {
    val o = runCatching { KernJson.parseToJsonElement(text) }.getOrNull() as? JsonObject ?: return AppsList()
    val apps = (o["apps"] as? JsonArray).orEmpty().mapNotNull { runCatching { KernJson.decodeFromJsonElement(HostedApp.serializer(), it) }.getOrNull() }
    return AppsList(apps, (o["worker"] as? JsonPrimitive)?.booleanOrNull ?: true)
}

/** One line of an app log. [mark]: " " output, "!" error, "#" Kern's own notes. */
data class AppLogLine(val time: String, val mark: String, val text: String)

private val ANSI = Regex("\u001B\\[[0-9;?]*[A-Za-z]")
private val LOG_LINE = Regex("^\\d{4}-\\d\\d-\\d\\dT(\\d\\d:\\d\\d:\\d\\d)Z ([ !#]) ?(.*)$")

/** The last [max] lines of a log chunk, colour codes removed and the "<time> <mark> " prefix split off. */
fun parseAppLog(text: String, max: Int = 100): List<AppLogLine> =
    text.split('\n').dropLastWhile { it.isEmpty() }.takeLast(max).map { raw ->
        val l = raw.replace(ANSI, "").trimEnd('\r')
        LOG_LINE.matchEntire(l)?.let { AppLogLine(it.groupValues[1], it.groupValues[2], it.groupValues[3]) } ?: AppLogLine("", " ", l)
    }

val APP_ACCESS = mapOf("private" to "Only me", "users" to "Signed-in users", "public" to "Everyone")
val APP_TRIGGERS = mapOf("push" to "Push", "manual" to "Manual", "hook" to "Deploy hook", "ai" to "AI builder", "rollback" to "Rollback", "create" to "Created", "edit" to "Edited in Kern")
val APP_DEPLOY_STATUS = mapOf("live" to "Live", "old" to "Replaced", "failed" to "Failed", "cancelled" to "Cancelled", "queued" to "Queued", "building" to "Building", "starting" to "Starting")

fun appUptime(s: Double): String {
    val n = s.toLong()
    return when {
        n < 60 -> "${n}s"
        n < 3600 -> "${n / 60}m"
        n < 86400 -> "${n / 3600}h ${(n % 3600) / 60}m"
        else -> "${n / 86400}d ${(n % 86400) / 3600}h"
    }
}
