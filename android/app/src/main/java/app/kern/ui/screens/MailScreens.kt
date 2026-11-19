package app.kern.ui.screens

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.Forward
import androidx.compose.material.icons.automirrored.outlined.Reply
import androidx.compose.material.icons.automirrored.outlined.ReplyAll
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.Email
import androidx.compose.material.icons.outlined.Lock
import androidx.compose.material.icons.outlined.MarkEmailUnread
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Snooze
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.StarBorder
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material.icons.outlined.WarningAmber
import androidx.compose.material3.Checkbox
import androidx.compose.material3.CheckboxDefaults
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.key
import androidx.compose.runtime.mutableStateListOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.graphics.toArgb
import androidx.compose.ui.viewinterop.AndroidView
import app.kern.data.ApiError
import app.kern.data.MailAddr
import app.kern.data.MailBody
import app.kern.data.MailFolder
import app.kern.data.MailMessage
import app.kern.data.MailStatus
import app.kern.data.MailThread
import app.kern.data.MailThreadDetail
import app.kern.data.str
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.KTopBar
import app.kern.ui.components.Loading
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Pill
import app.kern.ui.components.ago
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalTime
import java.time.ZonedDateTime

// Mail in the Android app: the inbox and folders, a conversation, and writing.
// Setting up the account (and two-factor sign-in, which mail needs) happens in
// Kern's web app: Settings → Account and Settings → Mail.

private val ROLE_ORDER = listOf("inbox", "starred", "snoozed", "drafts", "sent", "archive", "all", "junk", "trash")

/** Shown instead of mail when something is missing. Null when mail can be used. */
@Composable
private fun MailGate(ws: Workspace, status: MailStatus): Boolean {
    val tf = status.twoFactor
    when {
        !tf.enabled -> EmptyState(Icons.Outlined.Lock, "Mail needs two-factor sign-in",
            "Turn it on in Kern's web app (Settings → Account), then sign out here and back in with your code.")
        !tf.sessionVerified -> EmptyState(Icons.Outlined.Lock, "Sign in again with your code",
            "This phone signed in with your password only. Sign out and back in with the code from your authenticator app.",
            action = "Sign out" to { ws.logout(); Unit })
        !status.allowed && !status.connected -> EmptyState(Icons.Outlined.Email, "Mail is turned off", "An administrator has turned mail off on this server.")
        !status.connected && status.account?.str("address").isNullOrBlank() -> EmptyState(Icons.Outlined.Email, "Connect your mailbox",
            "Add your mail account in Kern's web app: Settings → Mail. It shows up here right after.")
        else -> return false
    }
    return true
}

private fun who(t: MailThread, me: String): String {
    val others = t.participants.filter { !it.addr.equals(me, ignoreCase = true) }.ifEmpty { t.participants }
    val names = others.map { it.name.ifBlank { it.addr.substringBefore('@') }.substringBefore(' ') }.distinct()
    return when {
        names.isEmpty() -> "(nobody)"
        names.size <= 2 -> names.joinToString(", ")
        else -> "${names.first()} … ${names.last()}"
    }
}

