package app.kern.ui.screens

import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
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
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.lazy.rememberLazyListState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Send
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.AutoAwesome
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Language
import androidx.compose.material.icons.outlined.Quiz
import androidx.compose.material.icons.outlined.Summarize
import androidx.compose.material.icons.outlined.EditNote
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
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
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.Chat
import app.kern.data.ChatMessage
import app.kern.data.obj
import app.kern.data.str
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.ago
import app.kern.ui.doc.openUrl
import app.kern.ui.theme.KernColors
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch

@Composable
fun IntelligenceScreen(ws: Workspace, nav: Nav) {
    var chats by remember { mutableStateOf<List<Chat>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    suspend fun load() { try { chats = ws.kern.chats(); err = null } catch (e: Exception) { err = e.message } }
    LaunchedEffect(Unit) { load() }
    fun new() = scope.launch { runCatching { ws.kern.createChat() }.onSuccess { nav.go("chat/${it.id}") }.onFailure { snack.error(it) } }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Intelligence", onBack = { nav.back() }) {
            IconButton(onClick = { new() }) { Icon(Icons.Outlined.Add, "New chat", tint = kern.accent) }
        }
        when {
            chats == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
            chats == null -> Loading()
            chats!!.isEmpty() -> EmptyState(Icons.Outlined.AutoAwesome, "Ask about your notes", "Intelligence can search, read and edit your workspace, add tasks and make flashcards. Set up an AI provider in the web app's settings first.", action = "Start a chat" to { new() })
            else -> LazyColumn {
                items(chats!!, key = { it.id }) { c ->
                    Row(Modifier.fillMaxWidth().clickable { nav.go("chat/${c.id}") }.padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Outlined.AutoAwesome, null, tint = kern.accent, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(14.dp))
                        Column(Modifier.weight(1f)) {
                            Text(c.title, style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            Text(ago(c.updatedAt), style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        }
                        IconButton(onClick = { scope.launch { runCatching { ws.kern.deleteChat(c.id) }.onSuccess { load() }.onFailure { snack.error(it) } } }) {
                            Icon(Icons.Outlined.Delete, "Delete chat", tint = kern.text3)
                        }
                    }
                }
            }
        }
    }
}

/** Light Markdown for replies: headings, lists, **bold**, *italic*, `code`, code fences, links. */
fun markdown(text: String, k: KernColors): AnnotatedString = buildAnnotatedString {
    var inCode = false
    val lines = text.lines()
    lines.forEachIndexed { li, raw ->
        if (raw.trimStart().startsWith("```")) { inCode = !inCode; return@forEachIndexed }
        if (inCode) {
            val s = length; append(raw)
            addStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = k.codeBg), s, length)
            if (li < lines.lastIndex) append('\n'); return@forEachIndexed
        }
        var line = raw
        val h = Regex("^(#{1,4})\\s+(.*)").find(line)
        val bullet = Regex("^(\\s*)[-*]\\s+(.*)").find(line)
        val start = length
        when {
            h != null -> { line = h.groupValues[2] }
            bullet != null -> { append(bullet.groupValues[1]); append("•  "); line = bullet.groupValues[2] }
        }
        inline(line, k)
        if (h != null) addStyle(SpanStyle(fontWeight = FontWeight.SemiBold, fontSize = if (h.groupValues[1].length <= 2) androidx.compose.ui.unit.TextUnit(18f, androidx.compose.ui.unit.TextUnitType.Sp) else androidx.compose.ui.unit.TextUnit.Unspecified), start, length)
        if (li < lines.lastIndex) append('\n')
    }
}

