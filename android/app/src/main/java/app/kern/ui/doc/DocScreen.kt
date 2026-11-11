package app.kern.ui.doc

import android.content.Intent
import androidx.activity.compose.BackHandler
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
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
import androidx.compose.foundation.lazy.grid.GridCells
import androidx.compose.foundation.lazy.grid.LazyVerticalGrid
import androidx.compose.foundation.lazy.grid.items
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.FormatIndentDecrease
import androidx.compose.material.icons.automirrored.outlined.FormatIndentIncrease
import androidx.compose.material.icons.automirrored.outlined.FormatListBulleted
import androidx.compose.material.icons.automirrored.outlined.OpenInNew
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Archive
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.CheckBox
import androidx.compose.material.icons.outlined.Code
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.automirrored.outlined.DriveFileMove
import androidx.compose.material.icons.outlined.FormatBold
import androidx.compose.material.icons.outlined.FormatItalic
import androidx.compose.material.icons.outlined.FormatQuote
import androidx.compose.material.icons.outlined.FormatStrikethrough
import androidx.compose.material.icons.outlined.FormatListNumbered
import androidx.compose.material.icons.outlined.Functions
import androidx.compose.material.icons.outlined.HorizontalRule
import androidx.compose.material.icons.outlined.Image
import androidx.compose.material.icons.outlined.KeyboardArrowDown
import androidx.compose.material.icons.outlined.KeyboardArrowUp
import androidx.compose.material.icons.outlined.KeyboardHide
import androidx.compose.material.icons.outlined.Lightbulb
import androidx.compose.material.icons.outlined.Link
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.MoreVert
import androidx.compose.material.icons.automirrored.outlined.Notes
import androidx.compose.material.icons.outlined.Share
import androidx.compose.material.icons.outlined.Star
import androidx.compose.material.icons.outlined.StarOutline
import androidx.compose.material.icons.outlined.Style
import androidx.compose.material.icons.outlined.Tag
import androidx.compose.material.icons.outlined.TaskAlt
import androidx.compose.material.icons.outlined.Title
import androidx.compose.material.icons.outlined.TextFields
import androidx.compose.material.icons.outlined.UnfoldMore
import androidx.compose.material.icons.outlined.Highlight
import androidx.compose.material.icons.outlined.Repeat
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Text
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.DisposableEffect
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.platform.LocalFocusManager
import androidx.compose.ui.platform.LocalSoftwareKeyboardController
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.lifecycle.viewmodel.compose.viewModel
import app.kern.data.BacklinkGroup
import app.kern.data.Doc
import app.kern.data.Html
import app.kern.data.Suggestion
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.DocIcon
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KField
import app.kern.ui.components.ListRow
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.Pill
import app.kern.ui.theme.kern
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

data class BlockKind(val type: String, val label: String, val icon: ImageVector, val props: JsonObject = JsonObject(emptyMap()))

val BLOCK_KINDS = listOf(
    BlockKind("paragraph", "Text", Icons.Outlined.TextFields),
    BlockKind("h1", "Heading 1", Icons.Outlined.Title),
    BlockKind("h2", "Heading 2", Icons.Outlined.Title),
    BlockKind("h3", "Heading 3", Icons.Outlined.Title),
    BlockKind("bullet", "Bulleted list", Icons.AutoMirrored.Outlined.FormatListBulleted),
    BlockKind("numbered", "Numbered list", Icons.Outlined.FormatListNumbered),
    BlockKind("todo", "Checklist", Icons.Outlined.CheckBox),
    BlockKind("toggle", "Toggle list", Icons.Outlined.UnfoldMore),
    BlockKind("quote", "Quote", Icons.Outlined.FormatQuote),
    BlockKind("callout", "Callout", Icons.Outlined.Lightbulb),
    BlockKind("code", "Code", Icons.Outlined.Code),
    BlockKind("divider", "Divider", Icons.Outlined.HorizontalRule),
    BlockKind("equation", "Equation", Icons.Outlined.Functions),
    BlockKind("image", "Image", Icons.Outlined.Image),
    BlockKind("bookmark", "Bookmark", Icons.Outlined.Bookmark),
)

