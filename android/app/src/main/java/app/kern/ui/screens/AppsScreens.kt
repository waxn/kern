package app.kern.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material.icons.outlined.RestartAlt
import androidx.compose.material.icons.outlined.Stop
import androidx.compose.material.icons.outlined.Widgets
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.data.ApiError
import app.kern.data.APP_ACCESS
import app.kern.data.APP_DEPLOY_STATUS
import app.kern.data.APP_TRIGGERS
import app.kern.data.AppDeploy
import app.kern.data.AppLogLine
import app.kern.data.AppTone
import app.kern.data.AppsList
import app.kern.data.HostedApp
import app.kern.data.appUptime
import app.kern.data.appUrl
import app.kern.data.appView
import app.kern.data.parseAppLog
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KButton
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.ago
import app.kern.ui.components.bytes
import app.kern.ui.doc.openUrl
import app.kern.ui.theme.kern
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

/** True when the server said these accounts may not use apps (an administrator turns them on in Settings → Server). */
private fun ApiError.isNotAvailable() = status == 403

@Composable
private fun toneColor(t: AppTone): Color = when (t) {
    AppTone.Ok -> kern.green
    AppTone.Busy -> kern.blue
    AppTone.Bad -> kern.danger
    AppTone.Off -> kern.text3
}

@Composable
private fun StatusChip(label: String, tone: AppTone) {
    val c = toneColor(tone)
    Text(
        label, style = MaterialTheme.typography.labelMedium, color = c, maxLines = 1,
        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(kern.tint(c)).padding(horizontal = 8.dp, vertical = 3.dp),
    )
}

@Composable
private fun AppIcon(a: HostedApp, size: Int = 40) {
    val c = kern.named(a.color.ifBlank { "gray" })
    Box(Modifier.size(size.dp).clip(RoundedCornerShape((size / 4).dp)).background(kern.tint(c)), contentAlignment = Alignment.Center) {
        Text(a.icon.ifBlank { "◇" }, fontSize = (size * 0.5).sp, color = c)
    }
}

@Composable
fun AppsScreen(ws: Workspace, nav: Nav) {
    var list by remember { mutableStateOf<AppsList?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var denied by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    suspend fun load() {
        try { list = ws.kern.apps(); err = null; denied = false }
        catch (e: ApiError) { if (e.isNotAvailable()) denied = true else err = e.message }
        catch (e: Exception) { err = e.message }
    }
    LaunchedEffect(Unit) { load() }
    // Keep looking while something is being built or started.
    LaunchedEffect(list) {
        val l = list ?: return@LaunchedEffect
        if (l.apps.any { appView(it, l.worker).tone == AppTone.Busy }) { delay(3000); load() }
    }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Apps", onBack = { nav.back() })
        val l = list
        when {
            l == null && !denied && err == null -> Loading()
            else -> PullToRefreshBox(refreshing, { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.weight(1f)) {
                LazyColumn(Modifier.fillMaxSize()) {
                    when {
                        denied -> item { EmptyState(Icons.Outlined.Lock, "Apps aren't available for your account", "An administrator can turn them on in Settings → Server on the web.") }
                        l == null -> item { ErrorState(err ?: "Something went wrong.") { scope.launch { load() } } }
                        else -> {
                            if (!l.worker) item {
                                Text(
                                    "The apps service isn't running, so apps can't be started or checked right now.",
                                    style = MaterialTheme.typography.bodySmall, color = kern.danger, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp),
                                )
                            }
                            if (l.apps.isEmpty()) item {
                                EmptyState(Icons.Outlined.Widgets, "No apps yet", "Create one on the web: build it with AI, start from a template, or deploy a repository.")
                            }
                            items(l.apps, key = { it.slug }) { a -> AppRow(a, l.worker) { nav.go("app/${a.slug}") } }
                        }
                    }
                }
            }
        }
    }
}