private fun AnnotatedString.Builder.inline(s: String, k: KernColors) {
    val re = Regex("\\*\\*(.+?)\\*\\*|`([^`]+)`|(?<![\\w*])\\*(?=\\S)(.+?)(?<=\\S)\\*|\\[([^\\]]+)]\\(([^)\\s]+)\\)")
    var i = 0
    for (m in re.findAll(s)) {
        append(s.substring(i, m.range.first)); i = m.range.last + 1
        val st = length
        when {
            m.groups[1] != null -> { append(m.groupValues[1]); addStyle(SpanStyle(fontWeight = FontWeight.SemiBold), st, length) }
            m.groups[2] != null -> { append(m.groupValues[2]); addStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = k.codeBg), st, length) }
            m.groups[3] != null -> { append(m.groupValues[3]); addStyle(SpanStyle(fontStyle = androidx.compose.ui.text.font.FontStyle.Italic), st, length) }
            m.groups[4] != null -> {
                append(m.groupValues[4])
                addLink(androidx.compose.ui.text.LinkAnnotation.Url(m.groupValues[5], androidx.compose.ui.text.TextLinkStyles(SpanStyle(color = k.blue))), st, length)
            }
        }
    }
    append(s.substring(i))
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun ChatScreen(ws: Workspace, nav: Nav, id: String, page: String?) {
    var chat by remember { mutableStateOf<Chat?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var text by remember { mutableStateOf("") }
    var sending by remember { mutableStateOf(false) }
    var pending by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val list = rememberLazyListState()
    val ctx = LocalContext.current
    val k = kern
    val pageTitle = page?.let { ws.doc(it)?.displayTitle }
    LaunchedEffect(id) { try { chat = ws.kern.chat(id) } catch (e: Exception) { err = e.message } }
    val count = (chat?.messages?.size ?: 0) + (if (pending != null) 2 else 0)
    LaunchedEffect(count) { if (count > 0) list.animateScrollToItem(count - 1) }

    fun send(msg: String = text) {
        val m = msg.trim()
        if (m.isEmpty() || sending) return
        text = ""; pending = m; sending = true
        scope.launch {
            try { chat = ws.kern.sendChat(id, m, page); ws.refresh() } catch (e: Exception) { snack.error(e); text = m }
            pending = null; sending = false
        }
    }

    Column(Modifier.fillMaxSize().background(k.bg).statusBarsPadding().imePadding().navigationBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { nav.back() }) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") }
            Column(Modifier.weight(1f)) {
                Text(chat?.title ?: "Intelligence", style = MaterialTheme.typography.titleMedium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                if (pageTitle != null) Text("About “$pageTitle”", style = MaterialTheme.typography.bodySmall, color = k.text3, maxLines = 1)
            }
        }
        Box(Modifier.weight(1f)) {
            val msgs = chat?.messages.orEmpty()
            when {
                chat == null && err != null -> ErrorState(err!!) { }
                chat == null -> Loading()
                msgs.isEmpty() && pending == null -> Column(Modifier.fillMaxSize().padding(20.dp), verticalArrangement = Arrangement.Center, horizontalAlignment = Alignment.CenterHorizontally) {
                    Icon(Icons.Outlined.AutoAwesome, null, tint = k.accent, modifier = Modifier.size(36.dp))
                    Spacer(Modifier.height(12.dp))
                    Text(if (page != null) "Ask about this page" else "What can I help with?", style = MaterialTheme.typography.titleLarge)
                    Spacer(Modifier.height(16.dp))
                    val ideas = if (page != null) listOf(
                        Icons.Outlined.Summarize to "Summarize this page",
                        Icons.Outlined.Quiz to "Quiz me on this page, one question at a time",
                        Icons.Outlined.EditNote to "Suggest improvements to this page",
                        Icons.Outlined.Language to "Look up more about this topic on the web",
                    ) else listOf(
                        Icons.Outlined.Summarize to "What did I write about this week?",
                        Icons.Outlined.EditNote to "Make a page with a plan for my week",
                        Icons.Outlined.Quiz to "Make flashcards from my latest page",
                        Icons.Outlined.Language to "Search the web and summarize the latest news on a topic",
                    )
                    ideas.forEach { (icon, idea) ->
                        Row(Modifier.fillMaxWidth().padding(vertical = 4.dp).clip(RoundedCornerShape(12.dp)).background(k.surface).clickable { send(idea) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(icon, null, tint = k.text3, modifier = Modifier.size(18.dp)); Spacer(Modifier.width(12.dp))
                            Text(idea, style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
                else -> LazyColumn(Modifier.fillMaxSize(), state = list) {
                    items(msgs) { m -> Bubble(m, nav) { openUrl(ctx, it) } }
                    if (pending != null) {
                        item { Bubble(ChatMessage("user", pending!!), nav) {} }
                        item {
                            Row(Modifier.padding(20.dp), verticalAlignment = Alignment.CenterVertically) {
                                CircularProgressIndicator(Modifier.size(16.dp), strokeWidth = 2.dp, color = k.accent)
                                Spacer(Modifier.width(10.dp))
                                Text("Thinking…", color = k.text3, style = MaterialTheme.typography.bodyMedium)
                            }
                        }
                    }
                }
            }
        }
        Row(Modifier.fillMaxWidth().background(k.side).padding(12.dp), verticalAlignment = Alignment.Bottom) {
            Box(Modifier.weight(1f).clip(RoundedCornerShape(20.dp)).background(k.bg).padding(horizontal = 16.dp, vertical = 12.dp)) {
                if (text.isEmpty()) Text("Ask anything…", color = k.text3, style = MaterialTheme.typography.bodyLarge)
                BasicTextField(text, { text = it }, textStyle = MaterialTheme.typography.bodyLarge.copy(color = k.text), cursorBrush = SolidColor(k.accent), maxLines = 6, modifier = Modifier.fillMaxWidth())
            }
            Spacer(Modifier.width(8.dp))
            IconButton(onClick = { send() }, enabled = text.isNotBlank() && !sending, modifier = Modifier.clip(RoundedCornerShape(24.dp)).background(if (text.isNotBlank()) k.accent else k.surface2)) {
                Icon(Icons.AutoMirrored.Outlined.Send, "Send", tint = if (text.isNotBlank()) k.onAccent else k.text3)
            }
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun Bubble(m: ChatMessage, nav: Nav, openUrl: (String) -> Unit) {
    val k = kern
    val user = m.role == "user"
    Column(Modifier.fillMaxWidth().padding(horizontal = 14.dp, vertical = 6.dp), horizontalAlignment = if (user) Alignment.End else Alignment.Start) {
        if (user) {
            Text(m.text, style = MaterialTheme.typography.bodyLarge, color = k.text,
                modifier = Modifier.widthIn(max = 320.dp).clip(RoundedCornerShape(18.dp, 18.dp, 4.dp, 18.dp)).background(k.surface2).padding(horizontal = 14.dp, vertical = 10.dp))
        } else {
            Text(remember(m.text, k) { markdown(m.text, k) }, style = MaterialTheme.typography.bodyLarge, color = k.text, modifier = Modifier.padding(horizontal = 6.dp))
            if (m.actions.isNotEmpty()) Column(Modifier.padding(top = 8.dp, start = 6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                m.actions.forEach { a ->
                    val verb = a.str("verb") ?: a.str("kind") ?: ""
                    val detail = a.str("detail") ?: ""
                    val page = a.obj("page")
                    val pid = page.str("id")
                    Row(
                        Modifier.clip(RoundedCornerShape(8.dp)).background(k.tint(k.accent)).clickable(enabled = pid != null) { pid?.let { nav.doc(it) } }.padding(horizontal = 10.dp, vertical = 6.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Text("✦ ", color = k.accent)
                        Text(listOfNotNull(verb.ifBlank { null }, page.str("title")?.ifBlank { "Untitled" }, detail.ifBlank { null }).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = k.text, maxLines = 2, overflow = TextOverflow.Ellipsis)
                    }
                }
            }
            if (m.sources.isNotEmpty()) FlowRow(Modifier.padding(top = 8.dp, start = 6.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
                m.sources.forEach { s ->
                    val url = s.str("url") ?: return@forEach
                    Text((s.str("title") ?: url).take(40), style = MaterialTheme.typography.labelMedium, color = k.blue,
                        modifier = Modifier.clip(RoundedCornerShape(6.dp)).background(k.surface).clickable { openUrl(url) }.padding(horizontal = 8.dp, vertical = 4.dp))
                }
            }
        }
    }
}
