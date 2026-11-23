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
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.material.icons.outlined.Settings
import kotlinx.serialization.decodeFromString
import kotlinx.coroutines.async
import androidx.compose.material.icons.outlined.AutoAwesome
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
fun MailScreen(ws: Workspace, nav: Nav, initialView: String? = null, standalone: Boolean = false) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
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
    var parcels by remember { mutableStateOf<List<app.kern.data.MailPackage>>(emptyList()) }
    val me = status?.account?.str("address") ?: ""

    // Instant start: the Inbox as this phone last saw it, until the server answers.
    LaunchedEffect(Unit) {
        if (standalone) app.kern.notify.Notifications.clearMail(ctx) // you're looking at it now
        if (view == "inbox" && threads.isEmpty()) {
            ctx.app.settings.mailInboxCache?.let { c ->
                runCatching { app.kern.data.KernJson.decodeFromString<List<MailThread>>(c) }.getOrNull()?.let {
                    threads.addAll(it); loading = false
                }
            }
        }
    }

    fun apiView(v: String): String {
        if (v == "starred" || v == "all" || v in ROLE_VIEWS) return v // the server knows folders by role
        val f = folders.firstOrNull { "f${it.id}" == v }
        return if (f != null) "folder:${f.id}" else "all"
    }
    suspend fun load(more: Boolean = false) {
        try {
            val r = kotlinx.coroutines.coroutineScope {
                val f = if (folders.isEmpty()) async { runCatching { ws.kern.mailFolders().folders }.getOrNull() } else null
                val t = async { ws.kern.mailThreads(apiView(view), q = query.takeIf { searching && it.isNotBlank() }, cursor = if (more) next else null) }
                f?.await()?.let { folders = it }
                t.await()
            }
            if (!more) threads.clear()
            threads.addAll(r.threads)
            next = r.next
            error = null
            if (!more && view == "inbox" && !searching) runCatching {
                ctx.app.settings.mailInboxCache = app.kern.data.KernJson.encodeToString(kotlinx.serialization.builtins.ListSerializer(MailThread.serializer()), r.threads)
            }
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
                if (changed && !searching) load()
                if (r.events.any { it.kind == "package" }) loadParcels()
                if (changed && view == "inbox") app.kern.notify.Notifications.clearMail(ctx)
            } catch (e: kotlinx.coroutines.CancellationException) {
                throw e
            } catch (_: Exception) {
                kotlinx.coroutines.delay(5_000)
            }
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
                KTopBar(title, onBack = if (standalone) null else ({ nav.back() }), subtitle = me.ifBlank { null }) {
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
                                Pill(label, if (v == view) kern.accent else kern.text2, onClick = { view = v })
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
                                folders = emptyList(); load()
                                kotlinx.coroutines.delay(900); load() // the check usually lands within a second
                                refreshing = false
                            }
                        },
                        modifier = Modifier.fillMaxSize(),
                    ) {
                        when {
                            loading && threads.isEmpty() -> Loading()
                            error != null && threads.isEmpty() -> ErrorState(error!!) { scope.launch { loading = true; load() } }
                            threads.isEmpty() -> EmptyState(Icons.Outlined.Email, if (searching) "No matches" else "Nothing here", null)
                            else -> LazyColumn(Modifier.fillMaxSize()) {
                                if (view == "inbox" && !searching && parcels.isNotEmpty()) item(key = "parcels") {
                                    ParcelStrip(parcels) { p -> nav.go(p.threadId?.let { "mail/thread/$it" } ?: "mail/packages") }
                                }
                                items(threads, key = { it.id }) { t ->
                                    SwipeRow(
                                        t,
                                        canArchive = view != "archive" && view != "trash" && view != "junk",
                                        onArchive = {
                                            val inbox = folders.firstOrNull { it.role == view }?.id
                                            threads.remove(t)
                                            scope.launch {
                                                try {
                                                    ws.kern.mailAction(listOf(t.id), "archive", *(if (inbox != null) arrayOf("context" to inbox) else emptyArray()))
                                                    val r = snack.host.showSnackbar("Archived", actionLabel = "Undo", duration = androidx.compose.material3.SnackbarDuration.Short)
                                                    if (r == androidx.compose.material3.SnackbarResult.ActionPerformed) {
                                                        ws.kern.mailAction(listOf(t.id), "inbox"); load()
                                                    }
                                                } catch (e: Exception) { snack.error(e); load() }
                                            }
                                        },
                                        onToggleRead = {
                                            val i = threads.indexOf(t)
                                            val read = t.unread > 0
                                            if (i >= 0) threads[i] = t.copy(unread = if (read) 0 else 1)
                                            scope.launch { runCatching { ws.kern.mailAction(listOf(t.id), if (read) "read" else "unread") }.onFailure { snack.error(it) } }
                                        },
                                    ) { ThreadRow(t, me) { nav.go("mail/thread/${t.id}") } }
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
    }
}

private val ROLE_VIEWS = setOf("inbox", "snoozed", "drafts", "sent", "archive", "junk", "trash")

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

/** One short line about when it arrives (like the web's packages.js arrivalLabel). */
internal fun arrival(p: app.kern.data.MailPackage): String {
    val today = LocalDate.now()
    val at = runCatching { ZonedDateTime.parse(p.statusAt).withZoneSameInstant(java.time.ZoneId.systemDefault()).toLocalDate() }.getOrNull()
    return when (p.status) {
        "delivered" -> when (at) { today -> "Delivered today"; today.minusDays(1) -> "Delivered yesterday"; null -> "Delivered"; else -> "Delivered ${at.dayOfMonth}/${at.monthValue}" }
        "ready_for_pickup" -> "Ready to pick up"
        "out_for_delivery" -> if (at == null || at == today) "Arriving today" else "Out for delivery"
        "exception" -> "Needs attention"
        else -> {
            val exp = p.expected?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
            when {
                exp == null -> p.statusLabel
                exp == today -> "Arriving today"
                exp == today.plusDays(1) -> "Arriving tomorrow"
                exp.isBefore(today) -> "Expected ${java.time.temporal.ChronoUnit.DAYS.between(exp, today)} d ago"
                java.time.temporal.ChronoUnit.DAYS.between(today, exp) < 7 -> "Arriving " + exp.dayOfWeek.name.lowercase().replaceFirstChar { it.uppercase() }
                else -> "Arriving ${exp.dayOfMonth}/${exp.monthValue}"
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

/** Swipe right to archive, left to mark read/unread (like Gmail). */
@Composable
private fun SwipeRow(t: MailThread, canArchive: Boolean, onArchive: () -> Unit, onToggleRead: () -> Unit, content: @Composable () -> Unit) {
    val state = androidx.compose.material3.rememberSwipeToDismissBoxState(
        confirmValueChange = { v ->
            when (v) {
                androidx.compose.material3.SwipeToDismissBoxValue.StartToEnd -> { if (canArchive) onArchive(); canArchive }
                androidx.compose.material3.SwipeToDismissBoxValue.EndToStart -> { onToggleRead(); false }
                else -> false
            }
        },
        positionalThreshold = { it * 0.35f },
    )
    androidx.compose.material3.SwipeToDismissBox(
        state,
        enableDismissFromStartToEnd = canArchive,
        backgroundContent = {
            val dir = state.dismissDirection
            val archive = dir == androidx.compose.material3.SwipeToDismissBoxValue.StartToEnd
            val color = if (archive) kern.green else kern.accent
            Row(Modifier.fillMaxSize().background(kern.tint(color)).padding(horizontal = 24.dp),
                horizontalArrangement = if (archive) Arrangement.Start else Arrangement.End, verticalAlignment = Alignment.CenterVertically) {
                if (dir != androidx.compose.material3.SwipeToDismissBoxValue.Settled) {
                    Icon(if (archive) Icons.Outlined.Archive else Icons.Outlined.MarkEmailUnread, null, tint = color)
                    Spacer(Modifier.width(8.dp))
                    Text(if (archive) "Archive" else if (t.unread > 0) "Mark read" else "Mark unread", color = color, style = MaterialTheme.typography.labelLarge)
                }
            }
        },
    ) { Box(Modifier.background(kern.bg)) { content() } }
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
            if (t.hit.isNotBlank()) Text(hitText(t.hit, kern.text), maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
            else Text(t.snippet, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
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
    val ctx = LocalContext.current
    LaunchedEffect(id) {
        app.kern.notify.Notifications.cancelMailThread(ctx, id)
        load()
    }
    var asking by remember { mutableStateOf(false) }
    fun ask() = scope.launch {
        if (asking) return@launch
        asking = true
        try { nav.go("chat/${ws.kern.createChat().id}?mail=$id") } catch (e: Exception) { snack.error(e) }
        asking = false
    }

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
                IconButton(onClick = { ask() }, enabled = !asking) { Icon(Icons.Outlined.AutoAwesome, "Ask Intelligence about this email", tint = kern.accent) }
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
    var original by remember(m.id) { mutableStateOf(false) }
    val ctx = LocalContext.current
    // The server fits the email to the theme (no white sheet; dark mail keeps its colors), like the web app.
    val colors = if (original) null else if (kern.dark) (if (ctx.app.settings.mailDarkEmails) "dark" else null) else "light"
    LaunchedEffect(m.id, expanded, colors) {
        if (expanded) body = runCatching { ws.kern.mailBody(m.id, colors) }.getOrElse { failed = true; body }
    }
    Column(Modifier.padding(horizontal = 12.dp, vertical = 4.dp).fillMaxWidth()
        .clip(androidx.compose.foundation.shape.RoundedCornerShape(12.dp))
        .border(1.dp, kern.border, androidx.compose.foundation.shape.RoundedCornerShape(12.dp))) {
        Row(Modifier.fillMaxWidth().clickable(onClick = onToggle).padding(12.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(if (m.fromMe) "Me" else m.from.display.ifBlank { "(unknown sender)" }, fontWeight = FontWeight.SemiBold, maxLines = 1, overflow = TextOverflow.Ellipsis,
                    style = MaterialTheme.typography.bodyMedium)
                Text(if (expanded) "to " + (m.to + m.cc).joinToString(", ") { it.display }.ifBlank { "(no recipients)" } else m.snippet,
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
                    val hasFiles = m.attachments.any { !it.inline }
                    val blank = b.html == null && (b.text ?: "").isBlank()
                    if (blank && !hasFiles) Text("No message text.", style = MaterialTheme.typography.bodySmall, color = kern.text3,
                        modifier = Modifier.padding(start = 12.dp, end = 12.dp, bottom = 12.dp))
                    else if (!blank) {
                        if (b.html != null && (original || b.colors in setOf("adapted", "dark", "light"))) {
                            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp), horizontalArrangement = Arrangement.End) {
                                Text(if (original) "Fit to theme" else "Original colors", style = MaterialTheme.typography.labelMedium, color = kern.text3,
                                    modifier = Modifier.clip(androidx.compose.foundation.shape.RoundedCornerShape(8.dp)).clickable { original = !original }.padding(horizontal = 8.dp, vertical = 4.dp))
                            }
                        }
                        EmailView(b, original = original)
                    }
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
private fun EmailView(b: MailBody, original: Boolean = false) {
    val ctx = LocalContext.current
    val k = kern
    val inner = b.html ?: b.textHtml ?: android.text.Html.escapeHtml(b.text ?: "")
    fun hex(c: androidx.compose.ui.graphics.Color) = String.format("#%06X", 0xFFFFFF and c.toArgb())
    // The email sits on the app's own background: the server already fitted its colors to the theme
    // (backend/mail/colors.py), so nothing is inverted here. Original colors: as sent, on white.
    val asSent = original && b.html != null
    val bg = if (asSent) "#ffffff" else "transparent"
    val fg = if (asSent) "#222222" else hex(k.text)
    val link = if (asSent || !k.dark) "#2f4ad0" else "#8ab4f8"
    val scheme = if (k.dark && !asSent) "dark" else "light"
    val page = """<!doctype html><html style="color-scheme:$scheme"><head><meta charset="utf-8">
        <meta http-equiv="Content-Security-Policy" content="default-src 'none'; style-src 'unsafe-inline'; img-src data:">
        <meta name="color-scheme" content="$scheme">
        <meta name="viewport" content="width=device-width, initial-scale=1">
        <style>html,body{margin:0;padding:4px 10px 10px;background:$bg;color:$fg;font:15px/1.5 sans-serif;overflow-wrap:anywhere}
        a{color:$link}img{max-width:100%;height:auto}pre{white-space:pre-wrap}blockquote{margin:0 0 0 .6em;padding-left:.8em;border-left:2px solid #888;opacity:.8}</style>
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
                setBackgroundColor(if (asSent) android.graphics.Color.WHITE else android.graphics.Color.TRANSPARENT)
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
    var from by remember { mutableStateOf("") }
    var info by remember { mutableStateOf<app.kern.data.MailInfo?>(null) }
    var fromMenu by remember { mutableStateOf(false) }
    val m = mode ?: "new"

    LaunchedEffect(Unit) { info = runCatching { ws.kern.mailInfo() }.getOrNull() }
    LaunchedEffect(message, mode) {
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
            ready = true
        }
    }

    fun send() = scope.launch {
        val rcpt = parseAddrs(to)
        if (rcpt.isEmpty() || rcpt.any { "@" !in it.addr }) { snack.show("Check the recipients."); return@launch }
        busy = true
        try {
            val sigHtml = if (signature.isNotBlank()) "<div><br></div><div>-- <br>" + android.text.Html.escapeHtml(signature).replace("\n", "<br>") + "</div>" else ""
            ws.kern.mailSend(m, message, rcpt, parseAddrs(cc), subject, textToHtml(text) + sigHtml + quoted, from)
            snack.show("Sending…")
            nav.back()
        } catch (e: Exception) {
            snack.error(e)
        } finally { busy = false }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding().imePadding()) {
        KTopBar(when (m) { "reply", "reply_all" -> "Reply"; "forward" -> "Forward"; else -> "New message" }, onBack = { nav.back() }) {
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
            KField(to, { to = it }, "To", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
            if (cc.isNotBlank() || m == "reply_all") KField(cc, { cc = it }, "Cc", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email))
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
}