private sealed interface Sheet {
    data object Types : Sheet
    data object PageMenu : Sheet
    data class BlockMenu(val id: String) : Sheet
    data class Backlinks(val block: String?) : Sheet
    data class Picker(val kind: String) : Sheet
    data object Icon : Sheet
    data object Tags : Sheet
    data object Move : Sheet
    data class Link(val id: String) : Sheet
    data class Media(val type: String, val after: String?) : Sheet
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun DocScreen(ws: Workspace, nav: Nav, id: String) {
    val vm: DocModel = viewModel(key = "doc-$id") { DocModel(ws, id) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val keyboard = LocalSoftwareKeyboardController.current
    val focusManager = LocalFocusManager.current
    val tree by ws.tree.collectAsState()
    val tags by ws.tags.collectAsState()
    val size by ws.settings.editorSize.collectAsState()
    var sheet by remember { mutableStateOf<Sheet?>(null) }
    val doc = vm.payload?.document?.let { p -> tree.firstOrNull { it.id == p.id }?.let { t -> p.copy(isFavorite = t.isFavorite, icon = t.icon, tags = t.tags, isArchived = t.isArchived) } ?: p }
    val listState = rememberLazyListState()

    fun done() { vm.stopEditing(); focusManager.clearFocus(); keyboard?.hide() }
    BackHandler(vm.focused != null) { done() }

    // Leaving an untouched new page throws it away, like the web app.
    DisposableEffect(id) {
        onDispose {
            if (vm.payload != null && vm.isEmptyDoc() && vm.payload?.document?.kind == "page" && vm.payload?.document?.database == null) {
                scope.launch { ws.kern.discardDoc(id) }
                ws.removeLocal(listOf(id))
            }
        }
    }

    Scaffold(
        containerColor = kern.bg,
        topBar = {
            TopAppBar(
                title = {
                    Column {
                        val path = ws.path(id)
                        Text(
                            if (path.isEmpty()) (doc?.let { if (it.entryOf != null) "Database entry" else if (it.isTemplate) "Template" else "Page" } ?: "") else path.joinToString(" / ") { it.displayTitle },
                            style = MaterialTheme.typography.bodySmall, color = kern.text3, maxLines = 1, overflow = TextOverflow.Ellipsis,
                        )
                        Text(vm.status.ifEmpty { doc?.updatedAt?.let { "Edited " + app.kern.ui.components.ago(it) } ?: "" }, style = MaterialTheme.typography.labelSmall, color = kern.text3)
                    }
                },
                navigationIcon = { IconButton(onClick = { done(); nav.back() }) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") } },
                actions = {
                    if (doc != null) {
                        IconButton(onClick = { scope.launch { runCatching { ws.setFavorite(doc, !doc.isFavorite) }.onFailure { snack.error(it) } } }) {
                            Icon(if (doc.isFavorite) Icons.Outlined.Star else Icons.Outlined.StarOutline, "Favorite", tint = if (doc.isFavorite) kern.accent else kern.text2)
                        }
                        IconButton(onClick = {
                            done()
                            scope.launch { runCatching { ws.kern.createChat() }.onSuccess { nav.go("chat/${it.id}?page=$id") }.onFailure { snack.error(it) } }
                        }) { Icon(Icons.Outlined.AutoAwesome, "Ask Intelligence about this page", tint = kern.text2) }
                        IconButton(onClick = { sheet = Sheet.PageMenu }) { Icon(Icons.Outlined.MoreVert, "More") }
                    }
                },
                colors = TopAppBarDefaults.topAppBarColors(containerColor = kern.bg),
            )
        },
        bottomBar = {
            if (vm.focused != null && vm.blocks[vm.focused]?.type in TEXT_TYPES) {
                Toolbar(vm, onTypes = { sheet = Sheet.Types }, onPage = { sheet = Sheet.Picker("doc") }, onTag = { sheet = Sheet.Picker("tag") }, onLink = { sheet = Sheet.Link(vm.focused!!) }, onDone = { done() })
            }
        },
    ) { pad ->
        when {
            vm.payload == null && vm.error != null -> Box(Modifier.padding(pad)) { ErrorState(vm.error!!) { vm.load() } }
            vm.payload == null || doc == null -> Loading(Modifier.padding(pad))
            else -> {
                val rows = vm.rows()
                val toolbar = vm.focused != null && vm.blocks[vm.focused]?.type in TEXT_TYPES
                // The toolbar already sits above the keyboard; otherwise make room for it here.
                LazyColumn(Modifier.fillMaxSize().padding(pad).then(if (toolbar) Modifier else Modifier.imePadding()), state = listState) {
                    item(key = "header") { Header(vm, ws, nav, doc, tags, onIcon = { sheet = Sheet.Icon }, onTags = { sheet = Sheet.Tags }) }
                    if (doc.database != null) item(key = "db") { DatabaseView(ws, nav, doc.database) }
                    if (doc.kind == "group") item(key = "group") { GroupChildren(ws, nav, doc) }
                    items(rows, key = { it.block.id }) { r ->
                        BlockItem(vm, ws, nav, r, size) { target ->
                            sheet = if (target.startsWith("backlinks:")) Sheet.Backlinks(target.removePrefix("backlinks:")) else Sheet.BlockMenu(target)
                        }
                    }
                    item(key = "tail") {
                        // Tapping below the last block continues writing.
                        Box(Modifier.fillMaxWidth().height(140.dp).clickable {
                            val last = rows.lastOrNull()?.block
                            if (last != null && last.type in TEXT_TYPES && last.parent == null && vm.markupOf(last).isEmpty()) vm.startEditing(last.id)
                            else vm.insertAfter(rows.lastOrNull { it.depth == 0 }?.block?.id)
                        })
                    }
                    if ((vm.payload?.backlinkCount ?: 0) > 0) item(key = "backlinks") {
                        BacklinksSection(ws, nav, id, vm.payload!!.backlinkCount)
                    }
                    item { Spacer(Modifier.height(40.dp)) }
                }
            }
        }
    }

    when (val s = sheet) {
        null -> Unit
        Sheet.Types -> BlockTypeSheet({ sheet = null }) { kind ->
            sheet = null
            val f = vm.focused
            when {
                kind.type in TEXT_TYPES && f != null -> vm.setType(f, kind.type)
                kind.type == "image" || kind.type == "bookmark" -> sheet = Sheet.Media(kind.type, f)
                else -> vm.insertAfter(f, kind.type, kind.props)
            }
        }
        Sheet.PageMenu -> PageMenu(ws, nav, vm, doc!!, onClose = { sheet = null }, onMove = { sheet = Sheet.Move }, onBacklinks = { sheet = Sheet.Backlinks(null) })
        is Sheet.BlockMenu -> BlockMenu(vm, s.id, { sheet = null }, onType = { vm.startEditing(s.id); sheet = Sheet.Types }, onBacklinks = { sheet = Sheet.Backlinks(s.id) }, onTask = {
            sheet = null
            scope.launch {
                vm.flush()
                runCatching { ws.kern.api.post<app.kern.data.Task>("/tasks", app.kern.data.jsonOf("block" to s.id, "title" to "")) }
                    .onSuccess { snack.show("Added to Tasks"); vm.load() }.onFailure { snack.error(it) }
            }
        })
        is Sheet.Backlinks -> BacklinksSheet(ws, nav, id, s.block) { sheet = null }
        is Sheet.Picker -> RefPicker(ws, s.kind, { sheet = null }) { sug ->
            sheet = null
            if (vm.focused == null) return@RefPicker
            vm.insertRef(if (sug.kind == "tag") "tag" else "doc", sug.id, sug.title, sug.color ?: "")
        }
        Sheet.Icon -> EmojiSheet({ sheet = null }) { e ->
            sheet = null
            scope.launch { runCatching { ws.setIcon(doc!!, e) }.onFailure { snack.error(it) } }
        }
        Sheet.Tags -> TagsSheet(ws, doc!!) { sheet = null }
        Sheet.Move -> MoveSheet(ws, doc!!, { sheet = null }) { parent ->
            sheet = null
            scope.launch { runCatching { ws.move(doc, parent) }.onSuccess { snack.show("Moved") }.onFailure { snack.error(it) } }
        }
        is Sheet.Link -> LinkSheet({ sheet = null }) { label, url ->
            sheet = null
            vm.startEditing(s.id, vm.edits[s.id]?.selection?.start?.minus(1))
            vm.wrap("[$label](", "$url)")
        }
        is Sheet.Media -> MediaSheet(s.type, { sheet = null }) { url, title ->
            sheet = null
            if (s.type == "image") vm.insertAfter(s.after, "image", JsonObject(mapOf("url" to JsonPrimitive(url))))
            else vm.insertAfter(s.after, "bookmark", JsonObject(mapOf("url" to JsonPrimitive(url), "title" to JsonPrimitive(title))))
        }
    }

}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Header(vm: DocModel, ws: Workspace, nav: Nav, doc: Doc, tags: List<app.kern.data.Tag>, onIcon: () -> Unit, onTags: () -> Unit) {
    val k = kern
    val focus = remember { FocusRequester() }
    LaunchedEffect(doc.id) {
        // A brand-new page starts with the cursor in its title.
        if (doc.title.isBlank() && vm.blocks.values.all { it.html.isBlank() }) { delay(150); runCatching { focus.requestFocus() } }
    }
    Column(Modifier.fillMaxWidth().padding(horizontal = 20.dp).padding(top = 8.dp, bottom = 12.dp)) {
        if (doc.cover.isNotBlank()) {
            coil.compose.AsyncImage(
                ws.kern.api.abs(doc.cover), null, contentScale = androidx.compose.ui.layout.ContentScale.Crop,
                modifier = Modifier.fillMaxWidth().height(140.dp).clip(RoundedCornerShape(12.dp)).background(k.surface2),
            )
            Spacer(Modifier.height(12.dp))
        }
        Box(Modifier.clip(RoundedCornerShape(10.dp)).clickable(onClick = onIcon).padding(4.dp)) {
            if (doc.icon.isNotBlank()) Text(doc.icon, fontSize = 40.sp)
            else Text("Add icon", style = MaterialTheme.typography.labelMedium, color = k.text3, modifier = Modifier.padding(vertical = 4.dp))
        }
        Spacer(Modifier.height(6.dp))
        Box {
            if (vm.title.isEmpty()) Text("Untitled", style = MaterialTheme.typography.headlineLarge.copy(fontSize = 30.sp), color = k.text3)
            BasicTextField(
                vm.title, { vm.editTitle(it.replace("\n", "")) },
                textStyle = MaterialTheme.typography.headlineLarge.copy(fontSize = 30.sp, color = k.text),
                cursorBrush = SolidColor(k.accent),
                keyboardOptions = KeyboardOptions(imeAction = ImeAction.Next),
                keyboardActions = KeyboardActions(onNext = {
                    val first = vm.rows().firstOrNull()?.block
                    if (first != null && first.type in TEXT_TYPES) vm.startEditing(first.id, 0) else vm.insertAfter(null)
                }),
                modifier = Modifier.fillMaxWidth().focusRequester(focus).clickable { vm.stopEditing() },
            )
        }
        Spacer(Modifier.height(10.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            for (tid in doc.tags) tags.firstOrNull { it.id == tid }?.let { t -> Pill("#${t.name}", k.named(t.color.ifBlank { "gray" })) { nav.go("tag/${t.id}") } }
            Pill(if (doc.tags.isEmpty()) "+ Add tag" else "+", k.text3, onClick = onTags)
            val cards = vm.payload?.cardCount ?: 0
            if (cards > 0) Pill("$cards card${if (cards == 1) "" else "s"} · study", k.purple) { nav.go("review?doc=${doc.id}") }
        }
        Properties(vm, ws, nav)
    }
}

@Composable
private fun Properties(vm: DocModel, ws: Workspace, nav: Nav) {
    val p = vm.payload ?: return
    val defs = p.properties.defs
    if (defs.isEmpty()) return
    val k = kern
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var values by remember(p) { mutableStateOf(p.properties.values) }
    Column(Modifier.padding(top = 12.dp).clip(RoundedCornerShape(10.dp)).border(1.dp, k.border, RoundedCornerShape(10.dp))) {
        defs.forEachIndexed { i, d ->
            if (i > 0) app.kern.ui.components.Divider()
            Row(Modifier.fillMaxWidth().padding(horizontal = 12.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(d.name, style = MaterialTheme.typography.bodyMedium, color = k.text2, modifier = Modifier.width(110.dp), maxLines = 1, overflow = TextOverflow.Ellipsis)
                Box(Modifier.weight(1f)) {
                    PropertyValue(d, values[d.id], p.refs, nav) { nv ->
                        values = JsonObject(values + (d.id to app.kern.data.toJson(nv)))
                        scope.launch { runCatching { ws.kern.setProperty(vm.docId, d.id, nv) }.onFailure { snack.error(it) } }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun PropertyValue(d: app.kern.data.PropDef, v: kotlinx.serialization.json.JsonElement?, refs: Map<String, app.kern.data.RefInfo>, nav: Nav, onChange: ((Any?) -> Unit)?) {
    val k = kern
    fun prim(): String? = runCatching { v?.jsonPrimitive?.contentOrNull }.getOrNull()
    fun list(): List<String> = runCatching { (v as JsonArray).map { it.jsonPrimitive.content } }.getOrDefault(emptyList())
    var editing by remember { mutableStateOf(false) }
    val style = MaterialTheme.typography.bodyMedium
    when (d.type) {
        "boolean" -> {
            val on = prim() == "true"
            Box(Modifier.size(22.dp).clip(RoundedCornerShape(5.dp)).background(if (on) k.accent else k.bg).border(1.5.dp, if (on) k.accent else k.borderStrong, RoundedCornerShape(5.dp))
                .clickable(enabled = onChange != null) { onChange?.invoke(!on) }, contentAlignment = Alignment.Center) {
                if (on) Icon(Icons.Outlined.CheckBox, null, Modifier.size(14.dp), tint = k.onAccent)
            }
        }
        "select", "status" -> {
            val opt = d.options.firstOrNull { it.id == prim() }
            Box {
                if (opt != null) Pill(opt.name, k.named(opt.color.ifBlank { "gray" })) { if (onChange != null) editing = true }
                else Text("Empty", style = style, color = k.text3, modifier = Modifier.clickable(enabled = onChange != null) { editing = true })
                androidx.compose.material3.DropdownMenu(editing, { editing = false }, containerColor = k.surface) {
                    d.options.forEach { o ->
                        androidx.compose.material3.DropdownMenuItem(text = { Pill(o.name, k.named(o.color.ifBlank { "gray" })) }, onClick = { editing = false; onChange?.invoke(o.id) })
                    }
                    androidx.compose.material3.DropdownMenuItem(text = { Text("Clear", color = k.text2) }, onClick = { editing = false; onChange?.invoke(null) })
                }
            }
        }
        "multi_select" -> FlowRow(horizontalArrangement = Arrangement.spacedBy(4.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
            val ids = list()
            ids.forEach { id -> d.options.firstOrNull { it.id == id }?.let { Pill(it.name, k.named(it.color.ifBlank { "gray" })) } }
            if (ids.isEmpty()) Text("Empty", style = style, color = k.text3)
        }
        "relation" -> FlowRow(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
            list().forEach { id ->
                val r = refs["doc:$id"] ?: refs[id]
                Text(r?.title?.ifBlank { "Untitled" } ?: "Page", style = style, color = k.accent, modifier = Modifier.clickable { nav.doc(id) })
            }
        }
        "rating" -> Row {
            val n = prim()?.toDoubleOrNull()?.toInt() ?: 0
            (1..5).forEach { i -> Text(if (i <= n) "★" else "☆", color = if (i <= n) k.accent else k.text3, fontSize = 18.sp, modifier = Modifier.clickable(enabled = onChange != null) { onChange?.invoke(if (i == n) 0 else i) }) }
        }
        "url" -> {
            val ctx = LocalContext.current
            val s = prim()
            if (editing || s.isNullOrBlank()) InlineEdit(s ?: "", onChange) { editing = false } else Text(s, style = style, color = k.blue, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.clickable { openUrl(ctx, s) })
        }
        "formula", "rollup", "created_time", "last_edited_time" -> Text(
            when (val x = v) { null -> ""; is JsonArray -> x.joinToString(", ") { runCatching { it.jsonPrimitive.content }.getOrDefault(it.toString()) }; else -> runCatching { x.jsonPrimitive.content }.getOrDefault(x.toString()) }
                .let { if (d.type.endsWith("_time")) app.kern.ui.components.ago(it) else it },
            style = style, color = k.text2,
        )
        else -> {
            val s = prim()
            if (editing && onChange != null) InlineEdit(s ?: "", onChange) { editing = false }
            else Text(
                (if (d.type == "date") s?.take(10)?.let { app.kern.ui.components.dueLabel(it) } else s)?.ifBlank { null } ?: "Empty",
                style = style, color = if (s.isNullOrBlank()) k.text3 else k.text,
                modifier = Modifier.fillMaxWidth().clickable(enabled = onChange != null) { editing = true },
            )
        }
    }
}

@Composable
private fun InlineEdit(initial: String, onChange: ((Any?) -> Unit)?, onDone: () -> Unit) {
    var t by remember { mutableStateOf(initial) }
    val f = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { f.requestFocus() } }
    BasicTextField(
        t, { t = it }, singleLine = true,
        textStyle = MaterialTheme.typography.bodyMedium.copy(color = kern.text),
        cursorBrush = SolidColor(kern.accent),
        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
        keyboardActions = KeyboardActions(onDone = { onChange?.invoke(t.ifBlank { null }); onDone() }),
        modifier = Modifier.fillMaxWidth().focusRequester(f).clip(RoundedCornerShape(6.dp)).background(kern.surface2).padding(6.dp),
    )
}

@Composable
private fun Toolbar(vm: DocModel, onTypes: () -> Unit, onPage: () -> Unit, onTag: () -> Unit, onLink: () -> Unit, onDone: () -> Unit) {
    val k = kern
    val id = vm.focused ?: return
    Column(Modifier.fillMaxWidth().background(k.side).imePadding().navigationBarsPadding()) {
        app.kern.ui.components.Divider()
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 4.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
            TB(Icons.Outlined.Add, "Block type") { onTypes() }
            TB(Icons.Outlined.CheckBox, "Checklist") { if (vm.blocks[id]?.type == "todo") vm.setType(id, "paragraph") else vm.setType(id, "todo") }
            TB(Icons.Outlined.FormatBold, "Bold") { vm.wrap("**") }
            TB(Icons.Outlined.FormatItalic, "Italic") { vm.wrap("*") }
            TB(Icons.Outlined.FormatStrikethrough, "Strikethrough") { vm.wrap("~~") }
            TB(Icons.Outlined.Code, "Code") { vm.wrap("`") }
            TB(Icons.Outlined.Highlight, "Highlight") { vm.wrap("==") }
            TB(Icons.Outlined.Link, "Link") { onLink() }
            TBText("[[", "Link a page") { onPage() }
            TB(Icons.Outlined.Tag, "Tag") { onTag() }
            TB(Icons.AutoMirrored.Outlined.FormatIndentIncrease, "Indent") { vm.indent(id) }
            TB(Icons.AutoMirrored.Outlined.FormatIndentDecrease, "Outdent") { vm.outdent(id) }
            TB(Icons.Outlined.KeyboardArrowUp, "Move up") { vm.move(id, -1) }
            TB(Icons.Outlined.KeyboardArrowDown, "Move down") { vm.move(id, 1) }
            TB(Icons.Outlined.Delete, "Delete block") { vm.delete(id) }
            TB(Icons.Outlined.KeyboardHide, "Done") { onDone() }
        }
    }
}

@Composable
private fun TB(icon: ImageVector, label: String, onClick: () -> Unit) {
    IconButton(onClick = onClick) { Icon(icon, label, tint = kern.text2) }
}

@Composable
private fun TBText(text: String, label: String, onClick: () -> Unit) {
    Box(Modifier.size(48.dp).clip(RoundedCornerShape(24.dp)).clickable(onClickLabel = label, onClick = onClick), contentAlignment = Alignment.Center) {
        Text(text, color = kern.text2, style = MaterialTheme.typography.titleSmall)
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KSheet(onDismiss: () -> Unit, title: String? = null, content: @Composable () -> Unit) {
    ModalBottomSheet(onDismiss, sheetState = rememberModalBottomSheetState(skipPartiallyExpanded = true), containerColor = kern.surface) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(bottom = 12.dp)) {
            if (title != null) Text(title, style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
            content()
        }
    }
}

@Composable
fun SheetItem(icon: ImageVector, label: String, danger: Boolean = false, hint: String? = null, onClick: () -> Unit) {
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(horizontal = 20.dp, vertical = 13.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, tint = if (danger) kern.danger else kern.text2, modifier = Modifier.size(20.dp))
        Spacer(Modifier.width(16.dp))
        Text(label, style = MaterialTheme.typography.bodyLarge, color = if (danger) kern.danger else kern.text, modifier = Modifier.weight(1f))
        if (hint != null) Text(hint, style = MaterialTheme.typography.bodySmall, color = kern.text3)
    }
}

@Composable
private fun BlockTypeSheet(onDismiss: () -> Unit, onPick: (BlockKind) -> Unit) = KSheet(onDismiss, "Turn into or insert") {
    LazyVerticalGrid(GridCells.Adaptive(104.dp), Modifier.fillMaxWidth().height(380.dp).padding(horizontal = 12.dp)) {
        items(BLOCK_KINDS) { kind ->
            Column(
                Modifier.padding(4.dp).clip(RoundedCornerShape(10.dp)).background(kern.surface2).clickable { onPick(kind) }.padding(vertical = 14.dp, horizontal = 6.dp),
                horizontalAlignment = Alignment.CenterHorizontally,
            ) {
                Icon(kind.icon, null, tint = kern.text2)
                Spacer(Modifier.height(6.dp))
                Text(kind.label, style = MaterialTheme.typography.labelMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}

@Composable
private fun BlockMenu(vm: DocModel, id: String, onDismiss: () -> Unit, onType: () -> Unit, onBacklinks: () -> Unit, onTask: () -> Unit) {
    val ctx = LocalContext.current
    val b = vm.blocks[id] ?: return
    KSheet(onDismiss) {
        if (b.type in TEXT_TYPES) SheetItem(Icons.Outlined.TextFields, "Turn into…") { onDismiss(); onType() }
        if (b.type in TEXT_TYPES && b.type != "code") SheetItem(Icons.Outlined.TaskAlt, "Add to Tasks") { onTask() }
        SheetItem(Icons.Outlined.ContentCopy, "Duplicate") { vm.duplicate(id); onDismiss() }
        SheetItem(Icons.Outlined.Share, "Copy text") {
            val cm = ctx.getSystemService(android.content.ClipboardManager::class.java)
            cm.setPrimaryClip(android.content.ClipData.newPlainText("Kern", Html.text(vm.htmlOf(b))))
            onDismiss()
        }
        if ((vm.payload?.blockBacklinks?.get(id) ?: 0) > 0) SheetItem(Icons.Outlined.Repeat, "References to this block") { onBacklinks() }
        SheetItem(Icons.AutoMirrored.Outlined.FormatIndentIncrease, "Indent") { vm.indent(id); onDismiss() }
        SheetItem(Icons.AutoMirrored.Outlined.FormatIndentDecrease, "Outdent") { vm.outdent(id); onDismiss() }
        SheetItem(Icons.Outlined.KeyboardArrowUp, "Move up") { vm.move(id, -1) }
        SheetItem(Icons.Outlined.KeyboardArrowDown, "Move down") { vm.move(id, 1) }
        SheetItem(Icons.Outlined.Delete, "Delete", danger = true) { vm.delete(id); onDismiss() }
    }
}

@Composable
private fun PageMenu(ws: Workspace, nav: Nav, vm: DocModel, doc: Doc, onClose: () -> Unit, onMove: () -> Unit, onBacklinks: () -> Unit) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    KSheet(onClose, doc.displayTitle) {
        SheetItem(Icons.Outlined.Add, "Add sub-page") {
            onClose()
            scope.launch { runCatching { ws.newPage(parent = doc.id) }.onSuccess { nav.doc(it.id) }.onFailure { snack.error(it) } }
        }
        if ((vm.payload?.backlinkCount ?: 0) > 0) SheetItem(Icons.Outlined.Repeat, "Linked from ${vm.payload!!.backlinkCount} pages") { onBacklinks() }
        if ((vm.payload?.cardCount ?: 0) > 0) SheetItem(Icons.Outlined.Style, "Study this page's flashcards") { onClose(); nav.go("review?doc=${doc.id}") }
        SheetItem(Icons.Outlined.TaskAlt, "Tasks from this page") { onClose(); nav.tab("tasks") }
        SheetItem(Icons.AutoMirrored.Outlined.DriveFileMove, "Move to…") { onMove() }
        SheetItem(Icons.Outlined.ContentCopy, "Duplicate") {
            onClose()
            scope.launch { runCatching { ws.duplicate(doc) }.onSuccess { nav.doc(it.id) }.onFailure { snack.error(it) } }
        }
        SheetItem(Icons.AutoMirrored.Outlined.Notes, "Save as template") {
            onClose()
            scope.launch { runCatching { ws.kern.api.post<Doc>("/templates", app.kern.data.jsonOf("from" to doc.id)) }.onSuccess { snack.show("Saved as a template") }.onFailure { snack.error(it) } }
        }
        SheetItem(Icons.Outlined.Share, "Share text") {
            onClose()
            val text = buildString {
                appendLine(vm.title.ifBlank { "Untitled" }); appendLine()
                vm.rows().forEach { r ->
                    val t = Html.text(vm.htmlOf(r.block))
                    val prefix = "  ".repeat(r.depth) + when (r.block.type) { "bullet" -> "• "; "numbered" -> "${r.number}. "; "todo" -> if (r.block.props.bool("checked") == true) "☑ " else "☐ "; "h1" -> "# "; "h2" -> "## "; "h3" -> "### "; else -> "" }
                    appendLine(prefix + t)
                }
            }
            ctx.startActivity(Intent.createChooser(Intent(Intent.ACTION_SEND).setType("text/plain").putExtra(Intent.EXTRA_TEXT, text).putExtra(Intent.EXTRA_SUBJECT, vm.title), "Share page"))
        }
        SheetItem(Icons.AutoMirrored.Outlined.OpenInNew, "Open in browser") { onClose(); openUrl(ctx, ws.kern.api.base + "/doc/" + doc.id) }
        SheetItem(Icons.Outlined.Archive, if (doc.isArchived) "Unarchive" else "Archive") {
            onClose()
            scope.launch { runCatching { ws.setArchived(doc, !doc.isArchived) }.onSuccess { snack.show(if (doc.isArchived) "Unarchived" else "Archived") }.onFailure { snack.error(it) } }
        }
        SheetItem(Icons.Outlined.Delete, "Move to trash", danger = true) {
            onClose()
            scope.launch { runCatching { ws.trash(doc) }.onSuccess { snack.show("Moved to trash"); nav.back() }.onFailure { snack.error(it) } }
        }
    }
}

@Composable
private fun BacklinksSection(ws: Workspace, nav: Nav, id: String, count: Int) {
    var groups by remember { mutableStateOf<List<BacklinkGroup>?>(null) }
    LaunchedEffect(id) { groups = runCatching { ws.kern.backlinks(id) }.getOrNull() }
    val k = kern
    val palette = k.palette
    val ctx = LocalContext.current
    Column(Modifier.padding(horizontal = 20.dp, vertical = 12.dp)) {
        Text("$count LINKED REFERENCE${if (count == 1) "" else "S"}", style = MaterialTheme.typography.labelSmall, color = k.text3)
        Spacer(Modifier.height(8.dp))
        groups?.forEach { g ->
            Column(Modifier.padding(vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(k.surface).clickable { nav.doc(g.doc.id) }.padding(12.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    DocIcon(g.doc.icon, size = 14.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(g.doc.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.titleSmall)
                }
                g.items.take(3).forEach { item ->
                    Text(
                        remember(item.html) { Html.annotate(item.html, palette) { t -> nav.ref(t) { openUrl(ctx, it) } } },
                        style = MaterialTheme.typography.bodyMedium, color = k.text2, maxLines = 3, overflow = TextOverflow.Ellipsis,
                        modifier = Modifier.padding(top = 4.dp),
                    )
                }
            }
        }
    }
}

@Composable
private fun BacklinksSheet(ws: Workspace, nav: Nav, docId: String, block: String?, onDismiss: () -> Unit) {
    var groups by remember { mutableStateOf<List<BacklinkGroup>?>(null) }
    LaunchedEffect(block) {
        groups = runCatching { if (block != null) ws.kern.api.get<List<BacklinkGroup>>("/blocks/$block/backlinks") else ws.kern.backlinks(docId) }.getOrDefault(emptyList())
    }
    val palette = kern.palette
    KSheet(onDismiss, if (block != null) "References to this block" else "Linked references") {
        if (groups == null) Loading(Modifier.height(120.dp))
        LazyColumn(Modifier.fillMaxWidth().height(420.dp)) {
            items(groups ?: emptyList()) { g ->
                Column(Modifier.fillMaxWidth().clickable { onDismiss(); nav.doc(g.doc.id) }.padding(horizontal = 20.dp, vertical = 10.dp)) {
                    Text(g.doc.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.titleSmall)
                    g.items.forEach { Text(Html.annotate(it.html, palette), style = MaterialTheme.typography.bodyMedium, color = kern.text2, maxLines = 3) }
                }
            }
        }
    }
}

@Composable
fun RefPicker(ws: Workspace, kind: String, onDismiss: () -> Unit, onPick: (Suggestion) -> Unit) {
    var q by remember { mutableStateOf("") }
    var results by remember { mutableStateOf<List<Suggestion>>(emptyList()) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    LaunchedEffect(q) {
        delay(150)
        results = runCatching { ws.kern.suggest(q, if (kind == "tag") "tag" else "doc") }.getOrDefault(emptyList())
    }
    KSheet(onDismiss, if (kind == "tag") "Add a tag" else "Link to a page") {
        val f = remember { FocusRequester() }
        LaunchedEffect(Unit) { runCatching { f.requestFocus() } }
        Box(Modifier.padding(horizontal = 16.dp)) {
            KField(q, { q = it.trimStart('#') }, if (kind == "tag") "Tag name" else "Page title", Modifier.focusRequester(f))
        }
        LazyColumn(Modifier.fillMaxWidth().height(360.dp).imePadding()) {
            items(results) { s ->
                ListRow(
                    if (s.kind == "tag") "#${s.title}" else s.title.ifBlank { "Untitled" },
                    subtitle = s.path.joinToString(" / "),
                    leading = { if (s.kind == "tag") Icon(Icons.Outlined.Tag, null, tint = kern.named(s.color ?: "gray")) else DocIcon(s.icon, size = 16.dp) },
                ) { onPick(s) }
            }
            if (q.isNotBlank() && results.none { it.title.equals(q, true) }) item {
                ListRow(if (kind == "tag") "Create #$q" else "Create page “$q”", leading = { Icon(Icons.Outlined.Add, null, tint = kern.accent) }) {
                    scope.launch {
                        try {
                            if (kind == "tag") { val t = ws.ensureTag(q.trim()); onPick(Suggestion("tag", t.id, t.name, color = t.color)) }
                            else { val d = ws.newPage(title = q.trim()); onPick(Suggestion("doc", d.id, d.title)) }
                        } catch (e: Exception) { snack.error(e) }
                    }
                }
            }
        }
    }
}

private val EMOJI = ("📝 📄 📚 📖 📓 📒 📕 📗 📘 📙 🗂️ 📁 📂 🗃️ 🗒️ 📋 📌 📍 📎 🔖 🏷️ 💡 🧠 🔬 🧪 🧬 🔭 🎓 ✏️ 🖊️ 🖋️ 📐 📏 🧮 💻 🖥️ ⌨️ 🖱️ 📱 ⚙️ 🛠️ 🔧 🔨 🧰 🧲 🔌 🔋 💾 📊 📈 📉 🗓️ 📅 ⏰ ⏳ ✅ ☑️ ✔️ ❗ ❓ ⭐ 🌟 ✨ 🔥 💥 🎯 🚀 🛸 🌍 🌎 🌏 🗺️ 🏔️ 🏕️ 🏖️ 🏠 🏡 🏢 🏛️ 🏗️ 🌱 🌿 🍀 🌳 🌲 🌸 🌻 🌙 ☀️ ⛅ 🌈 ❄️ 🌊 💧 🍎 🍋 🍇 🍕 ☕ 🍵 🍷 🎵 🎶 🎸 🎹 🎨 🖌️ 📷 🎬 🎮 🎲 🧩 ⚽ 🏀 🏃 🚴 🧘 ❤️ 🧡 💛 💚 💙 💜 🖤 🤍 💬 💭 👋 👍 👀 🙌 🤝 💪 🧑‍💻 👥 💼 💰 💳 🛒 🎁 📦 ✉️ 📮 🔒 🔑 🛡️ ⚖️ 🩺 💊 🐶 🐱 🦊 🐻 🐼 🦉 🐝 🦋 🐢 🐙").split(" ")

@Composable
private fun EmojiSheet(onDismiss: () -> Unit, onPick: (String) -> Unit) = KSheet(onDismiss, "Page icon") {
    LazyVerticalGrid(GridCells.Adaptive(48.dp), Modifier.fillMaxWidth().height(340.dp).padding(horizontal = 12.dp)) {
        items(EMOJI) { e ->
            Box(Modifier.size(48.dp).clip(RoundedCornerShape(10.dp)).clickable { onPick(e) }, contentAlignment = Alignment.Center) { Text(e, fontSize = 24.sp) }
        }
    }
    Row(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
        Text("Remove icon", color = kern.danger, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { onPick("") })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun TagsSheet(ws: Workspace, doc: Doc, onDismiss: () -> Unit) {
    val tags by ws.tags.collectAsState()
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var current by remember { mutableStateOf(doc.tags) }
    var q by remember { mutableStateOf("") }
    fun set(ids: List<String>) {
        current = ids
        scope.launch {
            runCatching { ws.kern.updateDoc(doc.id, "tags" to ids) }
                .onSuccess { ws.patchLocal(it); if (it.isFavorite != doc.isFavorite) Unit }
                .onFailure { snack.error(it) }
        }
    }
    KSheet(onDismiss, "Tags") {
        Box(Modifier.padding(horizontal = 16.dp)) {
            KField(q, { q = it.trimStart('#') }, "Find or create a tag",
                keyboard = KeyboardOptions(imeAction = ImeAction.Done),
                actions = KeyboardActions(onDone = {
                    val name = q.trim(); if (name.isEmpty()) return@KeyboardActions
                    q = ""
                    scope.launch { runCatching { ws.ensureTag(name) }.onSuccess { set(current + it.id) }.onFailure { snack.error(it) } }
                }))
        }
        FlowRow(Modifier.padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            tags.filter { q.isBlank() || it.name.contains(q, true) }.sortedBy { it.name.lowercase() }.forEach { t ->
                val on = t.id in current
                app.kern.ui.screens.Choice("#${t.name}", on, kern.named(t.color.ifBlank { "gray" })) { set(if (on) current - t.id else current + t.id) }
            }
        }
        if (q.isNotBlank() && tags.none { it.name.equals(q, true) }) Text(
            "Press done to create #$q", color = kern.text3, style = MaterialTheme.typography.bodySmall, modifier = Modifier.padding(horizontal = 20.dp),
        )
    }
}

@Composable
private fun MoveSheet(ws: Workspace, doc: Doc, onDismiss: () -> Unit, onPick: (String?) -> Unit) {
    val tree by ws.tree.collectAsState()
    var q by remember { mutableStateOf("") }
    val banned = remember(tree) {
        val out = mutableSetOf(doc.id); var grew = true
        while (grew) { grew = false; tree.forEach { if (it.parent in out && out.add(it.id)) grew = true } }
        out
    }
    KSheet(onDismiss, "Move “${doc.displayTitle}” to") {
        Box(Modifier.padding(horizontal = 16.dp)) { KField(q, { q = it }, "Search pages") }
        LazyColumn(Modifier.fillMaxWidth().height(380.dp)) {
            item { ListRow("Top level", leading = { Icon(Icons.Outlined.ChevronRight, null, tint = kern.text3) }) { onPick(null) } }
            items(tree.filter { it.id !in banned && it.entryOf == null && it.database == null && !it.isArchived && (q.isBlank() || it.title.contains(q, true)) }.take(80)) { d ->
                ListRow(d.displayTitle, subtitle = ws.path(d.id).joinToString(" / ") { it.displayTitle }, leading = { DocIcon(d, 16.dp) }) { onPick(d.id) }
            }
        }
    }
}

@Composable
private fun LinkSheet(onDismiss: () -> Unit, onDone: (String, String) -> Unit) = KSheet(onDismiss, "Add link") {
    var label by remember { mutableStateOf("") }
    var url by remember { mutableStateOf("https://") }
    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        KField(label, { label = it }, "Text")
        KField(url, { url = it }, "URL", keyboard = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri))
        app.kern.ui.components.KButton("Insert", Modifier.fillMaxWidth(), primary = true, enabled = url.length > 8) { onDone(label.ifBlank { url }, url.trim()) }
    }
}

@Composable
private fun MediaSheet(type: String, onDismiss: () -> Unit, onDone: (String, String) -> Unit) = KSheet(onDismiss, if (type == "image") "Image from a link" else "Bookmark") {
    var url by remember { mutableStateOf("https://") }
    var title by remember { mutableStateOf("") }
    Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
        KField(url, { url = it }, "URL", keyboard = KeyboardOptions(keyboardType = androidx.compose.ui.text.input.KeyboardType.Uri))
        if (type == "bookmark") KField(title, { title = it }, "Title (optional)")
        app.kern.ui.components.KButton("Insert", Modifier.fillMaxWidth(), primary = true, enabled = url.length > 8) { onDone(url.trim(), title.trim()) }
    }
}

@Composable
private fun GroupChildren(ws: Workspace, nav: Nav, doc: Doc) {
    val tree by ws.tree.collectAsState()
    val kids = tree.filter { it.parent == doc.id && it.entryOf == null && !it.isArchived }.sortedBy { it.position }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    Column(Modifier.padding(horizontal = 16.dp, vertical = 8.dp)) {
        kids.forEach { d ->
            Row(
                Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(kern.surface).border(1.dp, kern.border, RoundedCornerShape(12.dp))
                    .clickable { nav.doc(d.id) }.padding(14.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                DocIcon(d, 20.dp); Spacer(Modifier.width(10.dp))
                Column(Modifier.weight(1f)) {
                    Text(d.displayTitle, style = MaterialTheme.typography.titleSmall)
                    Text(app.kern.ui.components.ago(d.updatedAt), style = MaterialTheme.typography.bodySmall, color = kern.text3)
                }
                Icon(Icons.Outlined.ChevronRight, null, tint = kern.text3)
            }
        }
        Text("+ Add page to group", color = kern.accent, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(vertical = 10.dp).clickable {
            scope.launch { runCatching { ws.newPage(parent = doc.id) }.onSuccess { nav.doc(it.id) }.onFailure { snack.error(it) } }
        })
    }
}

/** Opens the page a block lives on. */
@Composable
fun BlockRedirect(ws: Workspace, nav: Nav, blockId: String) {
    LaunchedEffect(blockId) {
        val r = runCatching { ws.kern.api.get<Map<String, app.kern.data.RefInfo>>("/refs?ids=block:$blockId") }.getOrNull()
        val doc = r?.values?.firstOrNull()?.doc
        nav.c.popBackStack()
        if (doc != null) nav.doc(doc)
    }
    Loading(Modifier.statusBarsPadding())
}
