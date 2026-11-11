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
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material.icons.outlined.History
import androidx.compose.material.icons.automirrored.outlined.Notes
import androidx.compose.material.icons.outlined.Search
import androidx.compose.material.icons.outlined.Style
import androidx.compose.material.icons.outlined.Tag
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.Html
import app.kern.data.SearchResponse
import app.kern.data.SearchResult
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.DocIcon
import app.kern.ui.components.EmptyState
import app.kern.ui.components.Loading
import app.kern.ui.theme.kern
import kotlinx.coroutines.delay

private val KINDS = listOf(null to "All", "doc" to "Pages", "block" to "Blocks", "tag" to "Tags", "card" to "Cards", "task" to "Tasks")

@Composable
fun SearchScreen(ws: Workspace, nav: Nav) {
    var q by rememberSaveable { mutableStateOf("") }
    var kind by rememberSaveable { mutableStateOf<String?>(null) }
    var res by remember { mutableStateOf<SearchResponse?>(null) }
    var loading by remember { mutableStateOf(false) }
    var recent by remember { mutableStateOf(ws.settings.recentSearches) }
    val focus = remember { FocusRequester() }
    val palette = kern.palette
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }
    LaunchedEffect(q, kind) {
        if (q.isBlank()) { res = null; return@LaunchedEffect }
        delay(220)
        loading = true
        res = runCatching { ws.kern.search(q, kind) }.getOrNull()
        loading = false
    }
    fun remember(term: String) {
        if (term.isBlank()) return
        recent = (listOf(term) + recent.filter { it != term }).take(8)
        ws.settings.recentSearches = recent
    }
    fun open(r: SearchResult) {
        remember(q.trim())
        when (r.kind) {
            "doc" -> nav.doc(r.id)
            "block" -> r.doc?.let { nav.doc(it) }
            "tag" -> nav.go("tag/${r.id}")
            "task" -> nav.go("tasks?task=${r.id}")
            "card" -> r.doc?.let { nav.doc(it) } ?: nav.go("cards")
        }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding().imePadding()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { nav.back() }) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") }
            Row(
                Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(kern.surface2).padding(horizontal = 12.dp, vertical = 11.dp),
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Icon(Icons.Outlined.Search, null, tint = kern.text3, modifier = Modifier.size(18.dp))
                Spacer(Modifier.width(8.dp))
                Box(Modifier.weight(1f)) {
                    if (q.isEmpty()) Text("Search pages, blocks, tags, cards, tasks", color = kern.text3, style = MaterialTheme.typography.bodyLarge, maxLines = 1)
                    BasicTextField(
                        q, { q = it }, singleLine = true,
                        textStyle = MaterialTheme.typography.bodyLarge.copy(color = kern.text),
                        cursorBrush = SolidColor(kern.accent),
                        keyboardOptions = KeyboardOptions(imeAction = ImeAction.Search),
                        keyboardActions = KeyboardActions(onSearch = { remember(q.trim()) }),
                        modifier = Modifier.fillMaxWidth().focusRequester(focus),
                    )
                }
                if (q.isNotEmpty()) Icon(Icons.Outlined.Close, "Clear", tint = kern.text3, modifier = Modifier.size(18.dp).clickable { q = "" })
            }
        }
        Row(Modifier.horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp)) {
            KINDS.forEach { (k, label) ->
                val n = if (k == null) null else res?.counts?.get(k)
                Box(Modifier.padding(4.dp)) { Choice(if (n != null && n > 0) "$label $n" else label, kind == k) { kind = k } }
            }
        }
        when {
            q.isBlank() -> LazyColumn(Modifier.fillMaxSize()) {
                if (recent.isNotEmpty()) {
                    item { Heading("Recent searches") }
                    items(recent) { r ->
                        Row(Modifier.fillMaxWidth().clickable { q = r }.padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.History, null, tint = kern.text3, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(14.dp))
                            Text(r, style = MaterialTheme.typography.bodyLarge)
                        }
                    }
                } else item { EmptyState(Icons.Outlined.Search, "Search everything", "Full-text search across your pages, blocks, tags, flashcards and tasks.") }
            }
            res == null && loading -> Loading()
            res?.results.isNullOrEmpty() -> EmptyState(Icons.Outlined.Search, "No results", "Nothing matches “$q”.")
            else -> LazyColumn(Modifier.fillMaxSize()) {
                items(res!!.results, key = { it.kind + it.id }) { r ->
                    Row(Modifier.fillMaxWidth().clickable { open(r) }.padding(horizontal = 16.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
                        Box(Modifier.padding(top = 2.dp)) {
                            when (r.kind) {
                                "doc" -> DocIcon(r.icon, size = 18.dp)
                                "tag" -> Icon(Icons.Outlined.Tag, null, tint = kern.named(r.color ?: "gray"), modifier = Modifier.size(20.dp))
                                "task" -> Icon(Icons.Outlined.CheckCircle, null, tint = kern.text3, modifier = Modifier.size(20.dp))
                                "card" -> Icon(Icons.Outlined.Style, null, tint = kern.purple, modifier = Modifier.size(20.dp))
                                else -> Icon(Icons.AutoMirrored.Outlined.Notes, null, tint = kern.text3, modifier = Modifier.size(20.dp))
                            }
                        }
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            val title = when (r.kind) { "block" -> r.docTitle?.ifBlank { "Untitled" } ?: "Block"; "card" -> r.title.ifBlank { "Flashcard" + (r.docTitle?.let { " · $it" } ?: "") }; else -> r.title.ifBlank { "Untitled" } }
                            Text(Html.annotate(Html.esc(title), palette), style = MaterialTheme.typography.bodyLarge, maxLines = 1, overflow = TextOverflow.Ellipsis)
                            if (r.snippet.isNotBlank()) Text(Html.annotate(Html.esc(r.snippet), palette), style = MaterialTheme.typography.bodyMedium, color = kern.text2, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            if (r.path.isNotEmpty()) Text(r.path.joinToString(" / "), style = MaterialTheme.typography.bodySmall, color = kern.text3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        }
                    }
                }
            }
        }
    }
}
