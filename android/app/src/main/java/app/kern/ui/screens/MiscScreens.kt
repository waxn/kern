package app.kern.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
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
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.InsertDriveFile
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.AudioFile
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.DeleteForever
import androidx.compose.material.icons.outlined.FolderOpen
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.Movie
import androidx.compose.material.icons.outlined.PictureAsPdf
import androidx.compose.material.icons.outlined.Restore
import androidx.compose.material.icons.outlined.Settings
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Tag
import androidx.compose.material.icons.outlined.Unarchive
import androidx.compose.material.icons.automirrored.outlined.ViewQuilt
import androidx.compose.material.icons.outlined.AccountTree
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
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
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.Doc
import app.kern.data.LibraryFile
import app.kern.data.Tag
import app.kern.data.KernJson
import app.kern.data.BacklinkGroup
import app.kern.ui.Nav
import app.kern.ui.Session
import app.kern.ui.Workspace
import app.kern.ui.components.DocIcon
import app.kern.ui.components.DocRow
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KTopBar
import app.kern.ui.components.KernLogo
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.ago
import app.kern.ui.components.bytes
import app.kern.ui.doc.openUrl
import app.kern.ui.theme.kern
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray

@Composable
fun MoreScreen(ws: Workspace, nav: Nav) {
    val session by ws.session.collectAsState()
    val site by ws.site.collectAsState()
    val user = (session as? Session.SignedIn)?.user
    LazyColumn(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        item {
            Row(Modifier.fillMaxWidth().padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                KernLogo(36.dp)
                Spacer(Modifier.width(14.dp))
                Column(Modifier.weight(1f)) {
                    Text(site?.siteName ?: "Kern", style = MaterialTheme.typography.titleLarge)
                    Text(user?.username ?: "", style = MaterialTheme.typography.bodyMedium, color = kern.text3)
                }
                IconButton(onClick = { nav.go("search") }) { Icon(Icons.Outlined.Search, "Search", tint = kern.text2) }
            }
        }
        item { Heading("Workspace") }
        item {
            Bordered {
                MoreRow(Icons.Outlined.AutoAwesome, "Intelligence", kern.accent) { nav.go("intelligence") }
                MoreRow(Icons.Outlined.Bookmark, "Bookmarks") { nav.go("bookmarks") }
                MoreRow(Icons.AutoMirrored.Outlined.ViewQuilt, "Templates") { nav.go("templates") }
                MoreRow(Icons.Outlined.FolderOpen, "Files") { nav.go("files") }
                if (site?.allowGit != false) MoreRow(Icons.Outlined.AccountTree, "Git") { nav.go("git") }
                MoreRow(Icons.Outlined.Tag, "Tags") { nav.go("tags") }
            }
        }
        item { Heading("Storage") }
        item {
            Bordered {
                MoreRow(Icons.Outlined.Archive, "Archive") { nav.go("archive") }
                MoreRow(Icons.Outlined.Delete, "Trash") { nav.go("trash") }
            }
        }
        item { Heading("App") }
        item {
            Bordered {
                MoreRow(Icons.Outlined.Settings, "Settings") { nav.go("settings") }
            }
        }
        item { Spacer(Modifier.height(24.dp)) }
    }
}

@Composable
private fun MoreRow(icon: ImageVector, label: String, tint: androidx.compose.ui.graphics.Color? = null, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 14.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = tint ?: kern.text2, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(14.dp))
        Text(label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
        Icon(Icons.Outlined.ChevronRight, null, tint = kern.text3, modifier = Modifier.size(18.dp))
    }
}

