package app.kern.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Bookmark
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.Block
import app.kern.data.Html
import app.kern.notify.SyncWorker
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.LocalSnack
import app.kern.ui.doc.KSheet
import app.kern.ui.doc.SheetItem
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonObject
import java.util.UUID

/** Text or a link shared to Kern from another app. */
@Composable
fun ShareSheet(ws: Workspace, nav: Nav, text: String, subject: String?, onDone: () -> Unit) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val url = Regex("https?://\\S+").find(text)?.value
    val title = subject?.takeIf { it.isNotBlank() } ?: text.lineSequence().firstOrNull()?.take(80)?.takeIf { it != url } ?: ""

    KSheet(onDone, "Save to Kern") {
        Text(
            text, maxLines = 4, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyMedium, color = kern.text2,
            modifier = Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(kern.surface2).padding(12.dp),
        )
        Column(Modifier.padding(top = 8.dp)) {
            if (url != null) SheetItem(Icons.Outlined.Bookmark, "Save as bookmark", hint = "offline copy") {
                onDone()
                scope.launch {
                    runCatching { ws.kern.addWeb(url, title = subject ?: "") }
                        .onSuccess { snack.show("Saving bookmark…"); nav.go("bookmark/${it.id}") }
                        .onFailure { snack.error(it) }
                }
            }
            SheetItem(Icons.Outlined.Description, "New page") {
                onDone()
                scope.launch {
                    try {
                        val d = ws.newPage(title = if (url != null && subject != null) subject else title.take(120))
                        val body = text.lines().filter { it.isNotBlank() }.let { if (it.firstOrNull() == d.title) it.drop(1) else it }
                        val blocks = body.mapIndexed { i, line ->
                            val html = url?.takeIf { line.contains(it) }?.let { u -> Html.esc(line).replace(Html.esc(u), "<a href=\"${Html.escAttr(u)}\">${Html.esc(u)}</a>") } ?: Html.esc(line)
                            Block(UUID.randomUUID().toString(), null, (i + 1).toDouble(), "paragraph", html, JsonObject(emptyMap()))
                        }
                        if (blocks.isNotEmpty()) ws.kern.syncBlocks(d.id, blocks, emptyList(), null)
                        nav.doc(d.id)
                    } catch (e: Exception) { snack.error(e) }
                }
            }
            SheetItem(Icons.Outlined.CheckCircle, "New task") {
                onDone()
                scope.launch {
                    runCatching { ws.kern.createTask(title.ifBlank { text.take(200) }, description = if (text.length > title.length) text else "") }
                        .onSuccess { snack.show("Task added"); SyncWorker.refreshSoon(ctx) }
                        .onFailure { snack.error(it) }
                }
            }
            SheetItem(Icons.Outlined.AutoAwesome, "Ask Intelligence about it") {
                onDone()
                scope.launch {
                    runCatching { ws.kern.createChat() }.onSuccess { c ->
                        nav.go("chat/${c.id}")
                        runCatching { ws.kern.sendChat(c.id, text) }
                    }.onFailure { snack.error(it) }
                }
            }
        }
    }
}
