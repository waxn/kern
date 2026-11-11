package app.kern.ui.doc

import android.content.Intent
import android.net.Uri
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.gestures.detectTapGestures
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.IntrinsicSize
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxHeight
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.InsertDriveFile
import androidx.compose.material.icons.outlined.AudioFile
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.ChevronRight
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.ExpandMore
import androidx.compose.material.icons.outlined.Functions
import androidx.compose.material.icons.outlined.PlayCircle
import androidx.compose.material.icons.outlined.Repeat
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Style
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.app
import app.kern.data.Html
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.theme.kern
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonPrimitive

fun openUrl(ctx: android.content.Context, url: String) {
    runCatching { ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(url)).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)) }
}

@Composable
fun blockStyle(type: String, size: String): TextStyle {
    val t = MaterialTheme.typography
    val scale = when (size) { "small" -> 0.92f; "large" -> 1.12f; else -> 1f }
    val base = when (type) {
        "h1" -> t.headlineMedium
        "h2" -> t.headlineSmall
        "h3" -> t.titleMedium.copy(fontSize = 17.sp)
        "code" -> TextStyle(fontFamily = FontFamily.Monospace, fontSize = 13.5.sp, lineHeight = 20.sp)
        "quote" -> t.bodyLarge.copy(fontSize = 16.5.sp)
        else -> t.bodyLarge.copy(fontSize = 16.sp, lineHeight = 25.sp)
    }
    return base.copy(fontSize = base.fontSize * scale, lineHeight = base.lineHeight * scale, color = kern.text)
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
fun BlockItem(vm: DocModel, ws: Workspace, nav: Nav, row: Row, size: String, onMenu: (String) -> Unit) {
    val b = row.block
    val ctx = LocalContext.current
    val k = kern
    val editing = vm.focused == b.id && b.type in TEXT_TYPES
    val onLink: (String) -> Unit = { target -> nav.ref(target) { openUrl(ctx, ws.kern.api.abs(it) ?: it) } }
    val payload = vm.payload
    val cardCount = payload?.blockCards?.get(b.id) ?: 0
    val backlinks = payload?.blockBacklinks?.get(b.id) ?: 0

    Row(
        Modifier.fillMaxWidth()
            .padding(start = (16 + row.depth * 22).dp, end = 12.dp)
            .padding(vertical = if (b.type.startsWith("h")) 6.dp else 1.dp),
        verticalAlignment = Alignment.Top,
    ) {
        // Leading marker
        when (b.type) {
            "bullet" -> Marker { Box(Modifier.size(6.dp).clip(CircleShape).background(if (row.depth % 2 == 0) k.text2 else Color.Transparent).border(1.2.dp, k.text2, CircleShape)) }
            "numbered" -> Marker { Text("${row.number}.", style = MaterialTheme.typography.bodyLarge, color = k.text2) }
            "todo" -> {
                val checked = b.props.bool("checked") == true
                Box(Modifier.size(28.dp).clip(RoundedCornerShape(6.dp)).clickable { vm.toggleCheck(b.id) }, contentAlignment = Alignment.Center) {
                    Box(
                        Modifier.size(18.dp).clip(RoundedCornerShape(5.dp)).background(if (checked) k.accent else Color.Transparent).border(1.5.dp, if (checked) k.accent else k.borderStrong, RoundedCornerShape(5.dp)),
                        contentAlignment = Alignment.Center,
                    ) { if (checked) Icon(Icons.Outlined.Check, null, Modifier.size(13.dp), tint = k.onAccent) }
                }
                Spacer(Modifier.width(4.dp))
            }
            "toggle" -> Box(Modifier.size(28.dp).clip(CircleShape).clickable { vm.toggleCollapse(b.id) }, contentAlignment = Alignment.Center) {
                Icon(if (b.collapsed) Icons.Outlined.ChevronRight else Icons.Outlined.ExpandMore, "Toggle", tint = k.text2, modifier = Modifier.size(20.dp))
            }
        }

        val body: @Composable () -> Unit = {
            when (b.type) {
                "divider" -> Box(Modifier.fillMaxWidth().padding(vertical = 14.dp).height(1.dp).background(k.borderStrong).combinedClickable(onClick = {}, onLongClick = { onMenu(b.id) }))
                "image" -> MediaImage(ws, b, onLongClick = { onMenu(b.id) })
                "video", "audio", "file" -> FileCard(ws, b) { onMenu(b.id) }
                "bookmark" -> BookmarkCard(b) { onMenu(b.id) }
                "equation" -> EquationBlock(vm, b) { onMenu(b.id) }
                "table" -> TableBlock(b, onLink) { onMenu(b.id) }
                "embed", "synced" -> EmbedCard(vm, ws, nav, b) { onMenu(b.id) }
                "database" -> DatabaseCard(ws, nav, b) { onMenu(b.id) }
                else -> TextBlock(vm, b, editing, size, onLink, onMenu)
            }
        }

        when (b.type) {
            "quote" -> Row(Modifier.height(IntrinsicSize.Min).weight(1f)) {
                Box(Modifier.width(3.dp).fillMaxHeight().padding(vertical = 4.dp).background(k.text3, RoundedCornerShape(2.dp)))
                Spacer(Modifier.width(12.dp))
                Box(Modifier.weight(1f)) { body() }
            }
            "callout" -> Row(
                Modifier.weight(1f).padding(vertical = 4.dp).clip(RoundedCornerShape(10.dp)).background(k.surface2).padding(12.dp),
                verticalAlignment = Alignment.Top,
            ) {
                Text(b.props.string("icon") ?: "💡", fontSize = 18.sp, modifier = Modifier.padding(end = 10.dp, top = 2.dp))
                Box(Modifier.weight(1f)) { body() }
            }
            "code" -> Box(
                Modifier.weight(1f).padding(vertical = 4.dp).clip(RoundedCornerShape(8.dp)).background(k.surface).border(1.dp, k.border, RoundedCornerShape(8.dp)).padding(12.dp)
            ) { body() }
            else -> Box(Modifier.weight(1f)) { body() }
        }

        // Badges: flashcards made from this block, other blocks referring to it.
        if (cardCount > 0 || backlinks > 0) Column(Modifier.padding(start = 4.dp, top = 6.dp), horizontalAlignment = Alignment.End) {
            if (cardCount > 0) Badge(Icons.Outlined.Style, cardCount, k.purple) { nav.go("review?doc=${vm.docId}") }
            if (backlinks > 0) Badge(Icons.Outlined.Repeat, backlinks, k.text3) { onMenu("backlinks:${b.id}") }
        }
        payload?.blockTasks?.get(b.id)?.let { t ->
            if (t.due != null && !t.done) Text(
                app.kern.ui.components.dueLabel(t.due), style = MaterialTheme.typography.labelSmall,
                color = if (t.due < java.time.LocalDate.now().toString()) k.danger else k.green,
                modifier = Modifier.padding(start = 6.dp, top = 6.dp).clip(RoundedCornerShape(4.dp)).clickable { nav.go("tasks?task=${t.id}") }.padding(4.dp),
            )
        }
    }
}

@Composable
private fun Marker(content: @Composable () -> Unit) {
    Box(Modifier.widthIn(min = 24.dp).height(25.dp).padding(end = 6.dp), contentAlignment = Alignment.Center) { content() }
}

@Composable
private fun Badge(icon: androidx.compose.ui.graphics.vector.ImageVector, n: Int, color: Color, onClick: () -> Unit) {
    Row(Modifier.clip(RoundedCornerShape(4.dp)).clickable(onClick = onClick).padding(horizontal = 4.dp, vertical = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        Icon(icon, null, Modifier.size(12.dp), tint = color)
        Text("$n", fontSize = 11.sp, color = color)
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TextBlock(vm: DocModel, b: app.kern.data.Block, editing: Boolean, size: String, onLink: (String) -> Unit, onMenu: (String) -> Unit) {
    val k = kern
    val style = blockStyle(b.type, size).let {
        if (b.type == "todo" && b.props.bool("checked") == true) it.copy(color = k.text3, textDecoration = TextDecoration.LineThrough) else it
    }
    if (editing) {
        val focus = remember { FocusRequester() }
        val value = vm.edits[b.id]
        LaunchedEffect(vm.focusTick, vm.focused) {
            // A just-inserted field is attached a frame or two after composition; retry until it takes.
            repeat(10) {
                if (vm.focused != b.id) return@LaunchedEffect
                if (runCatching { focus.requestFocus() }.isSuccess) return@LaunchedEffect
                androidx.compose.runtime.withFrameNanos { }
            }
        }
        if (value != null) {
            BasicTextField(
                value = value,
                onValueChange = { vm.onEdit(b.id, it) },
                textStyle = style,
                cursorBrush = SolidColor(k.accent),
                modifier = Modifier.fillMaxWidth().heightIn(min = 25.dp).focusRequester(focus),
                decorationBox = { inner ->
                    Box {
                        if (value.text.removePrefix(SENTINEL).isEmpty()) Text(placeholder(b.type), style = style.copy(color = k.text3, textDecoration = null))
                        inner()
                    }
                },
            )
        }
    } else {
        val html = vm.htmlOf(b)
        val palette = k.palette
        val text = remember(html, palette) { Html.annotate(html, palette, tagOnly = true) }
        var layout by remember { mutableStateOf<androidx.compose.ui.text.TextLayoutResult?>(null) }
        Box(
            Modifier.fillMaxWidth().heightIn(min = 25.dp)
                .pointerInput(text) {
                    detectTapGestures(
                        onTap = { pos ->
                            // Follow a link only when the tapped character is part of it; otherwise edit.
                            val l = layout
                            val hit = l?.takeIf { pos.y <= it.size.height && pos.x <= it.getLineRight(it.getLineForVerticalPosition(pos.y)) }
                                ?.getOffsetForPosition(pos)
                                ?.let { off -> text.getStringAnnotations(Html.LINK, off, off).firstOrNull() }
                            if (hit != null) onLink(hit.item) else vm.startEditing(b.id)
                        },
                        onLongPress = { onMenu(b.id) },
                    )
                }
        ) {
            if (text.isEmpty()) Text(if (vm.rows().size == 1) "Tap to start writing…" else "", style = style.copy(color = k.text3))
            else Text(text, style = style, onTextLayout = { layout = it })
        }
    }
}

private fun placeholder(type: String) = when (type) {
    "h1" -> "Heading 1"; "h2" -> "Heading 2"; "h3" -> "Heading 3"
    "bullet", "numbered" -> "List"; "todo" -> "To-do"; "toggle" -> "Toggle"; "quote" -> "Quote"; "code" -> "Code"
    else -> "Type, or use the toolbar for blocks"
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun MediaImage(ws: Workspace, b: app.kern.data.Block, onLongClick: () -> Unit) {
    val ctx = LocalContext.current
    val url = ws.kern.api.abs(b.props.string("url"))
    Column(Modifier.fillMaxWidth().padding(vertical = 6.dp)) {
        if (url != null) AsyncImage(
            url, b.props.string("caption") ?: "Image",
            contentScale = ContentScale.FillWidth,
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(kern.surface2).heightIn(min = 60.dp)
                .combinedClickable(onClick = { openUrl(ctx, url) }, onLongClick = onLongClick),
        )
        b.props.string("caption")?.takeIf { it.isNotBlank() }?.let {
            Text(Html.text(it), style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(top = 6.dp))
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun FileCard(ws: Workspace, b: app.kern.data.Block, onLongClick: () -> Unit) {
    val ctx = LocalContext.current
    val url = ws.kern.api.abs(b.props.string("url"))
    val name = b.props.string("name") ?: url?.substringAfterLast('/') ?: b.type.replaceFirstChar { it.uppercase() }
    BoxCard(onClick = { url?.let { openUrl(ctx, it) } }, onLongClick = onLongClick) {
        Icon(when (b.type) { "video" -> Icons.Outlined.PlayCircle; "audio" -> Icons.Outlined.AudioFile; else -> Icons.AutoMirrored.Outlined.InsertDriveFile }, null, tint = kern.accent)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(name, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge)
            Text(b.props.string("mime") ?: b.type, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun BoxCard(onClick: () -> Unit, onLongClick: () -> Unit, content: @Composable androidx.compose.foundation.layout.RowScope.() -> Unit) {
    val shape = RoundedCornerShape(10.dp)
    Row(
        Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(shape).background(kern.surface).border(1.dp, kern.border, shape)
            .combinedClickable(onClick = onClick, onLongClick = onLongClick).padding(12.dp),
        verticalAlignment = Alignment.CenterVertically, content = content,
    )
}

@Composable
private fun BookmarkCard(b: app.kern.data.Block, onLongClick: () -> Unit) {
    val ctx = LocalContext.current
    val url = b.props.string("url") ?: ""
    BoxCard(onClick = { if (url.isNotBlank()) openUrl(ctx, url) }, onLongClick = onLongClick) {
        Icon(Icons.Outlined.Bookmark, null, tint = kern.accent)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(b.props.string("title")?.ifBlank { null } ?: url.removePrefix("https://").removePrefix("http://"), maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge)
            if (url.isNotBlank()) Text(url, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun EquationBlock(vm: DocModel, b: app.kern.data.Block, onLongClick: () -> Unit) {
    var editing by remember { mutableStateOf(false) }
    val tex = b.props.string("tex") ?: ""
    if (editing) {
        var v by remember { mutableStateOf(tex) }
        BasicTextField(
            v, { v = it; vm.setProps(b.id, "tex" to it) },
            textStyle = TextStyle(fontFamily = FontFamily.Monospace, fontSize = 14.sp, color = kern.text),
            cursorBrush = SolidColor(kern.accent),
            modifier = Modifier.fillMaxWidth().clip(RoundedCornerShape(8.dp)).background(kern.surface2).padding(12.dp),
        )
        Text("Done", color = kern.accent, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(top = 4.dp).clickable { editing = false })
    } else {
        Row(
            Modifier.fillMaxWidth().padding(vertical = 6.dp).clip(RoundedCornerShape(8.dp)).combinedClickable(onClick = { editing = true }, onLongClick = onLongClick).padding(10.dp),
            horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically,
        ) {
            Icon(Icons.Outlined.Functions, null, tint = kern.text3, modifier = Modifier.size(16.dp))
            Spacer(Modifier.width(8.dp))
            Text(tex.ifBlank { "Empty equation" }, fontFamily = FontFamily.Serif, fontSize = 17.sp, color = if (tex.isBlank()) kern.text3 else kern.text)
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun TableBlock(b: app.kern.data.Block, onLink: (String) -> Unit, onLongClick: () -> Unit) {
    val k = kern
    val rows = runCatching { b.props["rows"]!!.jsonArray.map { r -> (r as JsonArray).map { it.jsonPrimitive.contentOrNull ?: "" } } }.getOrDefault(emptyList())
    val header = b.props.bool("header") ?: true
    val palette = k.palette
    Box(Modifier.fillMaxWidth().padding(vertical = 6.dp).horizontalScroll(rememberScrollState())) {
        Column(Modifier.clip(RoundedCornerShape(8.dp)).border(1.dp, k.border, RoundedCornerShape(8.dp)).combinedClickable(onClick = {}, onLongClick = onLongClick)) {
            rows.forEachIndexed { ri, r ->
                Row(Modifier.background(if (ri == 0 && header) k.surface2 else Color.Transparent)) {
                    r.forEachIndexed { ci, cell ->
                        Box(Modifier.widthIn(min = 110.dp, max = 220.dp).border(0.5.dp, k.border).padding(horizontal = 10.dp, vertical = 8.dp)) {
                            Text(remember(cell) { Html.annotate(cell, palette, onLink = onLink) }, style = MaterialTheme.typography.bodyMedium, fontWeight = if (ri == 0 && header) FontWeight.SemiBold else null)
                        }
                    }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun EmbedCard(vm: DocModel, ws: Workspace, nav: Nav, b: app.kern.data.Block, onLongClick: () -> Unit) {
    val target = b.props.string("target") ?: b.props.string("doc")
    val kind = b.props.string("kind") ?: "doc"
    val ref = vm.payload?.refs?.get("$kind:$target") ?: vm.payload?.refs?.get(target ?: "")
    val label = when {
        b.type == "synced" -> "Synced block"
        kind == "block" -> "Embedded block"
        else -> "Embedded page"
    }
    BoxCard(onClick = {
        if (target != null) { if (kind == "block") nav.go("block/$target") else nav.doc(target) }
    }, onLongClick = onLongClick) {
        Icon(if (b.type == "synced") Icons.Outlined.Repeat else Icons.Outlined.Description, null, tint = kern.accent)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text(label.uppercase(), style = MaterialTheme.typography.labelSmall, color = kern.text3)
            Text(ref?.title?.ifBlank { null } ?: ref?.docTitle ?: if (b.type == "synced") Html.oneLine(b.html).ifBlank { "Open to view" } else "Open", maxLines = 2, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge)
        }
        Icon(Icons.Outlined.ChevronRight, null, tint = kern.text3)
    }
}

@Composable
private fun DatabaseCard(ws: Workspace, nav: Nav, b: app.kern.data.Block, onLongClick: () -> Unit) {
    val scope = rememberCoroutineScope()
    val ctx = LocalContext.current
    val dbId = b.props.string("database")
    var title by remember(dbId) { mutableStateOf<String?>(null) }
    var page by remember(dbId) { mutableStateOf<String?>(null) }
    var count by remember(dbId) { mutableStateOf<Int?>(null) }
    LaunchedEffect(dbId) {
        if (dbId != null) runCatching { ctx.app.kern.database(dbId) }.getOrNull()?.let { title = it.database.title; page = it.database.page; count = it.rows.size }
    }
    BoxCard(onClick = { page?.let { nav.doc(it) } ?: scope.launch {} }, onLongClick = onLongClick) {
        Icon(Icons.Outlined.Storage, null, tint = kern.accent)
        Spacer(Modifier.width(12.dp))
        Column(Modifier.weight(1f)) {
            Text("DATABASE", style = MaterialTheme.typography.labelSmall, color = kern.text3)
            Text(title?.ifBlank { "Untitled database" } ?: "Loading…", style = MaterialTheme.typography.bodyLarge)
            count?.let { Text("$it ${if (it == 1) "entry" else "entries"}", style = MaterialTheme.typography.bodySmall, color = kern.text3) }
        }
        Icon(Icons.Outlined.ChevronRight, null, tint = kern.text3)
    }
}
