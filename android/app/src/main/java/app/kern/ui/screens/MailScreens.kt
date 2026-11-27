package app.kern.ui.screens

import android.annotation.SuppressLint
import android.content.Intent
import android.net.Uri
import android.webkit.WebResourceRequest
import android.webkit.WebView
import android.webkit.WebViewClient
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.filled.Star
import androidx.compose.material.icons.outlined.AttachFile
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.DarkMode
import androidx.compose.material.icons.outlined.ExpandLess
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.GppMaybe
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.LightMode
import androidx.compose.material.icons.outlined.NotificationsOff
import androidx.compose.material.icons.outlined.Report
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.HorizontalDivider
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.outlined.Settings
import kotlinx.serialization.decodeFromString
import kotlinx.coroutines.async
import app.kern.ui.components.sparkleIcon
import app.kern.ui.components.tintOr
import androidx.compose.ui.draw.clip
import app.kern.app
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.navigationBarsPadding
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
import androidx.compose.material.icons.outlined.LocalShipping
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
import androidx.compose.ui.unit.sp
import androidx.compose.foundation.layout.offset
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

/** Who a conversation is with. The server sends this as `who` (backend/mail/names.py); this is the
 *  same rule for lists cached before it did, so the phone and the web name people alike. */
internal fun who(t: MailThread, me: String): String {
    if (t.who.isNotBlank()) return t.who
    fun first(p: MailAddr) = p.display.split(Regex("[\\s,]+")).firstOrNull().orEmpty().ifBlank { p.display }
    val senders = t.participants.filter { !it.to && !it.addr.equals(me, ignoreCase = true) }
    if (senders.isEmpty()) {
        val to = t.participants.filter { it.to }
        if (to.isNotEmpty()) return "To: " + to.take(3).joinToString(", ") { first(it) } + if (to.size > 3) "…" else ""
    }
    val people = senders.ifEmpty { t.participants.filter { !it.to } }
    if (people.isEmpty()) return "(no sender)"
    if (people.size == 1) return people[0].display
    val a = people.first()
    val b = people.last()
    val short = first(a) != first(b)
    val na = if (short) first(a) else a.display
    val nb = if (short) first(b) else b.display
    return if (people.size == 2) "$na, $nb" else "$na … $nb"
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MailScreen(ws: Workspace, nav: Nav, initialView: String? = null, standalone: Boolean = false) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    var status by remember { mutableStateOf<MailStatus?>(null) }
    var folders by remember { mutableStateOf<List<MailFolder>>(emptyList()) }
    var view by remember { mutableStateOf(initialView ?: "inbox") }
    var query by remember { mutableStateOf("") }
    var searching by remember { mutableStateOf(false) }
    var unreadOnly by remember { mutableStateOf(false) }
    val threads = remember { mutableStateListOf<MailThread>() }
    var next by remember { mutableStateOf<String?>(null) }
    var loading by remember { mutableStateOf(true) }
    var refreshing by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var parcels by remember { mutableStateOf<List<app.kern.data.MailPackage>>(emptyList()) }
    val me = status?.account?.str("address") ?: ""

    /** The Inbox as this phone last saw it. */
    fun cachedInbox(): List<MailThread>? = ctx.app.settings.mailInboxCache?.let { c ->
        runCatching { app.kern.data.KernJson.decodeFromString<List<MailThread>>(c) }.getOrNull()
    }
    // Instant start: the cached Inbox until the server answers.
    LaunchedEffect(Unit) {
        if (standalone) app.kern.notify.Notifications.clearMail(ctx) // you're looking at it now
        if (view == "inbox" && threads.isEmpty()) cachedInbox()?.let { threads.addAll(it); loading = false }
    }

    /** Loads the list (or its next page); [counts] also refreshes the folders and their unread numbers. */
    suspend fun load(more: Boolean = false, counts: Boolean = false) {
        val asked = Triple(view, unreadOnly, query.takeIf { searching && it.isNotBlank() })
        // False once another folder, filter or search was picked while this was on its way.
        fun current() = asked == Triple(view, unreadOnly, query.takeIf { searching && it.isNotBlank() })
        try {
            val r = kotlinx.coroutines.coroutineScope {
                val f = if (folders.isEmpty() || counts) async { runCatching { ws.kern.mailFolders().folders }.getOrNull() } else null
                val t = async {
                    ws.kern.mailThreads(apiView(view), q = asked.third, cursor = if (more) next else null,
                        unread = unreadOnly && !searching && view !in setOf("snoozed", "sent", "drafts"))
                }
                f?.await()?.let { folders = it }
                t.await()
            }
            if (!current()) return
            if (!more) threads.clear()
            // A page asked for before new mail arrived can repeat rows that are already shown.
            val shown = threads.mapTo(HashSet()) { it.id }
            threads.addAll(r.threads.filter { shown.add(it.id) })
            next = r.next
            error = null
            if (!more && view == "inbox" && !searching && !unreadOnly) runCatching {
                ctx.app.settings.mailInboxCache = app.kern.data.KernJson.encodeToString(kotlinx.serialization.builtins.ListSerializer(MailThread.serializer()), r.threads)
            }
        } catch (e: kotlinx.coroutines.CancellationException) {
            throw e // a newer load took over
        } catch (e: ApiError) {
            if (e.status == 403) status = runCatching { ws.kern.mailStatus() }.getOrNull() ?: status
            else if (current()) error = e.message
        } catch (e: Exception) {
            if (current()) error = e.message
        } finally {
            if (current()) loading = false
        }
    }
    LaunchedEffect(Unit) {
        status = runCatching { ws.kern.mailStatus() }.getOrElse { error = it.message; null }
    }
    LaunchedEffect(status, view, unreadOnly) {
        val s = status ?: return@LaunchedEffect
        if (s.twoFactor.enabled && s.twoFactor.sessionVerified && (s.connected || !s.account?.str("address").isNullOrBlank())) {
            loading = true
            load()
        }
    }

    suspend fun loadParcels() {
        runCatching { ws.kern.mailPackages() }.getOrNull()?.let { parcels = it.active }
    }
    // Live: mail read, archived or arriving anywhere else shows here within a second or two,
    // the same feed the web app and the notifications use.
    LaunchedEffect(status) {
        val s = status ?: return@LaunchedEffect
        if (!s.twoFactor.sessionVerified || !s.connected) return@LaunchedEffect
        loadParcels()
        var since: Long? = runCatching { ws.kern.mailChanges(null).last }.getOrNull()
        while (true) {
            try {
                val r = ws.kern.mailChanges(since, 25)
                val changed = r.reset || r.events.isNotEmpty()
                since = r.last
                if (changed && !searching) load(counts = true)
                if (r.events.any { it.kind == "package" }) loadParcels()
                if (changed && view == "inbox") app.kern.notify.Notifications.clearMail(ctx)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (_: Exception) {
                kotlinx.coroutines.delay(5_000)
            }
        }
    }

    val h24 = android.text.format.DateFormat.is24HourFormat(ctx)
    // A list read from the top stays at the top when new mail or the package strip arrives above
    // (a keyed list otherwise keeps the old first row in place and hides what's new above it).
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    var pinned by remember { mutableStateOf(true) }
    LaunchedEffect(listState) {
        androidx.compose.runtime.snapshotFlow { listState.isScrollInProgress }.collect { moving ->
            if (!moving) pinned = listState.firstVisibleItemIndex == 0 && listState.firstVisibleItemScrollOffset == 0
        }
    }
    LaunchedEffect(threads.firstOrNull()?.id, parcels.isNotEmpty(), view) {
        if (pinned && (listState.firstVisibleItemIndex != 0 || listState.firstVisibleItemScrollOffset != 0)) listState.scrollToItem(0)
    }
    var snoozing by remember { mutableStateOf<MailThread?>(null) }
    var menuFor by remember { mutableStateOf<Long?>(null) }

    fun replace(t: MailThread, with: MailThread) {
        val i = threads.indexOfFirst { it.id == t.id }
        if (i >= 0) threads[i] = with
    }

    val roles = rolesOf(folders)
    /** The folder being looked at; null for Starred, All mail and search. */
    val here = folders.firstOrNull { (it.role.isNotBlank() && it.role == view) || "f${it.id}" == view }?.id

    /** Takes [t] out of the list, does [act] and offers Undo, which puts it back where it was. */
    fun leave(t: MailThread, act: MailAct, done: String, vararg extra: Pair<String, Any?>) {
        threads.removeAll { it.id == t.id }
        val undo = inverseOf(act, roles)
        scope.launch {
            try {
                ws.kern.mailAction(listOf(t.id), act.action, *act.extras, *extra)
                if (undo == null) { snack.show(done); return@launch }
                val r = snack.host.showSnackbar(done, actionLabel = "Undo", duration = androidx.compose.material3.SnackbarDuration.Short)
                if (r == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                    ws.kern.mailAction(listOf(t.id), undo.action, *undo.extras)
                    load(counts = true)
                }
            } catch (e: Exception) { snack.error(e); load() }
        }
    }

    /** Swipe right: Archive, or back to the Inbox from Archive and Trash (the web's rule). */
    fun moveOut(t: MailThread) {
        if (view == "archive" || view == "trash") leave(t, MailAct("inbox", here), "Moved to Inbox")
        else leave(t, MailAct("archive", here), "Archived")
    }

    fun snooze(t: MailThread, at: java.time.LocalDateTime) {
        snoozing = null
        if (view != "snoozed") threads.removeAll { it.id == t.id }
        scope.launch {
            try {
                ws.kern.mailAction(listOf(t.id), "snooze", "until" to at.isoOffset(), *MailAct("snooze", here).extras)
                val r = snack.host.showSnackbar("Snoozed until " + snoozeLabel(at, h24), actionLabel = "Undo", duration = androidx.compose.material3.SnackbarDuration.Short)
                if (r == androidx.compose.material3.SnackbarResult.ActionPerformed) { ws.kern.mailAction(listOf(t.id), "unsnooze"); load() }
                else if (view == "snoozed") load()
            } catch (e: Exception) { snack.error(e); load() }
        }
    }

    fun star(t: MailThread) {
        replace(t, t.copy(starred = !t.starred))
        scope.launch {
            runCatching { ws.kern.mailAction(listOf(t.id), if (t.starred) "unstar" else "star") }
                .onSuccess { if (view == "starred" && t.starred) threads.removeAll { it.id == t.id } }
                .onFailure { replace(t, t); snack.error(it) }
        }
    }

    /** The long-press menu on a row. */
    fun rowAction(t: MailThread, action: String) {
        when (action) {
            "read", "unread" -> {
                replace(t, t.copy(unread = if (action == "read") 0 else maxOf(1, t.count)))
                scope.launch { runCatching { ws.kern.mailAction(listOf(t.id), action) }.onFailure { replace(t, t); snack.error(it) } }
            }
            "archive", "inbox" -> moveOut(t)
            "snooze" -> snoozing = t
            "star" -> star(t)
            "trash" -> leave(t, MailAct("trash", here), "Moved to Trash")
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
                // The web's subtitle: how much is unread in the Inbox, how many are snoozed.
                val inboxUnread = folders.firstOrNull { it.role == "inbox" }?.unread
                val subtitle = when {
                    view == "inbox" && inboxUnread != null -> if (inboxUnread > 0) "%,d unread".format(inboxUnread) else "all read"
                    view == "snoozed" && !loading -> "${threads.size} snoozed"
                    else -> me.ifBlank { null }
                }
                KTopBar(title, onBack = if (standalone) null else ({ nav.back() }), subtitle = subtitle) {
                    if (view !in setOf("snoozed", "sent", "drafts")) {
                        Segmented(listOf("All", "Unread"), if (unreadOnly) 1 else 0, Modifier.padding(end = 4.dp)) { unreadOnly = it == 1 }
                    }
                    IconButton(onClick = { searching = true }) { Icon(Icons.Outlined.Search, "Search", tint = kern.text2) }
                    if (standalone) IconButton(onClick = { nav.go("mail-settings") }) { Icon(Icons.Outlined.Settings, "Settings", tint = kern.text2) }
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
                                Pill(label, if (v == view) kern.accent else kern.text2, onClick = {
                                    pinned = true
                                    if (v != view) {
                                        // Not the last folder's mail under this one's name while it loads.
                                        threads.clear(); next = null; error = null; loading = true
                                        if (v == "inbox") cachedInbox()?.let { threads.addAll(it) }
                                        view = v
                                    }
                                })
                            }
                            Pill("Packages" + if (parcels.isNotEmpty()) " ${parcels.size}" else "", kern.text2, onClick = { nav.go("mail/packages") })
                        }
                    }
                    PullToRefreshBox(
                        isRefreshing = refreshing,
                        onRefresh = {
                            scope.launch {
                                refreshing = true
                                runCatching { ws.kern.mailCheckNow() } // ask the server to look for new mail now
                                load(counts = true)
                                kotlinx.coroutines.delay(900); load(counts = true) // the check usually lands within a second
                                refreshing = false
                            }
                        },
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        when {
                            loading && threads.isEmpty() -> Loading()
                            error != null && threads.isEmpty() -> ErrorState(error!!) { scope.launch { loading = true; load() } }
                            threads.isEmpty() -> Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState())) { // still pulls to refresh
                                val (head, line) = emptyText(view, searching, unreadOnly)
                                EmptyState(if (view == "inbox" && !searching) Icons.Outlined.Inbox else Icons.Outlined.Email, head, line)
                            }
                            else -> LazyColumn(Modifier.fillMaxSize(), state = listState) {
                                if (view == "inbox" && !searching && parcels.isNotEmpty()) item(key = "parcels") {
                                    ParcelStrip(parcels) { p -> nav.go(p.threadId?.let { "mail/thread/$it" } ?: "mail/packages") }
                                }
                                // Like the web: headings by day, except for Snoozed (sorted by wake-up time).
                                val grouped = view != "snoozed"
                                val today = LocalDate.now()
                                var lastGroup: String? = null
                                val seenGroups = HashSet<String>()
                                for (t in threads.toList()) {
                                    if (grouped) {
                                        val g = timeGroup(t.lastDate, today)
                                        if (g != lastGroup) {
                                            lastGroup = g
                                            val k = if (seenGroups.add(g)) "g:$g" else "g:$g:${t.id}"
                                            stickyHeader(key = k, contentType = "group") {
                                                Column(Modifier.fillMaxWidth().background(kern.bg)) {
                                                    Ledger(g, Modifier.padding(start = 24.dp, end = 16.dp, top = 12.dp, bottom = 5.dp))
                                                    HorizontalDivider(color = kern.border)
                                                }
                                            }
                                        }
                                    }
                                    item(key = t.id, contentType = "thread") {
                                        val toInbox = view == "archive" || view == "trash"
                                        SwipeRow(
                                            right = SwipeAction(if (toInbox) "Inbox" else "Archive", if (toInbox) Icons.Outlined.Inbox else Icons.Outlined.Archive,
                                                kern.green, leaves = true) { moveOut(t) },
                                            left = if (view == "drafts" || view == "sent") null else
                                                SwipeAction("Snooze", Icons.Outlined.Schedule, kern.accent, leaves = false) { snoozing = t },
                                            modifier = Modifier.animateItem(fadeInSpec = null, placementSpec = null, fadeOutSpec = null), // the row folds itself away
                                        ) {
                                            ThreadRow(t, me, h24, view,
                                                onStar = { star(t) },
                                                onLongClick = { menuFor = t.id },
                                                menu = menuFor == t.id,
                                                onMenuClose = { menuFor = null },
                                                onMenu = { action -> menuFor = null; rowAction(t, action) },
                                            ) { nav.go("mail/thread/${t.id}") }
                                        }
                                    }
                                }
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
        snoozing?.let { t -> SnoozeSheet(h24, onDismiss = { snoozing = null }) { at -> snooze(t, at) } }
    }
}

private val ROLE_VIEWS = setOf("inbox", "snoozed", "drafts", "sent", "archive", "junk", "trash")

internal fun rolesOf(folders: List<MailFolder>) = MailRoles(
    inbox = folders.firstOrNull { it.role == "inbox" }?.id,
    archive = folders.firstOrNull { it.role == "archive" }?.id,
    trash = folders.firstOrNull { it.role == "trash" }?.id,
    junk = folders.firstOrNull { it.role == "junk" }?.id,
)

/** The list's view as the server takes it: folders by role, "f12" (a folder of your own) as folder:12. */
internal fun apiView(v: String): String = when {
    v == "starred" || v == "all" || v in ROLE_VIEWS -> v
    v.startsWith("f") && v.drop(1).toLongOrNull() != null -> "folder:" + v.drop(1)
    else -> "all"
}

/** What an empty list says. */
internal fun emptyText(view: String, searching: Boolean, unreadOnly: Boolean): Pair<String, String?> = when {
    searching -> "No matches" to "Try other words, or fewer of them."
    unreadOnly -> "No unread mail" to null
    view == "inbox" -> "All caught up" to "New mail shows up here."
    view == "starred" -> "Nothing starred" to "Star a conversation to keep it here."
    view == "snoozed" -> "Nothing snoozed" to "Swipe a conversation left to have it come back later."
    view == "drafts" -> "No drafts" to null
    view == "sent" -> "Nothing sent yet" to null
    view == "junk" -> "No junk" to null
    view == "trash" -> "Trash is empty" to null
    else -> "Nothing here" to null
}

/** A search match from the server: the matched words sit between \u0002 and \u0003. */
private fun hitText(hit: String, strong: androidx.compose.ui.graphics.Color) = androidx.compose.ui.text.buildAnnotatedString {
    hit.split('\u0002').forEachIndexed { i, piece ->
        val parts = piece.split('\u0003', limit = 2)
        if (i > 0 && parts.size == 2) {
            pushStyle(androidx.compose.ui.text.SpanStyle(color = strong, fontWeight = FontWeight.SemiBold))
            append(parts[0]); pop(); append(parts[1])
        } else append(piece.replace("\u0003", ""))
    }
}

/** Packages on the way, small, at the top of the Inbox (the same strip as the web app). */
@Composable
private fun ParcelStrip(parcels: List<app.kern.data.MailPackage>, onOpen: (app.kern.data.MailPackage) -> Unit) {
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp, vertical = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(6.dp)) {
        parcels.take(6).forEach { p ->
            val hot = p.status == "out_for_delivery" || p.status == "ready_for_pickup"
            Row(Modifier.clip(androidx.compose.foundation.shape.RoundedCornerShape(14.dp)).background(kern.surface2)
                .clickable { onOpen(p) }.padding(horizontal = 10.dp, vertical = 5.dp), verticalAlignment = Alignment.CenterVertically) {
                Icon(Icons.Outlined.LocalShipping, null, tint = if (p.status == "exception") kern.danger else kern.text3, modifier = Modifier.size(14.dp))
                Spacer(Modifier.width(6.dp))
                Text(p.merchant.ifBlank { p.carrierName }, style = MaterialTheme.typography.labelMedium, color = kern.text, maxLines = 1)
                Spacer(Modifier.width(6.dp))
                Text(arrival(p), style = MaterialTheme.typography.labelMedium, color = if (hot) kern.accent else kern.text2, maxLines = 1)
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun MailPackagesScreen(ws: Workspace, nav: Nav) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    var data by remember { mutableStateOf<app.kern.data.MailPackages?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    val listState = androidx.compose.foundation.lazy.rememberLazyListState()
    suspend fun load() {
        try { data = ws.kern.mailPackages(); error = null } catch (e: Exception) { error = e.message }
    }
    LaunchedEffect(Unit) { load() }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Packages", onBack = { nav.back() })
        val d = data
        when {
            d == null && error == null -> Loading()
            d == null -> ErrorState(error!!) { scope.launch { load() } }
            else -> PullToRefreshBox(isRefreshing = refreshing, onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } }) {
                LazyColumn(Modifier.fillMaxSize(), state = listState, contentPadding = androidx.compose.foundation.layout.PaddingValues(start = 16.dp, end = 16.dp, bottom = 32.dp)) {
                    if (d.tracking?.hasKey != true) item {
                        Text("Live tracking is off: shops rarely email when something arrives. Turn it on in Kern's web app, Settings → Mail → Package tracking (built in with no account, or Parcels or TrackingMore).",
                            style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(bottom = 12.dp))
                    }
                    if (d.active.isNotEmpty() || d.delivered.isNotEmpty()) item {
                        // Every package on one map: on the way, and today's deliveries.
                        val recent = java.time.Instant.now().minusSeconds(2 * 86400)
                        val routes = d.active.map { MapRoute(it.id, it.route.latLon, false, it.merchant.ifBlank { it.carrierName }) } +
                            d.delivered.filter { p -> p.route.latLon.isNotEmpty() && runCatching { java.time.Instant.parse(p.statusAt ?: "") }.getOrNull()?.isAfter(recent) == true }
                                .map { MapRoute(it.id, it.route.latLon, true, it.merchant.ifBlank { it.carrierName }) }
                        RoutesMap(routes, d.map, height = 230.dp, onPick = { id ->
                            // Items above the cards: the tracking tip, this map, the section labels.
                            val before = (if (d.tracking?.hasKey != true) 1 else 0) + 1
                            val a = d.active.indexOfFirst { it.id == id }
                            val dl = d.delivered.indexOfFirst { it.id == id }
                            val i = when {
                                a >= 0 -> before + 1 + a
                                dl >= 0 -> before + (if (d.active.isNotEmpty()) 1 + d.active.size else 0) + 1 + dl
                                else -> -1
                            }
                            if (i >= 0) scope.launch { listState.animateScrollToItem(i) }
                        })
                    }
                    if (d.active.isEmpty() && d.delivered.isEmpty()) item { EmptyState(Icons.Outlined.LocalShipping, "No packages", "Shipping emails with a tracking number show up here.") }
                    if (d.active.isNotEmpty()) item { SectionLabel("On the way") }
                    items(d.active, key = { "a" + it.id }) { p -> PackageItem(p, nav, ctx, d.tracking?.hasKey == true, d.map) { action ->
                        scope.launch { runCatching { ws.kern.mailPackageAction(p.id, action) }.onFailure { snack.error(it) }; load() } } }
                    if (d.delivered.isNotEmpty()) item { SectionLabel("Delivered") }
                    items(d.delivered, key = { "d" + it.id }) { p -> PackageItem(p, nav, ctx, false, d.map) { action ->
                        scope.launch { runCatching { ws.kern.mailPackageAction(p.id, action) }.onFailure { snack.error(it) }; load() } } }
                }
            }
        }
    }
}

/** The package map: a line through its scans on map tiles from Kern's server, dark or light with
 *  the theme (the web's PackageMap.svelte / mapView.js, same math). */
@Composable
private fun PackageMap(points: List<Pair<Double, Double>>, delivered: Boolean, map: app.kern.data.MailMapInfo, height: androidx.compose.ui.unit.Dp = 170.dp) =
    RoutesMap(listOf(MapRoute(0, points, delivered, "")), map, height, labels = false)

/** One package's way on the map: its scans' places oldest first, and its name by the marker. */
internal data class MapRoute(val id: Long, val points: List<Pair<Double, Double>>, val delivered: Boolean, val label: String)

/** Routes on map tiles from Kern's server, dark or light with the theme (the web's PackageMap.svelte /
 *  mapView.js, same math). With no places yet it shows the world. */
@Composable
private fun RoutesMap(routes: List<MapRoute>, map: app.kern.data.MailMapInfo, height: androidx.compose.ui.unit.Dp = 170.dp,
                      labels: Boolean = true, onPick: ((Long) -> Unit)? = null) {
    val ctx = LocalContext.current
    val k = kern
    val theme = if (k.dark) "dark" else "light"
    androidx.compose.foundation.layout.BoxWithConstraints(Modifier.padding(top = 10.dp).fillMaxWidth().height(height)
        .clip(androidx.compose.foundation.shape.RoundedCornerShape(10.dp))
        .background(if (k.dark) androidx.compose.ui.graphics.Color(0xFF1B1B1D) else androidx.compose.ui.graphics.Color(0xFFF2F1EE))) {
        val w = maxWidth.value.toDouble()
        val h = maxHeight.value.toDouble()
        val tile = 256.0
        fun project(lat: Double, lon: Double, z: Int): Pair<Double, Double> {
            val size = tile * Math.pow(2.0, z.toDouble())
            val s = Math.sin(lat * Math.PI / 180).coerceIn(-0.9999, 0.9999)
            return ((lon + 180) / 360 * size) to ((0.5 - Math.log((1 + s) / (1 - s)) / (4 * Math.PI)) * size)
        }
        val all = routes.flatMap { it.points }
        val pad = 22.0
        var z: Int
        val ox: Double
        val oy: Double
        if (all.isEmpty()) {
            z = Math.ceil(Math.log(w / tile) / Math.log(2.0)).toInt().coerceIn(1, 4)
            val c = project(30.0, 0.0, z)
            ox = c.first - w / 2
            oy = (c.second - h / 2).coerceIn(0.0, maxOf(0.0, tile * (1 shl z) - h))
        } else {
            z = 9
            if (all.size > 1) {
                z = 11
                while (z > 1) {
                    val xy = all.map { project(it.first, it.second, z) }
                    if (xy.maxOf { it.first } - xy.minOf { it.first } <= w - 2 * pad && xy.maxOf { it.second } - xy.minOf { it.second } <= h - 2 * pad) break
                    z--
                }
            }
            val xy = all.map { project(it.first, it.second, z) }
            ox = (xy.maxOf { it.first } + xy.minOf { it.first }) / 2 - w / 2
            oy = (xy.maxOf { it.second } + xy.minOf { it.second }) / 2 - h / 2
        }
        // One zoom level deeper at half size: sharp on the phone's dense screen.
        val zt = minOf(z + 1, 18)
        val size = tile / 2
        val n = 1 shl zt
        val base = ctx.app.api.base
        // A source with one colourful style (OpenStreetMap): greyed down, and turned dark in the dark theme, like the web app.
        val tone = when {
            !map.tone -> androidx.compose.ui.graphics.ColorFilter.colorMatrix(androidx.compose.ui.graphics.ColorMatrix().apply { setToSaturation(0.7f) })
            k.dark -> androidx.compose.ui.graphics.ColorFilter.colorMatrix(androidx.compose.ui.graphics.ColorMatrix(floatArrayOf(
                -0.22f, -0.43f, -0.08f, 0f, 228f,
                -0.22f, -0.43f, -0.08f, 0f, 228f,
                -0.22f, -0.43f, -0.08f, 0f, 230f,
                0f, 0f, 0f, 1f, 0f)))
            else -> androidx.compose.ui.graphics.ColorFilter.colorMatrix(androidx.compose.ui.graphics.ColorMatrix().apply { setToSaturation(0.15f) })
        }
        for (ty in Math.floor(oy * 2 / tile).toInt()..Math.floor((oy + h) * 2 / tile).toInt()) {
            if (ty < 0 || ty >= n) continue
            for (tx in Math.floor(ox * 2 / tile).toInt()..Math.floor((ox + w) * 2 / tile).toInt()) {
                val x = ((tx % n) + n) % n
                coil.compose.AsyncImage(model = "$base/api/mail/maptiles/$theme/$zt/$x/$ty.png?v=${map.version}", contentDescription = null, colorFilter = tone,
                    modifier = Modifier.offset((tx * size - ox).dp, (ty * size - oy).dp).size(size.dp))
            }
        }
        val placed = routes.map { r -> r to r.points.map { p -> project(p.first, p.second, z).let { (it.first - ox) to (it.second - oy) } } }
        val accent = k.accent
        val page = k.bg
        val done = k.green
        androidx.compose.foundation.Canvas(Modifier.fillMaxSize()) {
            for ((r, xy) in placed) {
                val pts = xy.map { androidx.compose.ui.geometry.Offset(it.first.dp.toPx(), it.second.dp.toPx()) }
                val color = if (r.delivered) done else accent
                if (pts.size > 1) {
                    val path = androidx.compose.ui.graphics.Path().apply { moveTo(pts[0].x, pts[0].y); pts.drop(1).forEach { lineTo(it.x, it.y) } }
                    drawPath(path, page.copy(alpha = 0.7f), style = androidx.compose.ui.graphics.drawscope.Stroke(width = 6.dp.toPx(), cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                    drawPath(path, color, style = androidx.compose.ui.graphics.drawscope.Stroke(width = 3.dp.toPx(), cap = androidx.compose.ui.graphics.StrokeCap.Round, join = androidx.compose.ui.graphics.StrokeJoin.Round))
                }
                pts.dropLast(1).forEach {
                    drawCircle(page, 3.5.dp.toPx(), it)
                    drawCircle(color, 3.5.dp.toPx(), it, style = androidx.compose.ui.graphics.drawscope.Stroke(2.dp.toPx()))
                }
                pts.lastOrNull()?.let {
                    drawCircle(page, 8.5.dp.toPx(), it)
                    drawCircle(color, 6.dp.toPx(), it)
                }
            }
        }
        if (labels) for ((r, xy) in placed) {
            val now = xy.lastOrNull() ?: continue
            if (r.label.isBlank()) continue
            Text(r.label, style = MaterialTheme.typography.labelSmall, color = if (r.delivered) k.text2 else k.text, maxLines = 1,
                modifier = Modifier.offset((now.first + 10).dp, (now.second - 10).dp)
                    .clip(androidx.compose.foundation.shape.RoundedCornerShape(10.dp))
                    .background(k.bg.copy(alpha = 0.88f))
                    .then(if (onPick != null) Modifier.clickable { onPick(r.id) } else Modifier)
                    .padding(horizontal = 7.dp, vertical = 2.dp))
        }
        if (labels && all.isEmpty()) Text("Packages appear here once live tracking has their scans.", style = MaterialTheme.typography.bodySmall,
            color = k.text2, modifier = Modifier.align(Alignment.Center).clip(androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
                .background(k.bg.copy(alpha = 0.85f)).padding(horizontal = 12.dp, vertical = 6.dp))
        Text(map.attribution, style = MaterialTheme.typography.labelSmall.copy(fontSize = 8.sp), color = k.text3,
            modifier = Modifier.align(Alignment.BottomEnd).padding(horizontal = 4.dp, vertical = 1.dp))
    }
}

@Composable
private fun SectionLabel(text: String) {
    Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = kern.text3, modifier = Modifier.padding(top = 14.dp, bottom = 6.dp))
}

@Composable
private fun PackageItem(p: app.kern.data.MailPackage, nav: Nav, ctx: android.content.Context, live: Boolean, map: app.kern.data.MailMapInfo, act: (String) -> Unit) {
    var open by remember { mutableStateOf(false) }
    val tone = when (p.status) { "delivered" -> kern.green; "exception" -> kern.danger; "out_for_delivery", "ready_for_pickup" -> kern.accent; else -> kern.text2 }
    Column(Modifier.padding(vertical = 4.dp).fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
        .background(kern.surface).clickable { open = !open }.padding(14.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(listOf(p.carrierName, p.merchant).filter { it.isNotBlank() }.joinToString(" · "), style = MaterialTheme.typography.labelMedium, color = kern.text3, maxLines = 1)
                Text(arrival(p), style = MaterialTheme.typography.titleMedium, color = kern.text)
            }
            Text(p.statusLabel, style = MaterialTheme.typography.labelMedium, color = tone)
        }
        val route = p.route.latLon
        if (route.isNotEmpty()) PackageMap(route, p.status == "delivered", map)
        Row(Modifier.padding(top = 10.dp).fillMaxWidth(), horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            repeat(4) { i -> Box(Modifier.weight(1f).height(4.dp).clip(androidx.compose.foundation.shape.RoundedCornerShape(2.dp)).background(if (i <= p.step) tone else kern.border)) }
        }
        if (p.trackNote.isNotBlank() && live) Text(p.trackNote, style = MaterialTheme.typography.bodySmall, color = kern.orange,
            modifier = Modifier.padding(top = 8.dp))
        else p.events.firstOrNull()?.let { e ->
            Text(e.text + if (e.where.isNotBlank()) " · ${e.where}" else "", style = MaterialTheme.typography.bodySmall, color = kern.text2,
                modifier = Modifier.padding(top = 8.dp), maxLines = if (open) 3 else 1, overflow = TextOverflow.Ellipsis)
        }
        if (open) {
            p.events.drop(1).take(10).forEach { e ->
                Text(e.text + if (e.where.isNotBlank()) " · ${e.where}" else "", style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(top = 4.dp))
            }
            Text(p.number, style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(top = 8.dp))
            Row(Modifier.padding(top = 10.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                if (p.threadId != null) KButton("Email") { nav.go("mail/thread/${p.threadId}") }
                if (p.trackUrl.isNotBlank()) KButton("Track") {
                    runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, android.net.Uri.parse(p.trackUrl)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                }
                if (live) KButton("Check now") { act("refresh") }
                if (p.status != "delivered") KButton("Got it") { act("delivered") }
            }
        }
    }
}

/** One conversation in the list, laid out like the web's ThreadList row. */
@Composable
private fun ThreadRow(
    t: MailThread, me: String, h24: Boolean, view: String,
    onStar: () -> Unit, onLongClick: () -> Unit, menu: Boolean, onMenuClose: () -> Unit, onMenu: (String) -> Unit,
    onClick: () -> Unit,
) {
    val k = kern
    val unread = t.unread > 0
    Column(Modifier.fillMaxWidth()) {
        Box {
            Row(
                Modifier.fillMaxWidth()
                    .combinedClickable(onClick = onClick, onLongClick = onLongClick)
                    .padding(start = 24.dp, end = 6.dp, top = 10.dp, bottom = 10.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Column(Modifier.weight(1f)) {
                    Row(verticalAlignment = Alignment.CenterVertically) {
                        Text(
                            androidx.compose.ui.text.buildAnnotatedString {
                                append(who(t, me))
                                if (t.count > 1) {
                                    pushStyle(androidx.compose.ui.text.SpanStyle(color = k.text3, fontWeight = FontWeight.Normal, fontSize = 12.sp))
                                    append("  ${t.count}")
                                    pop()
                                }
                            },
                            maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 14.5.sp, lineHeight = 19.sp,
                            color = if (unread) k.text else k.text2,
                            fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                            modifier = Modifier.weight(1f),
                        )
                        if (t.risk == "high" || t.risk == "medium") {
                            Spacer(Modifier.width(6.dp))
                            Icon(Icons.Outlined.GppMaybe, if (t.risk == "high") "High phishing risk" else "Medium phishing risk",
                                tint = if (t.risk == "high") k.danger else k.orange, modifier = Modifier.size(15.dp))
                        }
                        if (t.hasAttachments) {
                            Spacer(Modifier.width(6.dp))
                            Icon(Icons.Outlined.AttachFile, "Has attachments", tint = k.text3, modifier = Modifier.size(14.dp))
                        }
                        if (t.muted) {
                            Spacer(Modifier.width(6.dp))
                            Icon(Icons.Outlined.NotificationsOff, "Muted", tint = k.text3, modifier = Modifier.size(14.dp))
                        }
                        Spacer(Modifier.width(8.dp))
                        if (t.snoozeUntil != null) {
                            Icon(Icons.Outlined.Schedule, "Snoozed", tint = k.accent, modifier = Modifier.size(12.dp))
                            Spacer(Modifier.width(3.dp))
                            Text(snoozeLabel(t.snoozeUntil, h24), fontSize = 11.5.sp, lineHeight = 15.sp, color = k.accent, maxLines = 1)
                        } else {
                            Text(mailDate(t.lastDate, h24), fontSize = 12.sp, lineHeight = 15.sp, maxLines = 1,
                                color = if (unread) k.accent else k.text3, fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal)
                        }
                    }
                    Spacer(Modifier.height(3.dp))
                    // Subject and preview on one line, the subject taking at most 72% (the web's line2).
                    androidx.compose.foundation.layout.BoxWithConstraints(Modifier.fillMaxWidth()) {
                        val cap = maxWidth * 0.72f
                        Row {
                            Text(t.subject.ifBlank { "(no subject)" }, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 14.sp, lineHeight = 19.sp,
                                color = if (unread) k.text else k.text2, fontWeight = if (unread) FontWeight.SemiBold else FontWeight.Normal,
                                modifier = Modifier.widthIn(max = cap))
                            val preview = if (t.hit.isNotBlank()) hitText(t.hit, k.text) else androidx.compose.ui.text.AnnotatedString(t.snippet)
                            if (preview.isNotBlank()) {
                                Spacer(Modifier.width(8.dp))
                                Text(preview, maxLines = 1, overflow = TextOverflow.Ellipsis, fontSize = 14.sp, lineHeight = 19.sp, color = k.text3, modifier = Modifier.weight(1f))
                            }
                        }
                    }
                }
                Box(Modifier.padding(start = 2.dp).size(36.dp).clip(CircleShape).clickable(onClick = onStar), contentAlignment = Alignment.Center) {
                    Icon(if (t.starred) Icons.Filled.Star else Icons.Outlined.StarBorder, if (t.starred) "Unstar" else "Star",
                        tint = if (t.starred) k.yellow else k.text3.copy(alpha = 0.6f), modifier = Modifier.size(18.dp))
                }
            }
            // The unread dot sits in the left margin, like the web.
            Box(Modifier.padding(start = 10.dp, top = 17.dp).size(6.dp).clip(CircleShape).background(if (unread) k.accent else androidx.compose.ui.graphics.Color.Transparent))
            DropdownMenu(expanded = menu, onDismissRequest = onMenuClose, offset = androidx.compose.ui.unit.DpOffset(24.dp, 0.dp)) {
                DropdownMenuItem(text = { Text(if (unread) "Mark read" else "Mark unread") }, leadingIcon = { Icon(Icons.Outlined.MarkEmailUnread, null) },
                    onClick = { onMenu(if (unread) "read" else "unread") })
                DropdownMenuItem(text = { Text(if (t.starred) "Unstar" else "Star") }, leadingIcon = { Icon(Icons.Outlined.StarBorder, null) }, onClick = { onMenu("star") })
                if (view != "drafts" && view != "sent") {
                    DropdownMenuItem(text = { Text("Snooze…") }, leadingIcon = { Icon(Icons.Outlined.Schedule, null) }, onClick = { onMenu("snooze") })
                }
                if (view == "archive" || view == "trash") {
                    DropdownMenuItem(text = { Text("Move to Inbox") }, leadingIcon = { Icon(Icons.Outlined.Inbox, null) }, onClick = { onMenu("inbox") })
                } else {
                    DropdownMenuItem(text = { Text("Archive") }, leadingIcon = { Icon(Icons.Outlined.Archive, null) }, onClick = { onMenu("archive") })
                }
                if (view != "trash") {
                    DropdownMenuItem(text = { Text("Move to Trash") }, leadingIcon = { Icon(Icons.Outlined.Delete, null) }, onClick = { onMenu("trash") })
                }
            }
        }
        HorizontalDivider(color = k.border)
    }
}

@Composable
fun MailThreadScreen(ws: Workspace, nav: Nav, id: Long) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val h24 = android.text.format.DateFormat.is24HourFormat(ctx)
    var detail by remember { mutableStateOf<MailThreadDetail?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var menu by remember { mutableStateOf(false) }
    var snoozing by remember { mutableStateOf(false) }
    var mine by remember { mutableStateOf<Set<String>>(emptySet()) }
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
    LaunchedEffect(id) {
        app.kern.notify.Notifications.cancelMailThread(ctx, id)
        load()
    }
    LaunchedEffect(Unit) {
        runCatching { ws.kern.mailInfo() }.getOrNull()?.let { i ->
            mine = (listOf(i.address) + i.identities.map { it.address }).filter { it.isNotBlank() }.map { it.lowercase() }.toSet()
        }
    }
    var asking by remember { mutableStateOf(false) }
    fun ask() = scope.launch {
        if (asking) return@launch
        asking = true
        try { nav.go("chat/${ws.kern.createChat().id}?mail=$id") } catch (e: Exception) { snack.error(e) }
        asking = false
    }

    var roles by remember { mutableStateOf(MailRoles()) }
    LaunchedEffect(Unit) { runCatching { ws.kern.mailFolders().folders }.getOrNull()?.let { roles = rolesOf(it) } }

    fun act(action: String, done: String, vararg extra: Pair<String, Any?>) = scope.launch {
        try {
            ws.kern.mailAction(listOf(id), action, *extra)
            if (action !in setOf("archive", "trash", "snooze", "spam")) { snack.show(done); load(); return@launch }
            nav.back()
            val undo = inverseOf(MailAct(action), roles) ?: return@launch snack.show(done)
            // On the app's own scope: this screen is gone by the time Undo is tapped.
            snack.scope.launch {
                snack.host.currentSnackbarData?.dismiss()
                val r = snack.host.showSnackbar(done, actionLabel = "Undo", duration = androidx.compose.material3.SnackbarDuration.Short)
                if (r == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                    runCatching { ws.kern.mailAction(listOf(id), undo.action, *undo.extras) }.onFailure { snack.error(it) }
                }
            }
        } catch (e: Exception) { snack.error(e) }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        val t = detail?.thread
        KTopBar("", onBack = { nav.back() }) {
            if (t != null) {
                IconButton(onClick = { ask() }, enabled = !asking) { Icon(sparkleIcon, "Ask Intelligence about this email", tint = sparkleIcon.tintOr(kern.accent)) }
                IconButton(onClick = { act("archive", "Archived") }) { Icon(Icons.Outlined.Archive, "Archive", tint = kern.text2) }
                IconButton(onClick = { act("trash", "Moved to Trash") }) { Icon(Icons.Outlined.Delete, "Trash", tint = kern.text2) }
                IconButton(onClick = { act(if (t.starred) "unstar" else "star", if (t.starred) "Unstarred" else "Starred") }) {
                    Icon(if (t.starred) Icons.Filled.Star else Icons.Outlined.StarBorder, if (t.starred) "Unstar" else "Star", tint = if (t.starred) kern.yellow else kern.text2)
                }
                Box {
                    IconButton(onClick = { menu = true }) { Icon(Icons.Outlined.MoreVert, "More", tint = kern.text2) }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Mark unread") }, leadingIcon = { Icon(Icons.Outlined.MarkEmailUnread, null) },
                            onClick = {
                                menu = false
                                scope.launch { runCatching { ws.kern.mailAction(listOf(id), "unread") }.onSuccess { nav.back() }.onFailure { snack.error(it) } }
                            })
                        DropdownMenuItem(text = { Text("Snooze…") }, leadingIcon = { Icon(Icons.Outlined.Schedule, null) },
                            onClick = { menu = false; snoozing = true })
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
                        DropdownMenuItem(text = { Text("Report spam") }, leadingIcon = { Icon(Icons.Outlined.Report, null) },
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
                item(key = "subject") {
                    Column(Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 2.dp, bottom = 14.dp)) {
                        Text(d.thread.subject.ifBlank { "(no subject)" }, fontSize = 19.sp, lineHeight = 24.sp, fontWeight = FontWeight(650), color = kern.text)
                        val summary = threadSummary(d.messages, h24)
                        if (summary.isNotBlank()) Text(summary, fontSize = 12.sp, color = kern.text3, modifier = Modifier.padding(top = 6.dp))
                    }
                }
                d.thread.snoozeUntil?.let { until ->
                    item(key = "snoozed") {
                        Row(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp).fillMaxWidth()
                            .clip(androidx.compose.foundation.shape.RoundedCornerShape(10.dp)).background(kern.tint(kern.accent))
                            .clickable { snoozing = true }.padding(horizontal = 14.dp, vertical = 10.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.Schedule, null, tint = kern.accent, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(10.dp))
                            Text("Snoozed until " + snoozeLabel(until, h24), style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                            Ledger("Change", color = kern.accent)
                        }
                    }
                }
                val risky = d.messages.firstOrNull { !it.fromMe && (it.risk.level == "high" || it.risk.level == "medium") }
                if (risky != null) item(key = "risk") {
                    val tone = if (risky.risk.level == "high") kern.danger else kern.orange
                    Row(Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp).fillMaxWidth()
                        .background(kern.tint(tone), androidx.compose.foundation.shape.RoundedCornerShape(10.dp)).padding(12.dp),
                        verticalAlignment = Alignment.Top) {
                        Icon(Icons.Outlined.GppMaybe, null, tint = tone, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(10.dp))
                        Column {
                            Text(if (risky.risk.level == "high") "This looks like phishing" else "Be careful with this message",
                                fontWeight = FontWeight.SemiBold, color = tone, style = MaterialTheme.typography.bodyMedium)
                            risky.risk.findings.take(3).forEach { f ->
                                Text(f.str("title") ?: f.str("rule") ?: "", style = MaterialTheme.typography.bodySmall, color = kern.text2)
                            }
                        }
                    }
                }
                items(d.tasks.filter { it.source?.kind == "mail" }, key = { "task-" + it.id }) { task ->
                    Row(Modifier.padding(horizontal = 8.dp).fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp))
                        .clickable { nav.go("tasks?task=${task.id}") }, verticalAlignment = Alignment.CenterVertically) {
                        Checkbox(task.done, onCheckedChange = { done ->
                            scope.launch { runCatching { ws.kern.updateTask(task.id, "done" to done) }; load() }
                        }, colors = CheckboxDefaults.colors(checkedColor = kern.accent))
                        Text(task.title + (task.due?.let { " · due ${app.kern.ui.components.dueLabel(it)}" } ?: ""),
                            style = MaterialTheme.typography.bodyMedium, color = if (task.done) kern.text3 else kern.text)
                    }
                }
                item(key = "top-line") { HorizontalDivider(color = kern.border) }
                items(d.messages, key = { it.id }) { m ->
                    MessageItem(ws, nav, m, mine, h24, expanded = m.id in open) { if (m.id in open) open.remove(m.id) else open.add(m.id) }
                    HorizontalDivider(color = kern.border)
                }
                item(key = "reply") {
                    val last = d.messages.lastOrNull()
                    if (last != null && last.isDraft) Row(Modifier.fillMaxWidth().padding(16.dp)) {
                        KButton("Edit draft", Modifier.weight(1f), primary = true, icon = Icons.Outlined.Edit) {
                            scope.launch {
                                try { nav.go("mail/compose?draft=${ws.kern.mailDraftOf(last.id).id}") } catch (e: Exception) { snack.error(e) }
                            }
                        }
                    } else if (last != null) Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        KButton("Reply", Modifier.weight(1f), icon = Icons.AutoMirrored.Outlined.Reply) { nav.go("mail/compose?msg=${last.id}&mode=reply") }
                        KButton("Reply all", Modifier.weight(1f), icon = Icons.AutoMirrored.Outlined.ReplyAll) { nav.go("mail/compose?msg=${last.id}&mode=reply_all") }
                        KButton("Forward", Modifier.weight(1f), icon = Icons.AutoMirrored.Outlined.Forward) { nav.go("mail/compose?msg=${last.id}&mode=forward") }
                    }
                }
                item { Spacer(Modifier.height(32.dp).navigationBarsPadding()) }
            }
        }
    }
    if (snoozing) SnoozeSheet(h24, onDismiss = { snoozing = false }) { at ->
        snoozing = false
        act("snooze", "Snoozed until " + snoozeLabel(at, h24), "until" to at.isoOffset())
    }
}

