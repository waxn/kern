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
    var q by rememberSaveable { mutableStateOf("") }
    var adding by rememberSaveable { mutableStateOf(openAdd) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    suspend fun load() { try { items = ws.kern.web(q.ifBlank { null }, kind); err = null } catch (e: Exception) { err = e.message } }
    LaunchedEffect(kind, q) { delay(if (q.isEmpty()) 0 else 250); load() }
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
        }
        PullToRefreshBox(refreshing, { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.weight(1f)) {
            when {
                items == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
                items == null -> Loading()
                items!!.isEmpty() -> EmptyState(Icons.Outlined.Bookmark, "No bookmarks", "Save pages, videos and images — or share a link to Kern from any app.", action = "Add a link" to { adding = true })
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    items(items!!, key = { it.id }) { w -> WebRow(ws, w) { nav.go("bookmark/${w.id}") } }
                    item { Spacer(Modifier.height(24.dp)) }
                }
            }
        }
    }
    if (adding) AddBookmarkSheet(ws, prefill, onDone = { adding = false; scope.launch { load() } })
}

@Composable
private fun WebRow(ws: Workspace, w: WebItem, onClick: () -> Unit) {
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
fun BookmarkScreen(ws: Workspace, nav: Nav, id: Long) {
    var w by remember { mutableStateOf<WebItem?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var notes by remember { mutableStateOf<String?>(null) }
    var reading by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val k = kern
    suspend fun load() { try { w = ws.kern.webItem(id); if (notes == null) notes = w!!.notes; err = null } catch (e: Exception) { err = e.message } }
    LaunchedEffect(id) { load() }
    LaunchedEffect(w) { if (w != null && (!w!!.isProcessed || w!!.videoStatus == "downloading")) { delay(3000); load() } }
    LaunchedEffect(notes) {
        val n = notes ?: return@LaunchedEffect
        if (w == null || n == w!!.notes) return@LaunchedEffect
        delay(800)
        runCatching { w = ws.kern.updateWeb(id, "notes" to n) }
    }

    Column(Modifier.fillMaxSize().background(k.bg).statusBarsPadding()) {
        KTopBar(w?.title?.ifBlank { null } ?: "Bookmark", onBack = { if (reading) reading = false else nav.back() }, subtitle = w?.url?.let { host(it) }) {
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
            reading -> {
                // The saved snapshot, scripts off, signed in with the app's session.
                val url = ws.kern.api.base + "/api/web/${item.id}/snapshot"
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
                    if (item.hasSnapshot) KButton("Read saved copy", primary = true, icon = Icons.Outlined.Language) { reading = true }
                    if (item.videoUrl != null) KButton("Play video", primary = !item.hasSnapshot, icon = Icons.Outlined.PlayCircle) { openUrl(ctx, ws.kern.api.abs(item.videoUrl)!!) }
                    else if (item.kind == "video" && item.videoStatus != "downloading") KButton("Download video") {
                        scope.launch { runCatching { ws.kern.api.post<WebItem>("/web/${item.id}/download-video", app.kern.data.jsonOf("format" to "best")) }.onSuccess { w = it; snack.show("Downloading…") }.onFailure { snack.error(it) } }
                    }
                }
                if (item.videoStatus == "downloading") LinearProgressIndicator({ ((item.videoProgress ?: 0.0) / 100).toFloat() }, Modifier.fillMaxWidth(), color = k.accent, trackColor = k.surface2)
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
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KButton("Refresh", icon = Icons.Outlined.Refresh) { scope.launch { runCatching { w = ws.kern.refreshWeb(id) }.onSuccess { snack.show("Capturing again…") }.onFailure { snack.error(it) } } }
                    KButton("Delete", icon = Icons.Outlined.Delete) { scope.launch { runCatching { ws.kern.deleteWeb(id) }.onSuccess { nav.back() }.onFailure { snack.error(it) } } }
                }
            }
        }
    }
}