@Composable
fun TagsScreen(ws: Workspace, nav: Nav) {
    var tags by remember { mutableStateOf<List<Tag>?>(null) }
    LaunchedEffect(Unit) { tags = runCatching { ws.kern.tags() }.getOrDefault(emptyList()) }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Tags", onBack = { nav.back() })
        when {
            tags == null -> Loading()
            tags!!.isEmpty() -> EmptyState(Icons.Outlined.Tag, "No tags yet", "Type #name in any page to tag it.")
            else -> LazyColumn {
                items(tags!!.sortedByDescending { it.docCount ?: 0 }, key = { it.id }) { t ->
                    Row(Modifier.fillMaxWidth().clickable { nav.go("tag/${t.id}") }.padding(horizontal = 20.dp, vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
                        Text("#", color = kern.named(t.color.ifBlank { "gray" }), style = MaterialTheme.typography.titleMedium)
                        Spacer(Modifier.width(10.dp))
                        Text(t.name, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                        Text("${t.docCount ?: 0}", style = MaterialTheme.typography.bodySmall, color = kern.text3)
                    }
                }
            }
        }
    }
}

@Composable
fun TagScreen(ws: Workspace, nav: Nav, id: String) {
    var tag by remember { mutableStateOf<Tag?>(null) }
    var docs by remember { mutableStateOf<List<Doc>>(emptyList()) }
    var blocks by remember { mutableStateOf<List<BacklinkGroup>>(emptyList()) }
    var err by remember { mutableStateOf<String?>(null) }
    val ctx = LocalContext.current
    LaunchedEffect(id) {
        try {
            val o = ws.kern.tag(id)
            tag = KernJson.decodeFromJsonElement(Tag.serializer(), o["tag"]!!)
            docs = (o["documents"] as? JsonArray)?.map { KernJson.decodeFromJsonElement(Doc.serializer(), it) } ?: emptyList()
            blocks = (o["blocks"] as? JsonArray)?.map { KernJson.decodeFromJsonElement(BacklinkGroup.serializer(), it) } ?: emptyList()
        } catch (e: Exception) { err = e.message }
    }
    val palette = kern.palette
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar(tag?.let { "#${it.name}" } ?: "Tag", onBack = { nav.back() }, subtitle = tag?.let { "${docs.size} pages" })
        when {
            err != null -> ErrorState(err!!) {}
            tag == null -> Loading()
            else -> LazyColumn {
                if (docs.isNotEmpty()) {
                    item { Heading("Pages") }
                    items(docs, key = { it.id }) { d -> DocRow(d, subtitle = ago(d.updatedAt)) { nav.doc(d.id) } }
                }
                if (blocks.isNotEmpty()) {
                    item { Heading("Mentions") }
                    items(blocks) { g ->
                        Column(Modifier.fillMaxWidth().clickable { nav.doc(g.doc.id) }.padding(horizontal = 20.dp, vertical = 10.dp)) {
                            Text(g.doc.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.titleSmall)
                            g.items.take(3).forEach {
                                Text(app.kern.data.Html.annotate(it.html, palette) { t -> nav.ref(t) { u -> openUrl(ctx, u) } }, style = MaterialTheme.typography.bodyMedium, color = kern.text2, maxLines = 3, overflow = TextOverflow.Ellipsis)
                            }
                        }
                    }
                }
                if (docs.isEmpty() && blocks.isEmpty()) item { EmptyState(Icons.Outlined.Tag, "Nothing tagged yet") }
            }
        }
    }
}

@Composable
fun TrashScreen(ws: Workspace, nav: Nav) {
    var docs by remember { mutableStateOf<List<Doc>?>(null) }
    var confirm by remember { mutableStateOf<Doc?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    suspend fun load() { docs = runCatching { ws.kern.trash() }.getOrDefault(emptyList()) }
    LaunchedEffect(Unit) { load() }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Trash", onBack = { nav.back() })
        when {
            docs == null -> Loading()
            docs!!.isEmpty() -> EmptyState(Icons.Outlined.Delete, "Trash is empty")
            else -> LazyColumn {
                items(docs!!, key = { it.id }) { d ->
                    DocRow(d, subtitle = "Deleted " + ago(d.trashedAt), trailing = {
                        Row {
                            IconButton(onClick = {
                                scope.launch { runCatching { ws.kern.restoreDoc(d.id) }.onSuccess { snack.show("Restored"); load(); ws.refresh() }.onFailure { snack.error(it) } }
                            }) { Icon(Icons.Outlined.Restore, "Restore", tint = kern.accent) }
                            IconButton(onClick = { confirm = d }) { Icon(Icons.Outlined.DeleteForever, "Delete forever", tint = kern.danger) }
                        }
                    }) {}
                }
            }
        }
    }
    confirm?.let { d ->
        AlertDialog(
            onDismissRequest = { confirm = null }, containerColor = kern.surface,
            title = { Text("Delete forever?") },
            text = { Text("“${d.displayTitle}” and everything inside it will be deleted permanently. This cannot be undone.") },
            confirmButton = { TextButton(onClick = { confirm = null; scope.launch { runCatching { ws.kern.deleteDoc(d.id) }.onSuccess { load() }.onFailure { snack.error(it) } } }) { Text("Delete", color = kern.danger) } },
            dismissButton = { TextButton(onClick = { confirm = null }) { Text("Cancel", color = kern.text2) } },
        )
    }
}