/** "3 messages · Ada, Grace and you · Nov 3 – 2 hours ago", the web's line under the subject. */
private fun threadSummary(msgs: List<MailMessage>, h24: Boolean): String {
    if (msgs.isEmpty()) return ""
    val people = mutableListOf<String>()
    val seen = HashSet<String>()
    for (m in msgs) {
        if (!seen.add(m.from.addr.lowercase())) continue
        people += if (m.fromMe) "you" else m.from.name.ifBlank { m.from.addr }.split(Regex("[\\s,]+")).first()
    }
    if ("you" in people) { people.remove("you"); people.add("you") }
    val names = if (people.size > 3) "${people.take(2).joinToString(", ")} and ${people.size - 2} others"
        else people.joinToString(", ").replace(Regex(", ([^,]*)$"), " and $1")
    val zone = java.time.ZoneId.systemDefault()
    fun day(iso: String?) = runCatching { ZonedDateTime.parse(iso).withZoneSameInstant(zone).toLocalDate() }.getOrNull()
    val lastLabel = ago(msgs.last().date)
    val span = if (msgs.size > 1 && day(msgs.first().date) != day(msgs.last().date)) "${mailDate(msgs.first().date, h24)} – $lastLabel" else lastLabel
    return listOf(if (msgs.size == 1) "1 message" else "${msgs.size} messages", names, span).filter { it.isNotBlank() }.joinToString("  ·  ")
}