private fun shortWhen(iso: String?): String {
    val d = runCatching { ZonedDateTime.parse(iso).withZoneSameInstant(java.time.ZoneId.systemDefault()) }.getOrNull() ?: return ""
    val today = LocalDate.now()
    return when {
        d.toLocalDate() == today -> "%02d:%02d".format(d.hour, d.minute)
        d.year == today.year -> "${d.dayOfMonth} ${d.month.name.take(3).lowercase().replaceFirstChar { it.uppercase() }}"
        else -> d.toLocalDate().toString()
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MailScreen(ws: Workspace, nav: Nav, initialView: String? = null) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var status by remember { mutableStateOf<MailStatus?>(null) }
    var folders by remember { mutableStateOf<List<MailFolder>>(emptyList()) }
    var view by remember { mutableStateOf(initialView ?: "inbox") }
    var query by remember { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    val threads = remember { mutableStateListOf<MailThread>() }
    var next by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    val me = status?.account?.str("address") ?: ""

    fun apiView(v: String): String {
        if (v == "starred" || v == "all") return v
        val f = folders.firstOrNull { it.role == v } ?: folders.firstOrNull { "f${it.id}" == v }
        return if (f != null) "folder:${f.id}" else "all"
    }
    suspend fun load(more: Boolean = false) {
        try {
            if (folders.isEmpty()) folders = ws.kern.mailFolders().folders
            val r = ws.kern.mailThreads(apiView(view), q = query.takeIf { searching && it.isNotBlank() }, cursor = if (more) next else null)
            if (!more) threads.clear()
            threads.addAll(r.threads)
            next = r.next
            error = null
        } catch (e: ApiError) {
            if (e.status == 403) status = runCatching { ws.kern.mailStatus() }.getOrNull() ?: status
            else error = e.message
        } catch (e: Exception) {
            error = e.message
        } finally {
            loading = false
        }
    }
    LaunchedEffect(Unit) {
        status = runCatching { ws.kern.mailStatus() }.getOrElse { error = it.message; null }
    }
    LaunchedEffect(status, view) {
        val s = status ?: return@LaunchedEffect
        if (s.twoFactor.enabled && s.twoFactor.sessionVerified && (s.connected || !s.account?.str("address").isNullOrBlank())) {
            loading = true
            load()
        }
    }

    val title = when (view) {
        "starred" -> "Starred"
        "all" -> "All mail"
        else -> folders.firstOrNull { it.role == view || "f${it.id}" == view }?.displayName ?: "Inbox"
    }

    Box(Modifier.fillMaxSize().background(kern.bg)) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            if (searching) {
                Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 6.dp), verticalAlignment = Alignment.CenterVertically) {
                    KField(query, { query = it }, "Search mail", modifier = Modifier.weight(1f),
                        keyboard = KeyboardOptions(imeAction = androidx.compose.ui.text.input.ImeAction.Search),
                        actions = androidx.compose.foundation.text.KeyboardActions(onSearch = { scope.launch { loading = true; load() } }))
                    IconButton(onClick = { searching = false; query = ""; scope.launch { load() } }) { Icon(Icons.Outlined.Close, "Close search") }
                }
            } else {
                KTopBar(title, onBack = { nav.back() }, subtitle = me.ifBlank { null }) {
                    IconButton(onClick = { searching = true }) { Icon(Icons.Outlined.Search, "Search", tint = kern.text2) }
                }
            }
            val s = status
            when {
                s == null && error == null -> Loading()
                s == null -> ErrorState(error ?: "") { scope.launch { status = runCatching { ws.kern.mailStatus() }.getOrNull() } }
                MailGate(ws, s) -> {}
                else -> {
                    if (!searching) {
                        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp),
                            horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                            val chips = ROLE_ORDER.mapNotNull { r ->
                                when (r) {
                                    "starred" -> "starred" to "Starred"
                                    "all" -> "all" to "All mail"
                                    else -> folders.firstOrNull { it.role == r }?.let { f -> r to (f.displayName + if (f.unread > 0 && r == "inbox") " ${f.unread}" else "") }
                                }
                            } + folders.filter { it.role.isBlank() }.map { "f${it.id}" to it.displayName }
                            chips.forEach { (v, label) ->
                                Pill(label, if (v == view) kern.accent else kern.text2, onClick = { view = v })
                            }
                        }
                    }
                    PullToRefreshBox(
                        isRefreshing = refreshing,
                        onRefresh = { scope.launch { refreshing = true; folders = emptyList(); load(); refreshing = false } },
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        when {
                            loading && threads.isEmpty() -> Loading()
                            error != null && threads.isEmpty() -> ErrorState(error!!) { scope.launch { loading = true; load() } }
                            threads.isEmpty() -> EmptyState(Icons.Outlined.Email, if (searching) "No matches" else "Nothing here", null)
                            else -> LazyColumn(Modifier.fillMaxSize()) {
                                items(threads, key = { it.id }) { t -> ThreadRow(t, me) { nav.go("mail/thread/${t.id}") } }
                                if (next != null) item {
                                    LaunchedEffect(next) { load(more = true) }
                                    Loading(Modifier.height(64.dp))
                                }
                                item { Spacer(Modifier.height(88.dp)) }
                            }
                        }
                    }
                }
            }
        }
        if (status?.let { it.twoFactor.sessionVerified && it.connected } == true) {
            FloatingActionButton(
                onClick = { nav.go("mail/compose") },
                containerColor = kern.accent, contentColor = kern.onAccent,
                modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp),
            ) { Icon(Icons.Outlined.Edit, "Write") }
        }
    }
}