@Composable
fun ArchiveScreen(ws: Workspace, nav: Nav) {
    val tree by ws.tree.collectAsState()
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val docs = tree.filter { it.isArchived && it.entryOf == null }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Archive", onBack = { nav.back() })
        if (docs.isEmpty()) EmptyState(Icons.Outlined.Archive, "Nothing archived", "Archived pages leave the sidebar but stay searchable.")
        else LazyColumn {
            items(docs, key = { it.id }) { d ->
                DocRow(d, subtitle = ago(d.updatedAt), trailing = {
                    IconButton(onClick = { scope.launch { runCatching { ws.setArchived(d, false) }.onSuccess { snack.show("Unarchived") }.onFailure { snack.error(it) } } }) {
                        Icon(Icons.Outlined.Unarchive, "Unarchive", tint = kern.accent)
                    }
                }) { nav.doc(d.id) }
            }
        }
    }
}

@Composable
fun TemplatesScreen(ws: Workspace, nav: Nav) {
    var templates by remember { mutableStateOf<List<Doc>?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    LaunchedEffect(Unit) { templates = runCatching { ws.kern.templates() }.getOrDefault(emptyList()) }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Templates", onBack = { nav.back() })
        when {
            templates == null -> Loading()
            templates!!.isEmpty() -> EmptyState(Icons.AutoMirrored.Outlined.ViewQuilt, "No templates", "Save any page as a template from its ⋮ menu.")
            else -> LazyColumn {
                item { Text("Tap Use to create a new page from a template.", style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) }
                items(templates!!, key = { it.id }) { t ->
                    DocRow(t, trailing = {
                        TextButton(onClick = {
                            scope.launch { runCatching { ws.newPage(template = t.id) }.onSuccess { ws.refresh(); nav.doc(it.id) }.onFailure { snack.error(it) } }
                        }) { Text("Use", color = kern.accent) }
                    }) { nav.doc(t.id) }
                }
            }
        }
    }
}

@Composable
fun FilesScreen(ws: Workspace, nav: Nav) {
    var files by remember { mutableStateOf<List<LibraryFile>?>(null) }
    var type by remember { mutableStateOf<String?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    val ctx = LocalContext.current
    LaunchedEffect(type) { try { files = ws.kern.library(type); err = null } catch (e: Exception) { err = e.message } }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Files", onBack = { nav.back() }, subtitle = files?.let { "${it.size} files · ${bytes(it.sumOf { f -> f.size })}" })
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp, vertical = 4.dp)) {
            listOf(null to "All", "image" to "Images", "video" to "Video", "audio" to "Audio", "pdf" to "PDF", "other" to "Other").forEach { (k, l) ->
                Box(Modifier.padding(4.dp)) { Choice(l, type == k) { type = k } }
            }
        }
        when {
            files == null && err != null -> ErrorState(err!!) {}
            files == null -> Loading()
            files!!.isEmpty() -> EmptyState(Icons.Outlined.FolderOpen, "No files", "Files you upload to pages appear here.")
            else -> LazyColumn {
                items(files!!, key = { it.id }) { f ->
                    Row(Modifier.fillMaxWidth().clickable { ws.kern.api.abs(f.url)?.let { openUrl(ctx, it) } }.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.CenterVertically) {
                        Box(Modifier.size(48.dp).clip(RoundedCornerShape(8.dp)).background(kern.surface2), contentAlignment = Alignment.Center) {
                            if (f.mime.startsWith("image/")) AsyncImage(ws.kern.api.abs(f.url), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxSize())
                            else Icon(
                                when { f.mime.startsWith("video/") -> Icons.Outlined.Movie; f.mime.startsWith("audio/") -> Icons.Outlined.AudioFile; f.mime == "application/pdf" -> Icons.Outlined.PictureAsPdf; else -> Icons.AutoMirrored.Outlined.InsertDriveFile },
                                null, tint = kern.text3,
                            )
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(f.name, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text("${bytes(f.size)} · ${ago(f.createdAt)}", style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        }
                    }
                }
            }
        }
    }
}