private val PREVIEWABLE = setOf("image/png", "image/jpeg", "image/jpg", "image/gif", "image/webp")

/** One message of a conversation: the web's MessageCard, edge to edge on the phone. */
@Composable
private fun MessageItem(ws: Workspace, nav: Nav, m: MailMessage, mine: Set<String>, h24: Boolean, expanded: Boolean, onToggle: () -> Unit) {
    var body by remember(m.id) { mutableStateOf<MailBody?>(null) }
    var failed by remember(m.id) { mutableStateOf(false) }
    var original by remember(m.id) { mutableStateOf(false) }
    var images by remember(m.id) { mutableStateOf(false) }
    var details by remember(m.id) { mutableStateOf(false) }
    var menu by remember(m.id) { mutableStateOf(false) }
    var attempt by remember(m.id) { mutableStateOf(0) }
    val ctx = LocalContext.current
    val k = kern
    // The server fits the email to the theme (no white sheet; dark mail keeps its colors), like the web app.
    val colors = if (original) null else if (k.dark) (if (ctx.app.settings.mailDarkEmails) "dark" else null) else "light"
    LaunchedEffect(m.id, expanded, colors, images, attempt) {
        if (!expanded) return@LaunchedEffect
        failed = false
        body = runCatching { ws.kern.mailBody(m.id, colors, images) }.getOrElse { failed = true; body }
    }
    val files = m.attachments.filter { !it.inline }
    val risk = !m.fromMe && (m.risk.level == "high" || m.risk.level == "medium")
    fun person(a: MailAddr) = if (a.addr.lowercase() in mine) "me" else a.display
    val toLine = "to " + (m.to + m.cc).joinToString(", ") { person(it) }.ifBlank { "undisclosed recipients" }

    Column(Modifier.fillMaxWidth()) {
        Row(
            Modifier.fillMaxWidth().clickable(onClick = onToggle)
                .padding(start = 16.dp, end = if (expanded) 4.dp else 16.dp, top = 12.dp, bottom = if (expanded) 6.dp else 12.dp),
            verticalAlignment = Alignment.Top,
        ) {
            MailAvatar(m.from)
            Spacer(Modifier.width(12.dp))
            Column(Modifier.weight(1f).padding(top = 1.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Text(m.from.display.ifBlank { "(unknown sender)" }, fontWeight = FontWeight.SemiBold, fontSize = 14.5.sp, color = k.text,
                        maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                    if (risk) {
                        Spacer(Modifier.width(6.dp))
                        Ledger(if (m.risk.level == "high") "High risk" else "Suspicious", color = if (m.risk.level == "high") k.danger else k.orange)
                    }
                    if (m.isDraft) {
                        Spacer(Modifier.width(6.dp))
                        Ledger("Draft", color = k.danger)
                    }
                }
                if (expanded) {
                    if (m.from.name.isNotBlank()) Text(m.from.addr, fontSize = 12.5.sp, color = k.text3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Row(Modifier.clip(androidx.compose.foundation.shape.RoundedCornerShape(6.dp)).clickable { details = !details }.padding(vertical = 2.dp),
                        verticalAlignment = Alignment.CenterVertically) {
                        Text(toLine, fontSize = 12.5.sp, color = k.text3, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f, fill = false))
                        Icon(if (details) Icons.Outlined.ExpandLess else Icons.Outlined.ExpandMore, if (details) "Hide details" else "Show details",
                            tint = k.text3, modifier = Modifier.size(16.dp))
                    }
                } else {
                    Text(m.snippet, fontSize = 13.sp, color = k.text3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
            }
            Spacer(Modifier.width(8.dp))
            if (expanded) {
                Text(mailDate(m.date, h24), fontSize = 11.5.sp, color = k.text3, modifier = Modifier.padding(top = 3.dp))
                Box(Modifier.size(36.dp).clip(CircleShape).clickable { nav.go("mail/compose?msg=${m.id}&mode=reply") }, contentAlignment = Alignment.Center) {
                    Icon(Icons.AutoMirrored.Outlined.Reply, "Reply", tint = k.text2, modifier = Modifier.size(18.dp))
                }
                Box {
                    Box(Modifier.size(36.dp).clip(CircleShape).clickable { menu = true }, contentAlignment = Alignment.Center) {
                        Icon(Icons.Outlined.MoreVert, "More", tint = k.text2, modifier = Modifier.size(18.dp))
                    }
                    DropdownMenu(expanded = menu, onDismissRequest = { menu = false }) {
                        DropdownMenuItem(text = { Text("Reply all") }, leadingIcon = { Icon(Icons.AutoMirrored.Outlined.ReplyAll, null) },
                            onClick = { menu = false; nav.go("mail/compose?msg=${m.id}&mode=reply_all") })
                        DropdownMenuItem(text = { Text("Forward") }, leadingIcon = { Icon(Icons.AutoMirrored.Outlined.Forward, null) },
                            onClick = { menu = false; nav.go("mail/compose?msg=${m.id}&mode=forward") })
                        val b = body
                        if (b?.html != null && (original || b.colors in setOf("adapted", "dark", "light"))) {
                            DropdownMenuItem(text = { Text(if (original) "Fit colors to the theme" else "Show original colors") },
                                leadingIcon = { Icon(if (original) Icons.Outlined.DarkMode else Icons.Outlined.LightMode, null) },
                                onClick = { menu = false; original = !original })
                        }
                        if (b != null && b.remoteImages > 0 && !b.imagesLoaded) {
                            DropdownMenuItem(text = { Text("Load images") }, leadingIcon = { Icon(Icons.Outlined.Image, null) },
                                onClick = { menu = false; images = true })
                        }
                    }
                }
            } else {
                if (files.isNotEmpty()) {
                    Icon(Icons.Outlined.AttachFile, null, tint = k.text3, modifier = Modifier.padding(top = 2.dp, end = 4.dp).size(14.dp))
                }
                Text(mailDate(m.date, h24), fontSize = 11.5.sp, color = k.text3, modifier = Modifier.padding(top = 2.dp))
            }
        }
        if (expanded) {
            if (details) MessageDetails(m, Modifier.padding(start = 16.dp, end = 16.dp, bottom = 10.dp))
            val b = body
            when {
                failed && b == null -> Row(Modifier.padding(horizontal = 16.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Text("Couldn't load this message.", color = k.danger, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.weight(1f))
                    app.kern.ui.components.TextAction("Retry") { attempt++ }
                }
                b == null -> Column(Modifier.padding(start = 16.dp, end = 16.dp, top = 6.dp, bottom = 18.dp), verticalArrangement = Arrangement.spacedBy(9.dp)) {
                    listOf(0.88f, 0.75f, 0.52f).forEach { w ->
                        Box(Modifier.fillMaxWidth(w).height(10.dp).clip(androidx.compose.foundation.shape.RoundedCornerShape(5.dp)).background(k.surface2))
                    }
                }
                else -> {
                    if (b.remoteImages > 0 && !b.imagesLoaded) {
                        Row(Modifier.padding(start = 16.dp, end = 16.dp, top = 2.dp, bottom = 8.dp).fillMaxWidth()
                            .clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp)).background(k.surface2)
                            .padding(start = 12.dp, end = 4.dp, top = 4.dp, bottom = 4.dp),
                            verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.Image, null, tint = k.text2, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(8.dp))
                            Text("${b.remoteImages} remote image${if (b.remoteImages == 1) "" else "s"} blocked to protect your privacy.",
                                fontSize = 12.5.sp, lineHeight = 16.sp, color = k.text2, modifier = Modifier.weight(1f))
                            Text("Load images", color = k.accent, fontSize = 13.sp, fontWeight = FontWeight.SemiBold,
                                modifier = Modifier.clip(androidx.compose.foundation.shape.RoundedCornerShape(6.dp)).clickable { images = true }
                                    .padding(horizontal = 10.dp, vertical = 8.dp))
                        }
                    }
                    val blank = b.html == null && (b.text ?: "").isBlank()
                    if (blank && files.isEmpty()) Text("No message text.", style = MaterialTheme.typography.bodySmall, color = k.text3,
                        modifier = Modifier.padding(start = 16.dp, end = 16.dp, bottom = 12.dp))
                    else if (!blank) EmailView(b, original = original)
                    if (files.isNotEmpty()) Attachments(m, files)
                    Spacer(Modifier.height(6.dp))
                }
            }
        }
    }
}

@Composable
private fun MessageDetails(m: MailMessage, modifier: Modifier = Modifier) {
    val k = kern
    fun full(a: MailAddr) = if (a.name.isBlank()) a.addr else "${a.name} <${a.addr}>"
    val rows = buildList {
        add("From" to full(m.from))
        if (m.replyTo.isNotEmpty()) add("Reply-To" to m.replyTo.joinToString(", ") { it.addr })
        if (m.to.isNotEmpty()) add("To" to m.to.joinToString(", ") { full(it) })
        if (m.cc.isNotEmpty()) add("Cc" to m.cc.joinToString(", ") { it.addr })
        val whenText = runCatching {
            ZonedDateTime.parse(m.date).withZoneSameInstant(java.time.ZoneId.systemDefault())
                .format(java.time.format.DateTimeFormatter.ofLocalizedDateTime(java.time.format.FormatStyle.MEDIUM, java.time.format.FormatStyle.SHORT))
        }.getOrNull()
        if (whenText != null) add("Date" to "$whenText (${ago(m.date)})")
    }
    Column(modifier.fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp)).background(k.surface2).padding(horizontal = 12.dp, vertical = 10.dp),
        verticalArrangement = Arrangement.spacedBy(3.dp)) {
        rows.forEach { (label, value) ->
            Row {
                Text(label, fontSize = 12.5.sp, color = k.text3, modifier = Modifier.width(72.dp))
                Text(value, fontSize = 12.5.sp, color = k.text, modifier = Modifier.weight(1f))
            }
        }
    }
}

