package app.kern.ui.screens

import android.annotation.SuppressLint
import android.webkit.CookieManager
import android.webkit.WebView
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.Refresh
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.LinearProgressIndicator
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.viewinterop.AndroidView
import app.kern.data.WebItem
import androidx.compose.foundation.border
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.outlined.Visibility
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.key
import app.kern.data.Tag
import app.kern.data.WATCH_INTERVALS
import app.kern.data.WATCH_MODES
import app.kern.data.WebChange
import app.kern.data.WebChanges
import app.kern.data.WebMonitor
import app.kern.data.WebVersion
import app.kern.notify.Notifications
import app.kern.ui.components.Dot
import app.kern.ui.components.Pill
import app.kern.ui.components.TextAction
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.ago
import app.kern.ui.doc.KSheet
import app.kern.ui.doc.openUrl
import app.kern.ui.theme.kern
import coil.compose.AsyncImage
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun BookmarksScreen(ws: Workspace, nav: Nav, openAdd: Boolean, prefill: String = "") {
    var items by remember { mutableStateOf<List<WebItem>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var kind by rememberSaveable { mutableStateOf<String?>(null) }
    var show by rememberSaveable { mutableStateOf<String?>(null) }
    var tag by rememberSaveable { mutableStateOf<String?>(null) }
    var q by rememberSaveable { mutableStateOf("") }
    var adding by rememberSaveable { mutableStateOf(openAdd) }
    var refreshing by remember { mutableStateOf(false) }
    var changes by remember { mutableStateOf<WebChanges?>(null) }
    // Tags used on any bookmark seen so far, so the tag filter lists only those.
    var usedTags by remember { mutableStateOf(emptySet<String>()) }
    val allTags by ws.tags.collectAsState()
    val scope = rememberCoroutineScope()
    suspend fun load() {
        try {
            items = ws.kern.web(q.ifBlank { null }, kind, tag, show)
            usedTags = usedTags + items!!.flatMap { it.tags }
            err = null
        } catch (e: Exception) { err = e.message }
        changes = runCatching { ws.kern.webChanges() }.getOrNull()
    }
    LaunchedEffect(kind, q, show, tag) { delay(if (q.isEmpty()) 0 else 250); load() }
    // Keep polling while something is still being saved or downloaded.
    LaunchedEffect(items) {
        if (items?.any { !it.isProcessed || it.videoStatus == "downloading" } == true) { delay(3000); load() }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Bookmarks", onBack = { nav.back() }) {
            IconButton(onClick = { adding = true }) { Icon(Icons.Outlined.Add, "Add bookmark", tint = kern.accent) }
        }
        Box(Modifier.padding(horizontal = 16.dp)) { KField(q, { q = it }, "Search bookmarks") }
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 8.dp)) {
            listOf(null to "All", "web" to "Pages", "video" to "Videos", "image" to "Images").forEach { (k, l) ->
                Box(Modifier.padding(4.dp)) { Choice(l, kind == k) { kind = k } }
            }
            val c = changes
            if (show != null || (c != null && c.watched + c.changed > 0)) {
                Box(Modifier.padding(4.dp)) { Choice("Watching", show == "watched") { show = if (show == "watched") null else "watched" } }
                Box(Modifier.padding(4.dp)) {
                    Choice(if ((c?.changed ?: 0) > 0) "Updated · ${c!!.changed}" else "Updated", show == "changed") { show = if (show == "changed") null else "changed" }
                }
            }
        }
        val tagChoices = allTags.filter { it.id in usedTags || it.id == tag }
        if (tagChoices.isNotEmpty()) Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp).padding(bottom = 6.dp)) {
            tagChoices.forEach { t ->
                Box(Modifier.padding(4.dp)) { Choice("#${t.name}", tag == t.id, kern.named(t.color.ifBlank { "gray" })) { tag = if (tag == t.id) null else t.id } }
            }
        }
        PullToRefreshBox(refreshing, { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.weight(1f)) {
            when {
                items == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
                items == null -> Loading()
                items!!.isEmpty() && (show != null || tag != null) ->
                    EmptyState(Icons.Outlined.Bookmark, "Nothing here", when (show) {
                        "watched" -> "Open a page bookmark and turn on Watch for changes."
                        "changed" -> "No new changes on the pages you watch."
                        else -> "No bookmarks with this tag."
                    })
                items!!.isEmpty() -> EmptyState(Icons.Outlined.Bookmark, "No bookmarks", "Save pages, videos and images — or share a link to Kern from any app.", action = "Add a link" to { adding = true })
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(items!!, key = { it.id }) { w -> WebRow(ws, w, allTags) { nav.go("bookmark/${w.id}") } }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
    if (adding) AddBookmarkSheet(ws, prefill, onDone = { adding = false; scope.launch { load() } })
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun WebRow(ws: Workspace, w: WebItem, allTags: List<Tag>, onClick: () -> Unit) {
    val k = kern
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
        Box(Modifier.size(width = 84.dp, height = 56.dp).clip(RoundedCornerShape(8.dp)).background(k.surface2), contentAlignment = Alignment.Center) {
            if (w.thumbnail.isNotBlank()) AsyncImage(ws.kern.api.abs(w.thumbnail), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
            else Icon(when (w.kind) { "video" -> Icons.Outlined.PlayCircle; "image" -> Icons.Outlined.Image; else -> Icons.Outlined.Language }, null, tint = k.text3)
        }
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(w.title.ifBlank { w.url }, style = MaterialTheme.typography.bodyLarge, maxLines = 2, overflow = TextOverflow.Ellipsis)
            Text(listOfNotNull(host(w.url), w.author.ifBlank { null }, ago(w.createdAt)).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = k.text3, maxLines = 1)
            when {
                w.errorMessage.isNotBlank() -> Text(w.errorMessage, style = MaterialTheme.typography.bodySmall, color = k.danger, maxLines = 1)
                !w.isProcessed -> Text("Saving…", style = MaterialTheme.typography.bodySmall, color = k.accent)
                w.videoStatus == "downloading" -> LinearProgressIndicator({ ((w.videoProgress ?: 0.0) / 100).toFloat() }, Modifier.fillMaxWidth().padding(top = 4.dp), color = k.accent, trackColor = k.surface2)
            }
            val tags = w.tags.mapNotNull { id -> allTags.firstOrNull { it.id == id } }
            val m = w.monitor
            if (tags.isNotEmpty() || m != null) {
                FlowRow(Modifier.padding(top = 4.dp), horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    if (w.unseen > 0) Pill("${w.unseen} new", k.accent)
                    if (m != null && m.priceText.isNotBlank()) Pill(m.priceText, k.green)
                    if (m != null && m.enabled && w.unseen == 0) Pill(if (m.hasError) "Watch failing" else "Watching", if (m.hasError) k.danger else k.text3)
                    tags.forEach { Pill("#${it.name}", k.named(it.color.ifBlank { "gray" })) }
                }
            }
        }
    }
}

private fun host(url: String) = runCatching { android.net.Uri.parse(url).host?.removePrefix("www.") }.getOrNull()

@Composable
fun AddBookmarkSheet(ws: Workspace, prefill: String, onDone: (WebItem?) -> Unit) {
    var url by remember { mutableStateOf(prefill.ifBlank { "" }) }
    var notes by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    fun save() {
        if (url.isBlank()) return
        busy = true
        scope.launch {
            runCatching { ws.kern.addWeb(url.trim(), notes = notes) }
                .onSuccess { snack.show("Saving bookmark…"); onDone(it) }
                .onFailure { snack.error(it); busy = false }
        }
    }
    KSheet({ onDone(null) }, "Save a link") {
        Column(Modifier.padding(horizontal = 16.dp).imePadding(), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            KField(url, { url = it }, "URL", placeholder = "https://…", keyboard = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Done), actions = KeyboardActions(onDone = { save() }))
            KField(notes, { notes = it }, "Notes (optional)", singleLine = false)
            Text("Web pages are saved as a full offline snapshot. Videos can be downloaded from the bookmark.", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            KButton(if (busy) "Saving…" else "Save", Modifier.fillMaxWidth(), primary = true, enabled = !busy && url.isNotBlank()) { save() }
        }
    }
}

@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun SavedPage(ws: Workspace, url: String) {
    // The saved page, scripts off, signed in with the app's session.
    key(url) {
        AndroidView(factory = { c ->
            val cm = CookieManager.getInstance()
            ws.kern.api.cookieJar.loadForRequest(okhttp3.HttpUrl.Builder().scheme(if (url.startsWith("https")) "https" else "http").host(android.net.Uri.parse(url).host ?: "localhost").build())
                .forEach { cm.setCookie(ws.kern.api.base, "${it.name}=${it.value}") }
            WebView(c).apply {
                settings.javaScriptEnabled = false
                settings.loadWithOverviewMode = true
                settings.useWideViewPort = true
                settings.builtInZoomControls = true
                settings.displayZoomControls = false
                loadUrl(url, mapOf("X-Kern" to "1"))
            }
        }, modifier = Modifier.fillMaxSize())
    }
}

@Composable
fun BookmarkScreen(ws: Workspace, nav: Nav, id: Long) {
    var w by remember { mutableStateOf<WebItem?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var notes by remember { mutableStateOf<String?>(null) }
    // The page shown full screen: the saved copy or a version from the history.
    var page by remember { mutableStateOf<Pair<String, String>?>(null) }
    var versions by remember { mutableStateOf<List<WebVersion>?>(null) }
    // The change was new when the bookmark was opened (it is marked seen straight away).
    var freshChange by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val k = kern
    suspend fun loadVersions() { versions = runCatching { ws.kern.webVersions(id) }.getOrNull() ?: versions }
    suspend fun load() {
        try {
            val item = ws.kern.webItem(id)
            w = item
            if (notes == null) notes = item.notes
            err = null
            if (item.unseen > 0) {
                freshChange = true
                Notifications.cancel(ctx, Notifications.webId(id))
                runCatching { w = ws.kern.updateWeb(id, "seen" to true) }
            }
        } catch (e: Exception) { err = e.message }
    }
    LaunchedEffect(id) { load(); loadVersions() }
    LaunchedEffect(w) { if (w != null && (!w!!.isProcessed || w!!.videoStatus == "downloading")) { delay(3000); load() } }
    LaunchedEffect(notes) {
        val n = notes ?: return@LaunchedEffect
        if (w == null || n == w!!.notes) return@LaunchedEffect
        delay(800)
        runCatching { w = ws.kern.updateWeb(id, "notes" to n) }
    }

    Column(Modifier.fillMaxSize().background(k.bg).statusBarsPadding()) {
        KTopBar(page?.second ?: w?.title?.ifBlank { null } ?: "Bookmark", onBack = { if (page != null) page = null else nav.back() }, subtitle = w?.url?.let { host(it) }) {
            w?.let { item ->
                IconButton(onClick = { openUrl(ctx, item.url) }) { Icon(Icons.AutoMirrored.Outlined.OpenInNew, "Open original") }
                IconButton(onClick = {
                    ctx.startActivity(android.content.Intent.createChooser(android.content.Intent(android.content.Intent.ACTION_SEND).setType("text/plain").putExtra(android.content.Intent.EXTRA_TEXT, item.url), "Share link"))
                }) { Icon(Icons.Outlined.Share, "Share") }
            }
        }
        val item = w
        when {
            item == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
            item == null -> Loading()
            page != null -> SavedPage(ws, page!!.first)
            else -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
                if (item.thumbnail.isNotBlank()) AsyncImage(ws.kern.api.abs(item.thumbnail), null, contentScale = ContentScale.Crop,
                    modifier = Modifier.fillMaxWidth().aspectRatio(16f / 9).clip(RoundedCornerShape(12.dp)).background(k.surface2).clickable {
                        item.videoUrl?.let { openUrl(ctx, ws.kern.api.abs(it)!!) } ?: openUrl(ctx, item.url)
                    })
                Text(item.title.ifBlank { item.url }, style = MaterialTheme.typography.headlineSmall)
                if (item.author.isNotBlank()) Text(item.author, style = MaterialTheme.typography.bodyMedium, color = k.text2)
                if (item.description.isNotBlank()) Text(item.description, style = MaterialTheme.typography.bodyMedium, color = k.text2)
                if (item.errorMessage.isNotBlank()) Text(item.errorMessage, color = k.danger, style = MaterialTheme.typography.bodyMedium)
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    if (item.hasSnapshot) KButton("Read saved copy", primary = true, icon = Icons.Outlined.Language) { page = ws.kern.api.base + "/api/web/${item.id}/snapshot" to (item.title.ifBlank { "Saved copy" }) }
                    if (item.videoUrl != null) KButton("Play video", primary = !item.hasSnapshot, icon = Icons.Outlined.PlayCircle) { openUrl(ctx, ws.kern.api.abs(item.videoUrl)!!) }
                    else if (item.kind == "video" && item.videoStatus != "downloading") KButton("Download video") {
                        scope.launch { runCatching { ws.kern.api.post<WebItem>("/web/${item.id}/download-video", app.kern.data.jsonOf("format" to "best")) }.onSuccess { w = it; snack.show("Downloading…") }.onFailure { snack.error(it) } }
                    }
                }
                if (item.videoStatus == "downloading") LinearProgressIndicator({ ((item.videoProgress ?: 0.0) / 100).toFloat() }, Modifier.fillMaxWidth(), color = k.accent, trackColor = k.surface2)
                BookmarkTags(ws, item) { w = it }
                if (item.canWatch) item.monitor?.let { m ->
                    WatchSection(ws, item, m, freshChange, onUpdate = { w = it; scope.launch { loadVersions() } })
                }
                KField(notes ?: "", { notes = it }, "Notes", singleLine = false, minLines = 3)
                if (item.todos.isNotEmpty()) {
                    Text("TO-DO", style = MaterialTheme.typography.labelSmall, color = k.text3)
                    item.todos.forEachIndexed { i, t ->
                        Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.fillMaxWidth().clickable {
                            val next = item.todos.mapIndexed { j, x -> if (j == i) x.copy(done = !x.done) else x }
                            scope.launch { runCatching { w = ws.kern.updateWeb(id, "todos" to next.map { mapOf("text" to it.text, "done" to it.done) }) } }
                        }) {
                            TaskCheck(t.done, 0) {}
                            Text(t.text, textDecoration = if (t.done) TextDecoration.LineThrough else null, color = if (t.done) k.text3 else k.text)
                        }
                    }
                }
                if (item.canWatch || !versions.isNullOrEmpty()) VersionHistory(ws, item, versions,
                    onSaved = { scope.launch { loadVersions(); load() } },
                    onOpen = { v -> page = ws.kern.webVersionPage(id, v.id) to (ago(v.createdAt).ifBlank { "Version" } + " · " + v.triggerLabel) })
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KButton("Refresh", icon = Icons.Outlined.Refresh) { scope.launch { runCatching { w = ws.kern.refreshWeb(id) }.onSuccess { snack.show("Capturing again…"); loadVersions() }.onFailure { snack.error(it) } } }
                    KButton("Delete", icon = Icons.Outlined.Delete) { scope.launch { runCatching { ws.kern.deleteWeb(id) }.onSuccess { nav.back() }.onFailure { snack.error(it) } } }
                }
            }
        }
    }
}