@Composable
private fun ThreadRow(t: MailThread, me: String, onClick: () -> Unit) {
    val unread = t.unread > 0
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
        Box(Modifier.padding(top = 7.dp).size(7.dp).background(if (unread) kern.accent else androidx.compose.ui.graphics.Color.Transparent, androidx.compose.foundation.shape.CircleShape))
        Spacer(Modifier.width(10.dp))
        Column(Modifier.weight(1f)) {
            Row(verticalAlignment = Alignment.CenterVertically) {
                Text(who(t, me) + if (t.count > 1) "  ${t.count}" else "", maxLines = 1, overflow = TextOverflow.Ellipsis,
                    fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                if (t.risk == "high" || t.risk == "medium") Icon(Icons.Outlined.WarningAmber, "Possible phishing", tint = kern.danger, modifier = Modifier.size(15.dp))
                if (t.starred) Icon(Icons.Outlined.Star, "Starred", tint = kern.yellow, modifier = Modifier.size(15.dp))
                Spacer(Modifier.width(6.dp))
                Text(shortWhen(t.lastDate), style = MaterialTheme.typography.bodySmall, color = if (unread) kern.accent else kern.text3)
            }
            Text(t.subject.ifBlank { "(no subject)" }, maxLines = 1, overflow = TextOverflow.Ellipsis,
                fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal, style = MaterialTheme.typography.bodyMedium, color = kern.text)
            Text(t.snippet, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
    }
}

@Composable
fun MailThreadScreen(ws: Workspace, nav: Nav, id: Long) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var detail by remember { mutableStateOf<MailThreadDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var menu by remember { mutableStateOf(false) }
    val open = remember { mutableStateListOf<Long>() }

    suspend fun load() {
        try {
            val d = ws.kern.mailThread(id)
            if (detail == null) {
                open.clear()
                open.addAll(d.messages.filter { !it.seen }.map { it.id })
                d.messages.lastOrNull()?.let { if (it.id !in open) open.add(it.id) }
            }
            detail = d
            if (d.thread.unread > 0) runCatching { ws.kern.mailAction(listOf(id), "read") }
        } catch (e: Exception) {
            error = e.message
        }
    }
    LaunchedEffect(id) { load() }

    fun act(action: String, done: String, vararg extra: Pair<String, Any?>) = scope.launch {
        try {
            ws.kern.mailAction(listOf(id), action, *extra)
            snack.show(done)
            if (action in setOf("archive", "trash", "snooze", "spam")) nav.back() else load()
        } catch (e: Exception) { snack.error(e) }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        val t = detail?.thread
        KTopBar("", onBack = { nav.back() }) {
            if (t != null) {
                IconButton(onClick = { act("archive", "Archived") }) { Icon(Icons.Outlined.Archive, "Archive", tint = kern.text2) }
                IconButton(onClick = { act("trash", "Moved to Trash") }) { Icon(Icons.Outlined.Delete, "Trash", tint = kern.text2) }
                IconButton(onClick = { act(if (t.starred) "unstar" else "star", if (t.starred) "Unstarred" else "Starred") }) {
                    Icon(if (t.starred) Icons.Outlined.Star else Icons.Outlined.StarBorder, if (t.starred) "Unstar" else "Star", tint = if (t.starred) kern.yellow else kern.text2)
                }
                Box {
                    IconButton(onClick = { menu = true }) { Icon(Icons.Outlined.MoreVert, "More", tint = kern.text2) }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Mark unread") }, leadingIcon = { Icon(Icons.Outlined.MarkEmailUnread, null) },
                            onClick = { menu = false; scope.launch { runCatching { ws.kern.mailAction(listOf(id), "unread") }; nav.back() } })
                        DropdownMenuItem(text = { Text("Snooze until tomorrow 8:00") }, leadingIcon = { Icon(Icons.Outlined.Snooze, null) },
                            onClick = {
                                menu = false
                                val at = LocalDate.now().plusDays(1).atTime(LocalTime.of(8, 0)).atZone(java.time.ZoneId.systemDefault()).toOffsetDateTime().toString()
                                act("snooze", "Snoozed until tomorrow", "until" to at)
                            })
                        DropdownMenuItem(text = { Text("Make a task for tomorrow") }, leadingIcon = { Icon(Icons.Outlined.TaskAlt, null) },
                            onClick = {
                                menu = false
                                scope.launch {
                                    try {
                                        ws.kern.mailTask(id, t.subject, LocalDate.now().plusDays(1).toString())
                                        snack.show("Task created")
                                        load()
                                    } catch (e: Exception) { snack.error(e) }
                                }
                            })
                        DropdownMenuItem(text = { Text("Report spam") }, leadingIcon = { Icon(Icons.Outlined.WarningAmber, null) },
                            onClick = { menu = false; act("spam", "Moved to Junk") })
                    }
                }
            }
        }
        val d = detail
        when {
            d == null && error == null -> Loading()
            d == null -> ErrorState(error!!) { scope.launch { error = null; load() } }
            else -> LazyColumn(Modifier.fillMaxSize()) {
                item {
                    Text(d.thread.subject.ifBlank { "(no subject)" }, style = MaterialTheme.typography.headlineSmall, color = kern.text,
                        modifier = Modifier.padding(start = 20.dp, end = 20.dp, bottom = 8.dp))
                }
                val risky = d.messages.firstOrNull { it.risk.level == "high" || it.risk.level == "medium" }
                if (risky != null) item {
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 4.dp).fillMaxWidth()
                        .background(kern.tint(kern.danger), androidx.compose.foundation.shape.RoundedCornerShape(10.dp)).padding(12.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Outlined.WarningAmber, null, tint = kern.danger)
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(if (risky.risk.level == "high") "This looks like phishing" else "Be careful with this message",
                                fontWeight = FontWeight.SemiBold, color = kern.danger, style = MaterialTheme.typography.bodyMedium)
                            risky.risk.findings.take(2).forEach { f ->
                                Text(f.str("title") ?: f.str("rule") ?: "", style = MaterialTheme.typography.bodySmall, color = kern.text2)
                            }
                        }
                    }
                }
                items(d.tasks.filter { it.source?.kind == "mail" }, key = { "task-" + it.id }) { task ->
                    Row(Modifier.padding(horizontal = 16.dp, vertical = 2.dp).fillMaxWidth().clickable { nav.go("tasks?task=${task.id}") },
                        verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(task.done, onCheckedChange = { done ->
                            scope.launch { runCatching { ws.kern.updateTask(task.id, "done" to done) }; load() }
                        }, colors = CheckboxDefaults.colors(checkedColor = kern.accent))
                        Text(task.title + (task.due?.let { " · due ${app.kern.ui.components.dueLabel(it)}" } ?: ""),
                            style = MaterialTheme.typography.bodyMedium, color = if (task.done) kern.text3 else kern.text)
                    }
                }
                items(d.messages, key = { it.id }) { m ->
                    MessageItem(ws, m, expanded = m.id in open) { if (m.id in open) open.remove(m.id) else open.add(m.id) }
                }
                item {
                    val last = d.messages.lastOrNull()
                    if (last != null) Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        KButton("Reply", icon = Icons.AutoMirrored.Outlined.Reply) { nav.go("mail/compose?msg=${last.id}&mode=reply") }
                        KButton("All", icon = Icons.AutoMirrored.Outlined.ReplyAll) { nav.go("mail/compose?msg=${last.id}&mode=reply_all") }
                        KButton("Forward", icon = Icons.AutoMirrored.Outlined.Forward) { nav.go("mail/compose?msg=${last.id}&mode=forward") }
                    }
                }
                item { Spacer(Modifier.height(32.dp)) }
            }
        }
    }
}