/** Files on a message: a thumbnail for pictures, the type for the rest; tap opens it in another app. */
@Composable
private fun Attachments(m: MailMessage, files: List<app.kern.data.MailAttachment>) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val k = kern
    var opening by remember { mutableStateOf<Long?>(null) }
    val base = ctx.app.api.base
    androidx.compose.foundation.layout.FlowRow(
        Modifier.fillMaxWidth().padding(start = 16.dp, end = 16.dp, top = 4.dp, bottom = 8.dp),
        horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp),
    ) {
        files.forEach { a ->
            val shape = androidx.compose.foundation.shape.RoundedCornerShape(10.dp)
            Row(
                Modifier.widthIn(max = 280.dp).clip(shape).border(1.dp, k.border, shape)
                    .clickable(enabled = opening == null) {
                        opening = a.id
                        scope.launch {
                            try { openAttachment(ctx, m.id, a) } catch (e: Exception) { snack.error(e) }
                            opening = null
                        }
                    }
                    .padding(6.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Box(Modifier.size(40.dp).clip(androidx.compose.foundation.shape.RoundedCornerShape(6.dp)).background(k.surface2), contentAlignment = Alignment.Center) {
                    if (a.contentType.lowercase() in PREVIEWABLE) {
                        coil.compose.AsyncImage(model = "$base/api/mail/messages/${m.id}/attachments/${a.id}?inline=1", contentDescription = null,
                            contentScale = androidx.compose.ui.layout.ContentScale.Crop, modifier = Modifier.fillMaxSize())
                    } else {
                        Text(a.filename.substringAfterLast('.', "file").take(4).uppercase(), fontSize = 10.sp, fontWeight = FontWeight.SemiBold, color = k.text2)
                    }
                }
                Spacer(Modifier.width(10.dp))
                Column(Modifier.padding(end = 8.dp)) {
                    Text(a.filename.ifBlank { "attachment" }, fontSize = 13.sp, color = k.text, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(if (opening == a.id) "Opening…" else app.kern.ui.components.bytes(a.size), fontSize = 11.5.sp, color = k.text3)
                }
            }
        }
    }
}

/** Downloads an attachment into the app's cache and hands it to whichever app opens that type. */
private suspend fun openAttachment(ctx: android.content.Context, message: Long, a: app.kern.data.MailAttachment) {
    val api = ctx.app.api
    val file = kotlinx.coroutines.withContext(kotlinx.coroutines.Dispatchers.IO) {
        val dir = java.io.File(ctx.cacheDir, "mail/$message-${a.id}").apply { mkdirs() }
        val name = a.filename.replace(Regex("[\\\\/:*?\"<>|\\p{Cntrl}]"), "_").trim().trimStart('.').ifBlank { "attachment" }.take(120)
        val f = java.io.File(dir, name)
        if (!f.exists() || f.length() == 0L) {
            val req = okhttp3.Request.Builder().url("${api.base}/api/mail/messages/$message/attachments/${a.id}").build()
            try {
                api.http.newCall(req).execute().use { r ->
                    if (!r.isSuccessful) throw ApiError(r.code, "Couldn't download ${a.filename}.")
                    val tmp = java.io.File(dir, "$name.part")
                    r.body!!.byteStream().use { input -> tmp.outputStream().use { input.copyTo(it) } }
                    tmp.renameTo(f)
                }
            } catch (e: java.io.IOException) {
                throw ApiError(0, "Cannot reach the server.")
            }
        }
        f
    }
    val uri = androidx.core.content.FileProvider.getUriForFile(ctx, ctx.packageName + ".files", file)
    val type = a.contentType.lowercase().ifBlank { null }
        ?: android.webkit.MimeTypeMap.getSingleton().getMimeTypeFromExtension(file.extension.lowercase()) ?: "application/octet-stream"
    val view = Intent(Intent.ACTION_VIEW).setDataAndType(uri, type)
        .addFlags(Intent.FLAG_GRANT_READ_URI_PERMISSION or Intent.FLAG_ACTIVITY_NEW_TASK)
    try {
        ctx.startActivity(view)
    } catch (e: android.content.ActivityNotFoundException) {
        throw ApiError(0, "No app on this phone opens ${a.filename}.")
    }
}

/**
 * SECURITY (read carefully): the email's HTML has already been sanitized by the server
 * (backend/mail/sanitize.py), which also rewrote every picture to Kern's own address: inline
 * attachments, and remote images only through the signed image proxy once they're allowed.
 * On top of that this WebView runs no JavaScript and reads no files, the page's CSP allows
 * images only from the Kern server and data:, and every request the page makes goes through
 * [shouldInterceptRequest]: only GETs for /api/mail/img and a message's attachments on the
 * Kern server are answered (with the app's session, raster images only); everything else gets
 * an empty 403. Links open only in the browser, only for http(s) and mailto.
 */
@Composable
private fun EmailView(b: MailBody, original: Boolean = false) {
    val ctx = LocalContext.current
    val k = kern
    val api = ctx.app.api
    val server = remember(api.base) { runCatching { android.net.Uri.parse(api.base) }.getOrNull() }
    val origin = server?.let { "${it.scheme}://${it.encodedAuthority}" } ?: ""
    val prefix = server?.encodedPath?.trimEnd('/') ?: ""
    val inner = b.html ?: b.textHtml ?: android.text.Html.escapeHtml(b.text ?: "")
    fun hex(c: androidx.compose.ui.graphics.Color) = String.format("#%06X", 0xFFFFFF and c.toArgb())
    // The email sits on the app's own background: the server already fitted its colors to the theme
    // (backend/mail/colors.py), so nothing is inverted here. Original colors: as sent, on white.
    val asSent = original && b.html != null
    val bg = if (asSent) "#ffffff" else "transparent"
    val fg = if (asSent) "#222222" else hex(k.text)
    val link = if (asSent || !k.dark) "#2f4ad0" else "#8ab4f8"
    val quote = if (asSent) "#c9c9cf" else hex(k.borderStrong)
    val muted = if (asSent) "#555555" else hex(k.text2)
    val scheme = if (k.dark && !asSent) "dark" else "light"
    // Edge to edge: HTML mail gets a narrow margin (newsletters bring their own), plain text the app's 16.
    val pad = when {
        asSent -> "12px 12px 14px"
        b.html != null -> "2px 12px 12px"
        else -> "2px 16px 12px"
    }
    val page = """<!doctype html><html style="color-scheme:$scheme"><head><meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; img-src $origin data:; style-src 'unsafe-inline'; font-src data:; form-action 'none'; base-uri 'none'">
        <meta name="color-scheme" content="$scheme">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <meta name="referrer" content="no-referrer">
        <style>html,body{margin:0;background:$bg;color:$fg}
        body{padding:$pad;font:15px/1.55 sans-serif;overflow-wrap:anywhere;word-break:break-word}
        img{max-width:100%;height:auto}table{max-width:100%}pre{white-space:pre-wrap}
        blockquote{margin:0 0 0 .6em;padding-left:.8em;border-left:2px solid $quote;color:$muted}a{color:$link}</style>
        </head><body>$inner</body></html>"""
    val attachment = remember { Regex("^/api/mail/messages/\\d+/attachments/\\d+$") }
    key(page) {
        AndroidView(factory = { c ->
            WebView(c).apply {
                settings.javaScriptEnabled = false
                settings.allowFileAccess = false
                settings.allowContentAccess = false
                settings.domStorageEnabled = false
                settings.loadsImagesAutomatically = true
                settings.textZoom = 100
                isVerticalScrollBarEnabled = false
                isHorizontalScrollBarEnabled = false
                setBackgroundColor(if (asSent) android.graphics.Color.WHITE else android.graphics.Color.TRANSPARENT)
                webViewClient = object : WebViewClient() {
                    override fun shouldOverrideUrlLoading(view: WebView, request: WebResourceRequest): Boolean {
                        val u = request.url
                        if (u.scheme in setOf("http", "https", "mailto")) {
                            runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, u).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
                        }
                        return true
                    }

                    override fun shouldInterceptRequest(view: WebView, request: WebResourceRequest): android.webkit.WebResourceResponse? {
                        val u = request.url
                        // The email page itself (loadDataWithBaseURL below) arrives here as a data: main frame.
                        if (request.isForMainFrame && u.scheme == "data") return null
                        val path = (u.encodedPath ?: "").let { p -> if (prefix.isNotEmpty() && p.startsWith("$prefix/")) p.removePrefix(prefix) else p }
                        val ours = origin.isNotEmpty() && request.method == "GET" && "${u.scheme}://${u.encodedAuthority}" == origin &&
                            (path == "/api/mail/img" || attachment.matches(path))
                        if (!ours) return refused()
                        return try {
                            val url = api.base + path + (u.encodedQuery?.let { "?$it" } ?: "")
                            val res = api.http.newCall(okhttp3.Request.Builder().url(url).header("Accept", "image/*").build()).execute()
                            val type = res.header("Content-Type")?.substringBefore(';')?.trim()?.lowercase() ?: ""
                            if (!res.isSuccessful || !type.startsWith("image/") || type.contains("svg")) {
                                res.close(); refused()
                            } else android.webkit.WebResourceResponse(type, null, res.body!!.byteStream())
                        } catch (_: Exception) {
                            refused()
                        }
                    }
                }
                loadDataWithBaseURL(if (origin.isNotEmpty()) "$origin/" else null, page, "text/html", "utf-8", null)
            }
        }, modifier = Modifier.fillMaxWidth())
    }
}

