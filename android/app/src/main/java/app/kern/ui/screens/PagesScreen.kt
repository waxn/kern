package app.kern.ui.screens

import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.CalendarMonth
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Edit
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.LayersClear
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.ViewKanban
import androidx.compose.material.icons.automirrored.outlined.NoteAdd
import androidx.compose.material.icons.automirrored.outlined.ViewQuilt
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.FloatingActionButton
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.Doc
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.DocIcon
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KField
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.SectionLabel
import app.kern.ui.doc.KSheet
import app.kern.ui.doc.SheetItem
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun PagesScreen(ws: Workspace, nav: Nav) {
    val tree by ws.tree.collectAsState()
    val loaded by ws.treeLoaded.collectAsState()
    val err by ws.treeError.collectAsState()
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var open by rememberSaveable { mutableStateOf(setOf<String>()) }
    var menu by remember { mutableStateOf<Doc?>(null) }
    var creating by remember { mutableStateOf(false) }
    var renaming by remember { mutableStateOf<Doc?>(null) }
    var refreshing by remember { mutableStateOf(false) }

    val live = tree.filter { it.entryOf == null && !it.isArchived }
    val byParent = live.groupBy { it.parent }
    val favorites = live.filter { it.isFavorite }
    val databases = live.filter { it.database != null }

    fun create(kind: String) = scope.launch {
        creating = false
        try {
            when (kind) {
                "page" -> nav.doc(ws.newPage().id)
                "group" -> nav.doc(ws.newPage(kind = "group", title = "New group").id)
                else -> {
                    val db = ws.kern.createDatabase("", kind.takeIf { it != "database" })
                    ws.refresh().join()
                    nav.doc(db.database.page)
                }
            }
        } catch (e: Exception) { snack.error(e) }
    }

    Box(Modifier.fillMaxSize().background(kern.bg)) {
        Column(Modifier.fillMaxSize().statusBarsPadding()) {
            Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
                Text("Pages", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.weight(1f))
                IconButton(onClick = { nav.go("search") }) { Icon(Icons.Outlined.Search, "Search", tint = kern.text2) }
            }
            PullToRefreshBox(refreshing, { scope.launch { refreshing = true; ws.refresh().join(); refreshing = false } }, Modifier.weight(1f)) {
                when {
                    !loaded && err != null -> ErrorState(err!!) { ws.refresh() }
                    !loaded -> Loading()
                    live.isEmpty() -> EmptyState(Icons.AutoMirrored.Outlined.NoteAdd, "No pages yet", "Create your first page.", action = "New page" to { create("page") })
                    else -> LazyColumn(Modifier.fillMaxSize()) {
                        if (favorites.isNotEmpty()) {
                            item { SectionLabel("Favorites") }
                            items(favorites, key = { "f" + it.id }) { d -> TreeRow(d, 0, false, false, { nav.doc(d.id) }, { menu = d }, {}) }
                        }
                        if (databases.isNotEmpty()) {
                            item { SectionLabel("Databases") }
                            items(databases, key = { "d" + it.id }) { d -> TreeRow(d, 0, false, false, { nav.doc(d.id) }, { menu = d }, {}) }
                        }
                        item { SectionLabel("Workspace") }
                        val flat = mutableListOf<Pair<Doc, Int>>()
                        fun walk(parent: String?, depth: Int) {
                            for (d in byParent[parent].orEmpty().sortedBy { it.position }) {
                                flat += d to depth
                                if (d.id in open) walk(d.id, depth + 1)
                            }
                        }
                        walk(null, 0)
                        items(flat, key = { "t" + it.first.id }) { (d, depth) ->
                            val hasKids = byParent[d.id].orEmpty().isNotEmpty()
                            TreeRow(d, depth, hasKids, d.id in open, { nav.doc(d.id) }, { menu = d }) {
                                open = if (d.id in open) open - d.id else open + d.id
                            }
                        }
                        item {
                            Row(Modifier.fillMaxWidth().clickable { nav.go("archive") }.padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Outlined.Archive, null, tint = kern.text3, modifier = Modifier.size(18.dp))
                                Spacer(Modifier.width(12.dp))
                                Text("Archive · ${tree.count { it.isArchived }}", color = kern.text3, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                        item { Spacer(Modifier.height(96.dp)) }
                    }
                }
            }
        }
        FloatingActionButton(
            onClick = { creating = true }, containerColor = kern.accent, contentColor = kern.onAccent,
            modifier = Modifier.align(Alignment.BottomEnd).padding(20.dp),
        ) { Icon(Icons.Outlined.Add, "New") }
    }

    if (creating) KSheet({ creating = false }, "Create") {
        SheetItem(Icons.Outlined.Description, "Page") { create("page") }
        SheetItem(Icons.Outlined.Dashboard, "Group") { create("group") }
        SheetItem(Icons.Outlined.Storage, "Database") { create("database") }
        SheetItem(Icons.Outlined.ViewKanban, "Kanban board") { create("kanban") }
        SheetItem(Icons.Outlined.CalendarMonth, "Calendar") { create("calendar") }
        SheetItem(Icons.AutoMirrored.Outlined.ViewQuilt, "From a template…") { creating = false; nav.go("templates") }
    }

    menu?.let { d ->
        KSheet({ menu = null }, d.displayTitle) {
            SheetItem(Icons.Outlined.Add, "Add sub-page") {
                menu = null
                scope.launch { runCatching { ws.newPage(parent = d.id) }.onSuccess { open = open + d.id; nav.doc(it.id) }.onFailure { snack.error(it) } }
            }
            SheetItem(if (d.isFavorite) Icons.Outlined.Star else Icons.Outlined.StarOutline, if (d.isFavorite) "Remove from favorites" else "Add to favorites") {
                menu = null; scope.launch { runCatching { ws.setFavorite(d, !d.isFavorite) }.onFailure { snack.error(it) } }
            }
            SheetItem(Icons.Outlined.Edit, "Rename") { menu = null; renaming = d }
            SheetItem(Icons.Outlined.ContentCopy, "Duplicate") { menu = null; scope.launch { runCatching { ws.duplicate(d) }.onFailure { snack.error(it) } } }
            SheetItem(Icons.Outlined.Archive, "Archive") { menu = null; scope.launch { runCatching { ws.setArchived(d, true) }.onSuccess { snack.show("Archived") }.onFailure { snack.error(it) } } }
            SheetItem(Icons.Outlined.Delete, "Move to trash", danger = true) { menu = null; scope.launch { runCatching { ws.trash(d) }.onSuccess { snack.show("Moved to trash") }.onFailure { snack.error(it) } } }
        }
    }

    renaming?.let { d ->
        var t by remember(d.id) { mutableStateOf(d.title) }
        AlertDialog(
            onDismissRequest = { renaming = null },
            containerColor = kern.surface,
            title = { Text("Rename") },
            text = { KField(t, { t = it }, "Title") },
            confirmButton = { TextButton(onClick = { renaming = null; scope.launch { runCatching { ws.rename(d, t) }.onFailure { snack.error(it) } } }) { Text("Save", color = kern.accent) } },
            dismissButton = { TextButton(onClick = { renaming = null }) { Text("Cancel", color = kern.text2) } },
        )
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TreeRow(d: Doc, depth: Int, hasKids: Boolean, expanded: Boolean, onClick: () -> Unit, onLong: () -> Unit, onToggle: () -> Unit) {
    Row(
        Modifier.fillMaxWidth().combinedClickable(onClick = onClick, onLongClick = onLong).heightIn(min = 44.dp).padding(start = (8 + depth * 18).dp, end = 16.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        Box(Modifier.size(36.dp).clip(CircleShape).clickable(enabled = hasKids, onClick = onToggle), contentAlignment = Alignment.Center) {
            if (hasKids) Icon(if (expanded) Icons.Outlined.ExpandMore else Icons.Outlined.ChevronRight, if (expanded) "Collapse" else "Expand", tint = kern.text3, modifier = Modifier.size(18.dp))
        }
        DocIcon(d, 17.dp)
        Spacer(Modifier.width(8.dp))
        Text(d.displayTitle, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge, color = if (d.title.isBlank()) kern.text3 else kern.text, modifier = Modifier.weight(1f))
        if (d.isFavorite && depth >= 0) Icon(Icons.Outlined.Star, null, tint = kern.accent.copy(alpha = 0.7f), modifier = Modifier.size(14.dp))
    }
}