@Composable
private fun AppRow(a: HostedApp, worker: Boolean, onClick: () -> Unit) {
    val v = appView(a, worker)
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 20.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
        AppIcon(a)
        Spacer(Modifier.width(14.dp))
        Column(Modifier.weight(1f)) {
            Text(a.displayName, style = MaterialTheme.typography.titleSmall, maxLines = 1, overflow = TextOverflow.Ellipsis)
            Text(
                "/${a.slug}/" + if (a.description.isNotBlank()) " · ${a.description}" else "",
                style = MaterialTheme.typography.bodySmall, color = kern.text3, maxLines = 1, overflow = TextOverflow.Ellipsis,
            )
        }
        Spacer(Modifier.width(10.dp))
        StatusChip(v.label, v.tone)
    }
}

@Composable
fun AppScreen(ws: Workspace, nav: Nav, slug: String) {
    var app by remember { mutableStateOf<HostedApp?>(null) }
    var log by remember { mutableStateOf<List<AppLogLine>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var denied by remember { mutableStateOf(false) }
    var acting by remember { mutableStateOf<String?>(null) }
    var confirmStop by remember { mutableStateOf(false) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    suspend fun load() {
        try { app = ws.kern.app(slug); err = null; denied = false }
        catch (e: ApiError) { if (e.isNotAvailable()) denied = true else err = e.message }
        catch (e: Exception) { err = e.message }
        // The log is a convenience: a failure to read it shouldn't hide the app.
        runCatching { ws.kern.appLogs(slug) }.onSuccess { log = parseAppLog(it.text, 100) }
    }
    LaunchedEffect(slug) { load() }
    val busy = app?.let { appView(it, it.worker ?: true).tone == AppTone.Busy } == true
    LaunchedEffect(app) { if (busy) { delay(3000); load() } }

    fun act(action: String) {
        scope.launch {
            acting = action
            try { app = ws.kern.appAction(slug, action) } catch (e: Exception) { snack.error(e) }
            acting = null
            delay(1200) // the apps service takes a moment to report the new state
            load()
        }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        val a = app
        KTopBar(a?.displayName ?: "App", onBack = { nav.back() }, subtitle = "/$slug/")
        when {
            denied -> EmptyState(Icons.Outlined.Lock, "Apps aren't available for your account", "An administrator can turn them on in Settings → Server on the web.")
            a == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
            a == null -> Loading()
            else -> PullToRefreshBox(refreshing, { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.weight(1f)) {
                AppDetail(ws, a, log, acting, { openUrl(ctx, appUrl(ws.kern.api.base, a)) }, ::act) { confirmStop = true }
            }
        }
    }
    if (confirmStop) AlertDialog(
        onDismissRequest = { confirmStop = false }, containerColor = kern.surface,
        title = { Text("Stop ${app?.displayName ?: "this app"}?") },
        text = { Text("It stays unreachable at /$slug/ until you start it again.") },
        confirmButton = { TextButton(onClick = { confirmStop = false; act("stop") }) { Text("Stop", color = kern.danger) } },
        dismissButton = { TextButton(onClick = { confirmStop = false }) { Text("Cancel", color = kern.text2) } },
    )
}

@Composable
private fun AppDetail(
    ws: Workspace, a: HostedApp, log: List<AppLogLine>?, acting: String?,
    onOpen: () -> Unit, onAction: (String) -> Unit, onStop: () -> Unit,
) {
    val worker = a.worker ?: true
    val v = appView(a, worker)
    val canStart = !a.enabled || (a.live == null && a.state in setOf("new", "stopped"))
    Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(bottom = 24.dp)) {
        Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
            AppIcon(a, 52)
            Spacer(Modifier.width(14.dp))
            Column(Modifier.weight(1f)) {
                Text(a.displayName, style = MaterialTheme.typography.titleLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
                Spacer(Modifier.height(4.dp))
                StatusChip(v.label, v.tone)
            }
        }
        if (a.description.isNotBlank()) Text(a.description, style = MaterialTheme.typography.bodyMedium, color = kern.text2, modifier = Modifier.padding(horizontal = 20.dp, vertical = 4.dp))
        if (v.detail.isNotBlank()) Text(v.detail, style = MaterialTheme.typography.bodySmall, color = if (v.tone == AppTone.Bad) kern.danger else kern.text3, modifier = Modifier.padding(horizontal = 20.dp, vertical = 2.dp))

        Column(Modifier.padding(horizontal = 16.dp, vertical = 12.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            KButton("Open in browser", Modifier.fillMaxWidth(), primary = true, icon = Icons.AutoMirrored.Outlined.OpenInNew, onClick = onOpen)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (canStart) {
                    KButton(if (acting == "start") "Starting…" else "Start", Modifier.weight(1f), enabled = acting == null, icon = Icons.Outlined.PlayArrow) { onAction("start") }
                } else {
                    KButton(if (acting == "restart") "Restarting…" else "Restart", Modifier.weight(1f), enabled = acting == null, icon = Icons.Outlined.RestartAlt) { onAction("restart") }
                    KButton(if (acting == "stop") "Stopping…" else "Stop", Modifier.weight(1f), enabled = acting == null, icon = Icons.Outlined.Stop, onClick = onStop)
                }
            }
        }

        Heading("Details")
        Bordered {
            val m = a.metrics
            val rows = buildList {
                add("Address" to appUrl(ws.kern.api.base, a))
                add("Access" to (APP_ACCESS[a.access] ?: a.access))
                if (a.runtime.isNotBlank()) add("Runtime" to a.runtime.replaceFirstChar { it.uppercase() })
                add("Source" to if (a.source == "url") a.gitUrl.ifBlank { "Git URL" } else "Kern repository ${a.repo}".trim())
                if (a.branch.isNotBlank()) add("Branch" to a.branch)
                if (m != null && m.running) {
                    add("Uptime" to appUptime(m.uptime))
                    add("Memory" to bytes(m.rss.toLong()))
                    if (m.restarts > 0) add("Restarts" to m.restarts.toString())
                }
            }
            rows.forEach { (k, value) ->
                Row(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
                    Text(k, style = MaterialTheme.typography.bodyMedium, color = kern.text3, modifier = Modifier.width(88.dp))
                    Text(value, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f), maxLines = 3, overflow = TextOverflow.Ellipsis)
                }
            }
        }

        Heading("Latest deploy")
        a.latest?.let { DeployCard(it) } ?: Text("Not deployed yet.", style = MaterialTheme.typography.bodyMedium, color = kern.text3, modifier = Modifier.padding(horizontal = 20.dp))

        Heading("Log")
        LogBox(log)
    }
}

@Composable
private fun DeployCard(d: AppDeploy) {
    val tone = when (d.status) {
        "live" -> AppTone.Ok
        "failed" -> AppTone.Bad
        "queued", "building", "starting" -> AppTone.Busy
        else -> AppTone.Off
    }
    Bordered {
        Column(Modifier.fillMaxWidth().padding(14.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text("#${d.number}", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                StatusChip(APP_DEPLOY_STATUS[d.status] ?: d.status.replaceFirstChar { it.uppercase() }, tone)
            }
            if (d.subject.isNotBlank()) Text(d.subject, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
            val meta = listOfNotNull(
                (APP_TRIGGERS[d.trigger] ?: d.trigger).ifBlank { null },
                d.short.ifBlank { null },
                d.who.ifBlank { null },
                ago(d.finished ?: d.created).ifBlank { null },
            )
            if (meta.isNotEmpty()) Text(meta.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = kern.text3)
            if (d.error.isNotBlank()) Text(d.error, style = MaterialTheme.typography.bodySmall, color = kern.danger)
        }
    }
}

@Composable
private fun LogBox(log: List<AppLogLine>?) {
    Column(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(kern.codeBg).padding(12.dp)) {
        when {
            log == null -> Text("Couldn't read the log.", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            log.isEmpty() -> Text("Nothing logged yet.", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            else -> SelectionContainer {
                Column(Modifier.horizontalScroll(rememberScrollState())) {
                    for (l in log) {
                        Text(
                            (if (l.time.isNotEmpty()) l.time + "  " else "") + l.text,
                            fontFamily = FontFamily.Monospace, fontSize = 11.5.sp, lineHeight = 16.sp,
                            fontWeight = FontWeight.Normal,
                            color = when (l.mark) { "!" -> kern.danger; "#" -> kern.text3; else -> kern.text },
                        )
                    }
                }
            }
        }
    }
}