private fun refused() = android.webkit.WebResourceResponse("text/plain", "utf-8", 403, "Blocked", emptyMap(), java.io.ByteArrayInputStream(ByteArray(0)))

private fun textToHtml(t: String): String =
    t.trimEnd().split(Regex("\n{2,}")).joinToString("") { p -> "<p>" + android.text.Html.escapeHtml(p).replace("\n", "<br>") + "</p>" }

/** A draft's HTML as text to edit in the phone's plain field. */
private fun htmlToText(html: String): String =
    android.text.Html.fromHtml(html, android.text.Html.FROM_HTML_MODE_COMPACT).toString().replace('\u00A0', ' ').trim()

/** What was typed in a message whose send can still be undone, so Undo brings it back exactly as it was. */
private data class Typed(val to: String, val cc: String, val bcc: String, val subject: String, val text: String,
                         val quoted: String, val signature: String, val from: String)

private val unsent = HashMap<Long, Typed>()

@Composable
fun MailComposeScreen(ws: Workspace, nav: Nav, message: Long? = null, mode: String? = null, draft: Long? = null) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var to by remember { mutableStateOf("") }
    var cc by remember { mutableStateOf("") }
    var bcc by remember { mutableStateOf("") }
    var copies by remember { mutableStateOf(false) }
    var subject by remember { mutableStateOf("") }
    var text by remember { mutableStateOf("") }
    var quoted by remember { mutableStateOf("") }
    var signature by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var ready by remember { mutableStateOf(message == null && draft == null) }
    var from by remember { mutableStateOf("") }
    var info by remember { mutableStateOf<app.kern.data.MailInfo?>(null) }
    var fromMenu by remember { mutableStateOf(false) }
    var m by remember { mutableStateOf(mode ?: "new") }
    var draftId by remember { mutableStateOf(draft) }
    // A draft opened from the Drafts folder: Discard leaves it there. Its HTML is sent as it was unless the text changed.
    var onServer by remember { mutableStateOf(false) }
    var loadedHtml by remember { mutableStateOf<String?>(null) }
    var loadedText by remember { mutableStateOf("") }
    var leaving by remember { mutableStateOf(false) }
    var asking by remember { mutableStateOf(false) }
    fun typed() = Typed(to, cc, bcc, subject, text, quoted, signature, from)
    // What was there before any typing (a new message starts empty); the signature and quote don't count.
    var start by remember { mutableStateOf(if (message == null && draft == null) Typed("", "", "", "", "", "", "", "") else null) }
    val changed = ready && start?.let { typed().copy(quoted = "", signature = "") != it.copy(quoted = "", signature = "") } == true

    LaunchedEffect(Unit) { info = runCatching { ws.kern.mailInfo() }.getOrNull() }
    LaunchedEffect(message, mode, draft) {
        if (draft != null) {
            val kept = unsent.remove(draft)
            try {
                val d = ws.kern.mailDraft(draft)
                m = d.mode
                if (kept != null) {
                    to = kept.to; cc = kept.cc; bcc = kept.bcc; subject = kept.subject; text = kept.text
                    quoted = kept.quoted; signature = kept.signature; from = kept.from
                } else {
                    to = addrsText(d.to); cc = addrsText(d.cc); bcc = addrsText(d.bcc); subject = d.subject; from = d.from
                    text = htmlToText(d.bodyHtml)
                    loadedHtml = d.bodyHtml; loadedText = text; onServer = true
                }
                copies = cc.isNotBlank() || bcc.isNotBlank()
            } catch (e: Exception) { snack.error(e) }
            start = typed(); ready = true
            return@LaunchedEffect
        }
        runCatching { ws.kern.api.get<kotlinx.serialization.json.JsonObject>("/mail/preferences") }.getOrNull()?.let { p ->
            val sig = p.str("signature") ?: ""
            val onReplies = p.str("signature_on_replies") != "false"
            if (sig.isNotBlank() && (m == "new" || onReplies)) signature = sig
        }
        if (message != null) {
            try {
                val p = ws.kern.mailPrefill(message, m)
                to = addrsText(p.to); cc = addrsText(p.cc); subject = p.subject; quoted = p.bodyHtml; from = p.from
            } catch (e: Exception) { snack.error(e) }
            start = typed(); ready = true
        }
    }

    fun fields(): app.kern.data.MailDraft {
        val body = loadedHtml?.takeIf { text == loadedText } ?: run {
            val sigHtml = if (signature.isNotBlank()) "<div><br></div><div>-- <br>" + android.text.Html.escapeHtml(signature).replace("\n", "<br>") + "</div>" else ""
            textToHtml(text) + sigHtml + quoted
        }
        return app.kern.data.MailDraft(id = draftId ?: 0, mode = m, to = parseAddrs(to), cc = parseAddrs(cc), bcc = parseAddrs(bcc),
            subject = subject, bodyHtml = body, from = from, inReplyTo = message)
    }

    /** "Sending…" with Undo for as long as the server holds the message back. */
    fun offerUndo(id: Long, seconds: Int) = snack.scope.launch {
        snack.host.currentSnackbarData?.dismiss()
        if (seconds <= 0) { snack.host.showSnackbar("Sending…"); return@launch }
        val r = kotlinx.coroutines.withTimeoutOrNull(seconds * 1000L) {
            snack.host.showSnackbar("Sending…", actionLabel = "Undo", duration = androidx.compose.material3.SnackbarDuration.Indefinite)
        }
        if (r != androidx.compose.material3.SnackbarResult.ActionPerformed) { unsent.remove(id); return@launch }
        try {
            ws.kern.mailUndoSend(id)
            nav.go("mail/compose?draft=$id")
        } catch (e: Exception) {
            unsent.remove(id)
            snack.error(e)
        }
    }

    fun send() = scope.launch {
        val all = parseAddrs(to) + parseAddrs(cc) + parseAddrs(bcc)
        if (all.isEmpty()) { snack.show("Add someone to send it to."); return@launch }
        badAddr(all)?.let { snack.show("“$it” isn't an email address."); return@launch }
        busy = true
        try {
            val d = ws.kern.mailSaveDraft(draftId, fields())
            draftId = d.id
            ws.kern.mailSendDraft(d.id)
            val seconds = info?.undoSeconds ?: 0
            if (seconds > 0) unsent[d.id] = typed()
            leaving = true
            nav.back()
            offerUndo(d.id, seconds)
        } catch (e: Exception) {
            snack.error(e)
        } finally { busy = false }
    }

    fun saveAndLeave() = scope.launch {
        busy = true
        try {
            ws.kern.mailSaveDraft(draftId, fields(), toServer = true)
            leaving = true
            nav.back()
            snack.show("Saved to Drafts")
        } catch (e: Exception) {
            snack.error(e)
        } finally { busy = false }
    }

    fun discardAndLeave() {
        val id = draftId
        if (id != null && !onServer) snack.scope.launch { runCatching { ws.kern.mailDeleteDraft(id) } }
        leaving = true
        nav.back()
    }

    fun leave() { if (changed && !leaving) asking = true else nav.back() }
    androidx.activity.compose.BackHandler(enabled = changed && !leaving) { asking = true }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding().imePadding()) {
        KTopBar(when (m) { "reply", "reply_all" -> "Reply"; "forward" -> "Forward"; else -> if (onServer) "Draft" else "New message" }, onBack = { leave() }) {
            IconButton(onClick = { send() }, enabled = ready && !busy, modifier = Modifier.padding(end = 4.dp)) { Icon(Icons.AutoMirrored.Outlined.Send, "Send", tint = kern.accent) }
        }
        if (!ready) Loading() else Column(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).padding(horizontal = 16.dp),
            verticalArrangement = Arrangement.spacedBy(8.dp)) {
            val i = info
            if (i != null && i.identities.isNotEmpty()) Box {
                val label = i.identities.firstOrNull { it.address.equals(from, true) }?.let { if (it.name.isBlank()) it.address else "${it.name} <${it.address}>" }
                    ?: if (i.fromName.isBlank()) i.address else "${i.fromName} <${i.address}>"
                Text("From  $label", style = MaterialTheme.typography.bodyMedium, color = kern.text2, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    modifier = Modifier.fillMaxWidth().clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp)).clickable { fromMenu = true }.padding(vertical = 10.dp, horizontal = 4.dp))
                DropdownMenu(expanded = fromMenu, onDismissRequest = { fromMenu = false }) {
                    DropdownMenuItem(text = { Text(i.address) }, onClick = { from = ""; fromMenu = false })
                    i.identities.forEach { id -> DropdownMenuItem(text = { Text(id.address) }, onClick = { from = id.address; fromMenu = false }) }
                }
            }
            val showCopies = copies || cc.isNotBlank() || bcc.isNotBlank() || m == "reply_all"
            Row(verticalAlignment = Alignment.CenterVertically) {
                KField(to, { to = it }, "To", modifier = Modifier.weight(1f), keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
                if (!showCopies) app.kern.ui.components.TextAction("Cc Bcc") { copies = true }
            }
            if (showCopies) {
                KField(cc, { cc = it }, "Cc", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
                KField(bcc, { bcc = it }, "Bcc", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
            }
            KField(subject, { subject = it }, "Subject")
            KField(text, { text = it }, "Message", singleLine = false, minLines = 8)
            if (signature.isNotBlank()) Text("-- \n$signature", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            if (quoted.isNotBlank()) Text(if (m == "forward") "The forwarded message is added below." else "The earlier message is quoted below your reply.",
                style = MaterialTheme.typography.bodySmall, color = kern.text3)
            // Room around Send so it isn't cramped against the fields or the keyboard.
            KButton(if (busy) "Sending…" else "Send", Modifier.fillMaxWidth().padding(top = 16.dp).height(52.dp), primary = true, enabled = !busy && ready,
                icon = Icons.AutoMirrored.Outlined.Send) { send() }
            Spacer(Modifier.height(32.dp).navigationBarsPadding())
        }
    }
    if (asking) androidx.compose.material3.AlertDialog(
        onDismissRequest = { asking = false },
        containerColor = kern.surface,
        title = { Text(if (onServer) "Keep your changes?" else "Keep this message?") },
        text = { Text("Saved drafts are in Drafts, here and on the web.", color = kern.text2) },
        confirmButton = { androidx.compose.material3.TextButton(onClick = { asking = false; saveAndLeave() }) { Text("Save draft", color = kern.accent) } },
        dismissButton = { androidx.compose.material3.TextButton(onClick = { asking = false; discardAndLeave() }) { Text("Discard", color = kern.danger) } },
    )
}