@Composable
private fun MessageItem(ws: Workspace, m: MailMessage, expanded: Boolean, onToggle: () -> Unit) {
    var body by remember(m.id) { mutableStateOf<MailBody?>(null) }
    var failed by remember(m.id) { mutableStateOf(false) }
    LaunchedEffect(m.id, expanded) {
        if (expanded && body == null) body = runCatching { ws.kern.mailBody(m.id) }.getOrElse { failed = true; null }
    }
    Column(Modifier.padding(horizontal = 12.dp, vertical = 4.dp).fillMaxWidth()
        .background(kern.surface, androidx.compose.foundation.shape.RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(if (m.fromMe) "Me" else m.from.label, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodyMedium)
                Text(if (expanded) "to " + (m.to + m.cc).joinToString(", ") { it.label }.ifBlank { "(no recipients)" } else m.snippet,
                    maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
            }
            Text(ago(m.date), style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
        if (expanded) {
            val b = body
            when {
                failed -> Text("Couldn't load this message.", color = kern.danger, modifier = Modifier.padding(12.dp))
                b == null -> Loading(Modifier.height(80.dp))
                else -> {
                    EmailView(b)
                    if (b.remoteImages > 0) Text("Images from the web stay hidden in the app. Open the message in Kern's web app to load them.",
                        style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 10.dp))
                    m.attachments.filter { !it.inline }.takeIf { it.isNotEmpty() }?.let { atts ->
                        Text(atts.joinToString("  ·  ") { "📎 " + it.filename }, style = MaterialTheme.typography.bodySmall, color = kern.text2,
                            modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp))
                    }
                }
            }
        }
    }
}