/** The bookmark's tags: tap one to add or remove it, or type a new one. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun BookmarkTags(ws: Workspace, item: WebItem, onUpdate: (WebItem) -> Unit) {
    val allTags by ws.tags.collectAsState()
    var editing by remember { mutableStateOf(false) }
    var newTag by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val k = kern
    fun setTags(ids: List<String>) = scope.launch { runCatching { onUpdate(ws.kern.updateWeb(item.id, "tags" to ids)) }.onFailure { snack.error(it) } }
    val mine = item.tags.mapNotNull { id -> allTags.firstOrNull { it.id == id } }
    Row(verticalAlignment = Alignment.CenterVertically) {
        Text("TAGS", style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.weight(1f))
        TextAction(if (editing) "Done" else if (mine.isEmpty()) "Add tag" else "Edit") { editing = !editing }
    }
    if (!editing) {
        if (mine.isEmpty()) Text("No tags", style = MaterialTheme.typography.bodySmall, color = k.text3)
        else FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            mine.forEach { Pill("#${it.name}", k.named(it.color.ifBlank { "gray" })) }
        }
        return
    }
    FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
        for (tag in allTags.sortedByDescending { it.id in item.tags }.take(30)) {
            val on = tag.id in item.tags
            Choice("#${tag.name}", on, k.named(tag.color.ifBlank { "gray" })) { setTags(if (on) item.tags - tag.id else item.tags + tag.id) }
        }
    }
    KField(newTag, { newTag = it.trimStart('#') }, "New tag", keyboard = KeyboardOptions(imeAction = ImeAction.Done),
        actions = KeyboardActions(onDone = {
            val name = newTag.trim(); if (name.isEmpty()) return@KeyboardActions
            newTag = ""
            scope.launch { runCatching { val t = ws.ensureTag(name); if (t.id !in item.tags) onUpdate(ws.kern.updateWeb(item.id, "tags" to item.tags + t.id)) }.onFailure { snack.error(it) } }
        }))
}

/** Watch for changes: on/off, what and how often, "Check now" and the last change found. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun WatchSection(ws: Workspace, item: WebItem, m: WebMonitor, fresh: Boolean, onUpdate: (WebItem) -> Unit) {
    var busy by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val k = kern
    fun run(call: suspend () -> WebItem, done: (WebItem) -> Unit = {}) = scope.launch {
        busy = true
        runCatching { call() }.onSuccess { onUpdate(it); done(it) }.onFailure { snack.error(it) }
        busy = false
    }
    fun patch(vararg f: Pair<String, Any?>) = run({ ws.kern.updateWeb(item.id, *f) })
    val shape = RoundedCornerShape(12.dp)
    Column(Modifier.fillMaxWidth().clip(shape).background(k.surface)
        .border(1.dp, if (m.enabled) k.accent.copy(alpha = 0.4f) else k.border, shape).padding(12.dp),
        verticalArrangement = Arrangement.spacedBy(10.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Icon(Icons.Outlined.Visibility, null, tint = if (m.enabled) k.accent else k.text3, modifier = Modifier.size(18.dp))
            Spacer(Modifier.width(8.dp))
            Text("Watch for changes", style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            if (busy) CircularProgressIndicator(Modifier.size(16.dp).padding(end = 4.dp), color = k.accent, strokeWidth = 2.dp)
            Switch(m.enabled, { on -> patch("monitor_enabled" to on) }, enabled = !busy,
                colors = SwitchDefaults.colors(checkedTrackColor = k.accent, checkedThumbColor = k.onAccent))
        }
        if (!m.enabled) {
            Text("Kern fetches the page on a schedule and flags new posts, price changes or edits, saving each version to the history.",
                style = MaterialTheme.typography.bodySmall, color = k.text3)
            return@Column
        }
        Text("WATCH", style = MaterialTheme.typography.labelSmall, color = k.text3)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            WATCH_MODES.forEach { (v, l) -> Choice(l, m.mode == v) { if (!busy && m.mode != v) patch("monitor_mode" to v) } }
        }
        Text("HOW OFTEN", style = MaterialTheme.typography.labelSmall, color = k.text3)
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            WATCH_INTERVALS.forEach { (v, l) -> Choice(l, m.interval == v) { if (!busy && m.interval != v) patch("monitor_interval" to v) } }
            if (WATCH_INTERVALS.none { it.first == m.interval }) Choice("Every ${m.interval} min", true) {}
        }
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("Save a snapshot to history on every change", style = MaterialTheme.typography.bodySmall, color = k.text2, modifier = Modifier.weight(1f))
            Switch(m.archive, { on -> patch("monitor_archive" to on) }, enabled = !busy,
                colors = SwitchDefaults.colors(checkedTrackColor = k.accent, checkedThumbColor = k.onAccent))
        }
        val status = listOfNotNull(
            m.resolvedMode.takeIf { it.isNotBlank() }?.let { r -> "Watching " + mapOf("posts" to "new posts", "price" to "the price", "content" to "any change")[r] + if (m.mode == "auto") " (automatic)" else "" },
            m.lastCheckedAt?.let { "checked ${ago(it)}" },
        ).joinToString(" · ")
        if (status.isNotBlank()) Text(status, style = MaterialTheme.typography.bodySmall, color = k.text3)
        if (m.feedUrl.isNotBlank()) Text("Feed: " + m.feedUrl.substringAfter("://").removePrefix("www."), style = MaterialTheme.typography.bodySmall, color = k.text3, maxLines = 1, overflow = TextOverflow.Ellipsis)
        if (m.errorText.isNotBlank()) Text(m.errorText, style = MaterialTheme.typography.bodySmall, color = k.danger)

        val lc = m.lastChange
        if (m.watching == "price" && m.priceText.isNotBlank()) Row(verticalAlignment = Alignment.CenterVertically) {
            Text(m.priceText, style = MaterialTheme.typography.titleLarge)
            if (lc is WebChange.Price) Text((if (lc.dropped) "  ↓ was " else "  ↑ was ") + lc.old, style = MaterialTheme.typography.bodyMedium, color = if (lc.dropped) k.green else k.red)
        }
        if (lc != null) {
            val cs = RoundedCornerShape(8.dp)
            Column(Modifier.fillMaxWidth().clip(cs).background(k.surface2).border(1.dp, if (fresh) k.accent else k.border, cs).padding(10.dp),
                verticalArrangement = Arrangement.spacedBy(4.dp)) {
                Text(listOfNotNull(lc.text, lc.at?.let { ago(it) }?.ifBlank { null }).joinToString(" · "), style = MaterialTheme.typography.labelLarge)
                when (lc) {
                    is WebChange.Posts -> lc.added.take(6).forEach { p ->
                        Text("• " + p.title.ifBlank { p.url }, style = MaterialTheme.typography.bodySmall, color = if (p.url.isNotBlank()) k.accent else k.text2,
                            maxLines = 2, overflow = TextOverflow.Ellipsis,
                            modifier = if (p.url.isNotBlank()) Modifier.clickable { openUrl(ctx, p.url) } else Modifier)
                    }
                    is WebChange.Content -> lc.snippets.forEach { Text("+ $it", style = MaterialTheme.typography.bodySmall, color = k.text2, maxLines = 3, overflow = TextOverflow.Ellipsis) }
                    is WebChange.Price -> {}
                }
            }
        } else if (m.watching == "posts" && m.latest.isNotEmpty()) {
            Text("Latest on the page", style = MaterialTheme.typography.labelMedium, color = k.text3)
            m.latest.take(5).forEach { p ->
                Text("• " + p.title.ifBlank { p.url }, style = MaterialTheme.typography.bodySmall, color = if (p.url.isNotBlank()) k.accent else k.text2,
                    maxLines = 2, overflow = TextOverflow.Ellipsis,
                    modifier = if (p.url.isNotBlank()) Modifier.clickable { openUrl(ctx, p.url) } else Modifier)
            }
        }
        KButton(if (busy) "Checking…" else "Check now", icon = Icons.Outlined.Refresh, enabled = !busy) {
            val before = m.unseen
            run({ ws.kern.checkWeb(item.id) }) { d ->
                val dm = d.monitor
                snack.show(when {
                    dm == null -> "Checked"
                    dm.errorText.isNotBlank() -> dm.errorText
                    dm.unseen > before -> dm.lastChange?.text ?: "Found a change"
                    else -> "No changes since the last check"
                })
            }
        }
    }
}

/** Saved versions, newest first; tap one with a saved page to view it. */
@Composable
private fun VersionHistory(ws: Workspace, item: WebItem, versions: List<WebVersion>?, onSaved: () -> Unit, onOpen: (WebVersion) -> Unit) {
    var saving by remember { mutableStateOf(false) }
    var all by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val k = kern
    Row(verticalAlignment = Alignment.CenterVertically) {
        Icon(Icons.Outlined.History, null, tint = k.text3, modifier = Modifier.size(16.dp))
        Spacer(Modifier.width(6.dp))
        Text("HISTORY" + (versions?.size?.takeIf { it > 0 }?.let { " · $it" } ?: ""), style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.weight(1f))
        if (item.canWatch) TextAction(if (saving) "Saving…" else "Save snapshot") {
            if (saving) return@TextAction
            saving = true
            scope.launch {
                runCatching { ws.kern.saveWebVersion(item.id) }.onSuccess { snack.show("Snapshot saved to history"); onSaved() }.onFailure { snack.error(it) }
                saving = false
            }
        }
    }
    when {
        versions == null -> Text("Loading…", style = MaterialTheme.typography.bodySmall, color = k.text3)
        versions.isEmpty() -> Text("No saved versions yet. Save a snapshot, or watch the page to keep one each time it changes.", style = MaterialTheme.typography.bodySmall, color = k.text3)
        else -> {
            val shown = if (all) versions else versions.take(8)
            shown.forEach { v ->
                Row(Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).then(if (v.hasPage) Modifier.clickable { onOpen(v) } else Modifier).padding(vertical = 6.dp),
                    verticalAlignment = Alignment.CenterVertically) {
                    Dot(if (v.trigger == "change") k.accent else k.text3)
                    Spacer(Modifier.width(10.dp))
                    Column(Modifier.weight(1f)) {
                        Text(ago(v.createdAt).ifBlank { "Version ${v.id}" }, style = MaterialTheme.typography.bodyMedium, color = if (v.hasPage) k.text else k.text3)
                        val detail = listOfNotNull(v.triggerLabel, v.change?.text, v.price.ifBlank { null }).joinToString(" · ")
                        Text(detail, style = MaterialTheme.typography.bodySmall, color = k.text3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        (v.change as? WebChange.Posts)?.added?.mapNotNull { it.title.ifBlank { null } }?.take(3)?.takeIf { it.isNotEmpty() }?.let {
                            Text(it.joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = k.text2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                    if (v.hasPage) Icon(Icons.Outlined.Language, "View this version", tint = k.text3, modifier = Modifier.size(18.dp))
                }
            }
            if (versions.size > shown.size) TextAction("Show all ${versions.size}") { all = true }
        }
    }
}
