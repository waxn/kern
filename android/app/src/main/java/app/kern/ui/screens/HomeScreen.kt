package app.kern.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.lazy.LazyListScope
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.automirrored.outlined.NoteAdd
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.CardStats
import app.kern.data.Doc
import app.kern.data.Task
import app.kern.notify.SyncWorker
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.DocIcon
import app.kern.ui.components.KButton
import app.kern.ui.components.KernLogo
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Narrow
import app.kern.ui.components.ago
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import java.time.LocalTime

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun HomeScreen(ws: Workspace, nav: Nav) {
    val tree by ws.tree.collectAsState()
    val tags by ws.tags.collectAsState()
    val session by ws.session.collectAsState()
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    var tasks by remember { mutableStateOf(ws.settings.cachedTasks) }
    var cards by remember { mutableStateOf<CardStats?>(null) }
    var refreshing by remember { mutableStateOf(false) }

    suspend fun load() {
        runCatching { tasks = ws.kern.tasks("today") }
        runCatching { cards = ws.kern.cardStats() }
    }
    LaunchedEffect(Unit) { load() }

    val pages = tree.filter { it.entryOf == null && !it.isArchived && !it.empty }
    val favorites = pages.filter { it.isFavorite }
    val edited = pages.sortedByDescending { it.updatedAt }.take(15)
    val name = (session as? app.kern.ui.Session.SignedIn)?.user?.username ?: ""
    val hour = LocalTime.now().hour
    val greeting = when { hour < 5 -> "Good night"; hour < 12 -> "Good morning"; hour < 18 -> "Good afternoon"; else -> "Good evening" }

    fun toggle(t: Task) = scope.launch {
        tasks = tasks.map { if (it.id == t.id) it.copy(done = !t.done) else it }
        try { ws.kern.updateTask(t.id, "done" to !t.done); SyncWorker.refreshSoon(ctx) } catch (e: Exception) { snack.error(e) }
    }

    PullToRefreshBox(
        isRefreshing = refreshing,
        onRefresh = { scope.launch { refreshing = true; ws.refresh().join(); load(); refreshing = false } },
        modifier = Modifier.fillMaxSize().background(kern.bg),
    ) {
        Narrow {
            LazyColumn(Modifier.fillMaxSize().statusBarsPadding()) {
                item {
                    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                        KernLogo(26.dp)
                        Spacer(Modifier.width(10.dp))
                        Text(ws.site.collectAsState().value?.siteName ?: "Kern", style = MaterialTheme.typography.titleMedium, color = kern.text2, modifier = Modifier.weight(1f))
                        IconButton(onClick = { nav.go("search") }) { Icon(Icons.Outlined.Search, "Search", tint = kern.text2) }
                        IconButton(onClick = { nav.go("settings") }) { Icon(Icons.Outlined.Settings, "Settings", tint = kern.text2) }
                    }
                }
                item {
                    Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
                        Text(if (name.isNotEmpty()) "$greeting, $name" else greeting, style = MaterialTheme.typography.headlineLarge, color = kern.text)
                        Spacer(Modifier.height(4.dp))
                        Text("${pages.size} ${if (pages.size == 1) "page" else "pages"} · ${tags.size} ${if (tags.size == 1) "tag" else "tags"}", style = MaterialTheme.typography.bodyMedium, color = kern.text2)
                        Spacer(Modifier.height(16.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            KButton("New page", primary = true, icon = Icons.Outlined.Add) {
                                scope.launch { try { nav.doc(ws.newPage().id) } catch (e: Exception) { snack.error(e) } }
                            }
                            KButton("Search", icon = Icons.Outlined.Search) { nav.go("search") }
                            KButton("Ask", icon = Icons.Outlined.AutoAwesome) { nav.go("intelligence") }
                        }
                    }
                }

                // Today
                item { Heading("Today · ${tasks.count { !it.done }} ${if (tasks.count { !it.done } == 1) "task" else "tasks"}") { nav.tab("tasks") } }
                item {
                    Bordered {
                        if (tasks.isEmpty()) Text("Nothing due today.", color = kern.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(14.dp))
                        tasks.take(8).forEachIndexed { i, t ->
                            if (i > 0) app.kern.ui.components.Divider()
                            TaskRow(t, onToggle = { toggle(t) }) { nav.go("tasks?task=${t.id}") }
                        }
                        if (tasks.size > 8) Text("All ${tasks.size} tasks →", color = kern.text3, style = MaterialTheme.typography.bodySmall,
                            modifier = Modifier.fillMaxWidth().clickable { nav.tab("tasks") }.padding(12.dp))
                    }
                }

                // Flashcards
                cards?.let { c ->
                    item { Heading("Flashcards") }
                    item {
                        Bordered {
                            Row(Modifier.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Outlined.Layers, null, tint = kern.purple)
                                Spacer(Modifier.width(12.dp))
                                Column(Modifier.weight(1f)) {
                                    Text("${c.dueToday} due · ${c.newAvailable} new", fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.bodyLarge)
                                    Text("${c.reviewedToday} reviewed today", color = kern.text3, style = MaterialTheme.typography.bodySmall)
                                }
                                KButton("Study", primary = true, enabled = c.dueToday + c.newAvailable > 0) { nav.go("review") }
                            }
                        }
                    }
                }

                if (ws.treeLoaded.value && pages.isEmpty()) {
                    item {
                        app.kern.ui.components.EmptyState(Icons.AutoMirrored.Outlined.NoteAdd, "Your workspace is empty", "Create a page to start writing. Type [[ in a page to link pages together.")
                    }
                } else {
                    if (favorites.isNotEmpty()) {
                        item { Heading("Favorites") }
                        docList(favorites, ws, nav)
                    }
                    item { Heading("Recently edited") }
                    docList(edited, ws, nav)
                }
                item { Spacer(Modifier.height(24.dp)) }
            }
        }
    }
}

private fun LazyListScope.docList(docs: List<Doc>, ws: Workspace, nav: Nav) {
    item {
        Bordered {
            docs.forEachIndexed { i, d ->
                if (i > 0) app.kern.ui.components.Divider()
                Row(
                    Modifier.fillMaxWidth().clickable { nav.doc(d.id) }.padding(horizontal = 12.dp, vertical = 11.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    DocIcon(d, 16.dp)
                    Spacer(Modifier.width(8.dp))
                    Column(Modifier.weight(1f)) {
                        Text(d.displayTitle, maxLines = 1, overflow = TextOverflow.Ellipsis, color = if (d.title.isBlank()) kern.text3 else kern.text, style = MaterialTheme.typography.bodyLarge)
                        val path = ws.path(d.id).joinToString(" / ") { it.displayTitle }
                        if (path.isNotEmpty()) Text(path, maxLines = 1, overflow = TextOverflow.Ellipsis, color = kern.text3, style = MaterialTheme.typography.bodySmall)
                    }
                    Text(ago(d.updatedAt), color = kern.text3, style = MaterialTheme.typography.bodySmall)
                }
            }
        }
    }
}

@Composable
fun Heading(text: String, onMore: (() -> Unit)? = null) {
    Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 20.dp, top = 22.dp, bottom = 8.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = kern.text3, modifier = Modifier.weight(1f))
        if (onMore != null) Text("See all", style = MaterialTheme.typography.labelMedium, color = kern.accent, modifier = Modifier.clickable(onClick = onMore))
    }
}

@Composable
fun Bordered(modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val shape = RoundedCornerShape(12.dp)
    Column(
        modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(shape).background(kern.surface).border(1.dp, kern.border, shape)
    ) { content() }
}