/**
 * SECURITY (read carefully): the email's HTML has already been sanitized by the server
 * (backend/mail/sanitize.py). On top of that this WebView runs no JavaScript, may not load
 * anything from the network or from files (so no trackers, remote images or local files), and
 * opens links only in the browser, only for http(s) and mailto.
 */
@SuppressLint("SetJavaScriptEnabled")
@Composable
private fun EmailView(b: MailBody) {
    val ctx = LocalContext.current
    val k = kern
    val inner = b.html ?: b.textHtml ?: android.text.Html.escapeHtml(b.text ?: "")
    // HTML mail is shown on white, the way senders design it; plain text follows the app theme.
    val isHtml = b.html != null
    fun hex(c: androidx.compose.ui.graphics.Color) = String.format("#%06X", 0xFFFFFF and c.toArgb())
    val bg = if (isHtml) "#ffffff" else hex(k.surface)
    val fg = if (isHtml) "#1f1f1f" else hex(k.text)
    val page = """<!doctype html><html><head><meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>html,body{margin:0;padding:6px 10px 10px;background:$bg;color:$fg;font:15px/1.5 sans-serif;overflow-wrap:anywhere}
        img{max-width:100%;height:auto}pre{white-space:pre-wrap}blockquote{margin:0 0 0 .6em;padding-left:.8em;border-left:2px solid #bbb;color:#666}</style>
        </head><body>$inner</body></html>"""
    key(page) {
        AndroidView(factory = { c ->
            WebView(c).apply {
                settings.javaScriptEnabled = false
                settings.blockNetworkLoads = true
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.domStorageEnabled = false
                settings.loadsImagesAutomatically = true // data: images only (network loads are blocked)
                isVerticalScrollBarEnabled = false
                setBackgroundColor(android.graphics.Color.TRANSPARENT)
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        val u = request.url
                        if (u.scheme in setOf("http", "https", "mailto")) {
                            runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, u).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                        }
                        return true
                    }
                }
                loadDataWithBaseURL(null, page, "text/html", "utf-8", null)
            }
        }, modifier = Modifier.fillMaxWidth().padding(horizontal = 4.dp))
    }
}

private fun parseAddrs(s: String): List<MailAddr> = s.split(',', ';').map { it.trim() }.filter { it.isNotEmpty() }.map { part ->
    val m = Regex("^(.*)<([^>]+)>$").find(part)
    if (m != null) MailAddr(m.groupValues[1].trim().trim('"'), m.groupValues[2].trim()) else MailAddr("", part)
}

private fun addrsText(l: List<MailAddr>) = l.joinToString(", ") { if (it.name.isBlank()) it.addr else "${it.name} <${it.addr}>" }

private fun textToHtml(t: String): String =
    t.trimEnd().split(Regex("\n{2,}")).joinToString("") { p -> "<p>" + android.text.Html.escapeHtml(p).replace("\n", "<br>") + "</p>" }

@Composable
fun MailComposeScreen(ws: Workspace, nav: Nav, message: Long? = null, mode: String? = null) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var to by remember { mutableStateOf("") }
    var cc by remember { mutableStateOf("") }
    var subject by remember { mutableStateOf("") }
    var text by remember { mutableStateOf("") }
    var quoted by remember { mutableStateOf("") }
    var signature by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var ready by remember { mutableStateOf(message == null) }
    val m = mode ?: "new"

    LaunchedEffect(message, mode) {
        runCatching { ws.kern.api.get<kotlinx.serialization.json.JsonObject>("/mail/preferences") }.getOrNull()?.let { p ->
            val sig = p.str("signature") ?: ""
            val onReplies = p.str("signature_on_replies") != "false"
            if (sig.isNotBlank() && (m == "new" || onReplies)) signature = sig
        }
        if (message != null) {
            try {
                val p = ws.kern.mailPrefill(message, m)
                to = addrsText(p.to); cc = addrsText(p.cc); subject = p.subject; quoted = p.bodyHtml
            } catch (e: Exception) { snack.error(e) }
            ready = true
        }
    }

    fun send() = scope.launch {
        val rcpt = parseAddrs(to)
        if (rcpt.isEmpty() || rcpt.any { "@" !in it.addr }) { snack.show("Check the recipients."); return@launch }
        busy = true
        try {
            val sigHtml = if (signature.isNotBlank()) "<div><br></div><div>-- <br>" + android.text.Html.escapeHtml(signature).replace("\n", "<br>") + "</div>" else ""
            ws.kern.mailSend(m, message, rcpt, parseAddrs(cc), subject, textToHtml(text) + sigHtml + quoted)
            snack.show("Sending…")
            nav.back()
        } catch (e: Exception) {
            snack.error(e)
        } finally { busy = false }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding().imePadding()) {
        KTopBar(when (m) { "reply", "reply_all" -> "Reply"; "forward" -> "Forward"; else -> "New message" }, onBack = { nav.back() }) {
            IconButton(onClick = { send() }, enabled = ready && !busy) { Icon(Icons.AutoMirrored.Outlined.Send, "Send", tint = kern.accent) }
        }
        if (!ready) Loading() else Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            KField(to, { to = it }, "To", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
            if (cc.isNotBlank() || m == "reply_all") KField(cc, { cc = it }, "Cc", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
            KField(subject, { subject = it }, "Subject")
            KField(text, { text = it }, "Message", singleLine = false, minLines = 8)
            if (signature.isNotBlank()) Text("-- \n$signature", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            if (quoted.isNotBlank()) Text(if (m == "forward") "The forwarded message is added below." else "The earlier message is quoted below your reply.",
                style = MaterialTheme.typography.bodySmall, color = kern.text3)
            KButton(if (busy) "Sending…" else "Send", Modifier.fillMaxWidth(), primary = true, enabled = !busy, icon = Icons.AutoMirrored.Outlined.Send) { send() }
            Spacer(Modifier.height(24.dp))
        }
    }
}
