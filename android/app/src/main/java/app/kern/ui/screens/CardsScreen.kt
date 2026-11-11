package app.kern.ui.screens

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.BoxWithConstraints
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.automirrored.outlined.Undo
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.Celebration
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Layers
import androidx.compose.material.icons.outlined.Insights
import androidx.compose.material.icons.outlined.PlayArrow
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableLongStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.data.Card
import app.kern.data.CardQueue
import app.kern.data.CardStats
import app.kern.data.Deck
import app.kern.data.Html
import app.kern.notify.SyncWorker
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.doc.KSheet
import app.kern.ui.doc.openUrl
import app.kern.ui.theme.kern
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import java.time.LocalDate

@OptIn(androidx.compose.material3.ExperimentalMaterial3Api::class)
@Composable
fun CardsScreen(ws: Workspace, nav: Nav) {
    var stats by remember { mutableStateOf<CardStats?>(null) }
    var decks by remember { mutableStateOf<List<Deck>>(emptyList()) }
    var err by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var adding by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    suspend fun load() {
        try { stats = ws.kern.cardStats(); decks = ws.kern.decks(); err = null } catch (e: Exception) { err = e.message }
    }
    LaunchedEffect(Unit) { load() }
    val k = kern

    Column(Modifier.fillMaxSize().background(k.bg).statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Flashcards", style = MaterialTheme.typography.headlineMedium, modifier = Modifier.weight(1f))
            IconButton(onClick = { nav.go("stats") }) { Icon(Icons.Outlined.Insights, "Stats", tint = k.text2) }
            IconButton(onClick = { adding = true }) { Icon(Icons.Outlined.Add, "New card", tint = k.accent) }
        }
        PullToRefreshBox(refreshing, { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.weight(1f)) {
            val s = stats
            when {
                s == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
                s == null -> Loading()
                else -> LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        Column(Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(16.dp)).background(k.surface).border(1.dp, k.border, RoundedCornerShape(16.dp)).padding(18.dp)) {
                            Row(verticalAlignment = Alignment.Bottom) {
                                Text("${s.dueToday}", style = MaterialTheme.typography.displaySmall.copy(fontSize = 44.sp), color = if (s.dueToday > 0) k.text else k.text3)
                                Spacer(Modifier.width(8.dp))
                                Text("due today", style = MaterialTheme.typography.bodyLarge, color = k.text2, modifier = Modifier.padding(bottom = 8.dp))
                                Spacer(Modifier.weight(1f))
                                Text("+${s.newAvailable} new", color = k.purple, style = MaterialTheme.typography.labelLarge, modifier = Modifier.padding(bottom = 10.dp))
                            }
                            Spacer(Modifier.height(10.dp))
                            Row(horizontalArrangement = Arrangement.spacedBy(18.dp)) {
                                Stat("${s.reviewedToday}", "reviewed")
                                Stat("${s.timeTodayMs / 60000}m", "studied")
                                Stat(s.accuracyToday?.let { "${it.toInt()}%" } ?: "—", "right today")
                                Stat(s.accuracy30d?.let { "${it.toInt()}%" } ?: "—", "30 days")
                            }
                            Spacer(Modifier.height(16.dp))
                            KButton(if (s.dueToday + s.newAvailable > 0) "Study now" else "Nothing to study", Modifier.fillMaxWidth(), primary = true, icon = Icons.Outlined.PlayArrow, enabled = s.dueToday + s.newAvailable > 0) { nav.go("review") }
                        }
                    }
                    if (s.forecast.isNotEmpty()) item {
                        Heading("Next 14 days")
                        Forecast(s.forecast.take(14))
                    }
                    if (s.history.isNotEmpty()) item {
                        Heading("Last 26 weeks")
                        Heatmap(s.history)
                    }
                    item { Heading("Decks") }
                    if (decks.isEmpty()) item { EmptyState(Icons.Outlined.Layers, "No cards yet", "Write “Question :: Answer” in any block, or add a card with +.") }
                    decks.forEach { d ->
                        item(key = d.id) {
                            Row(Modifier.fillMaxWidth().clickable { nav.go("review?deck=${d.id}") }.padding(horizontal = 20.dp, vertical = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                                Icon(Icons.Outlined.Layers, null, tint = k.purple, modifier = Modifier.size(20.dp))
                                Spacer(Modifier.width(14.dp))
                                Column(Modifier.weight(1f)) {
                                    Text(d.name, style = MaterialTheme.typography.bodyLarge)
                                    Text("${d.total} cards", style = MaterialTheme.typography.bodySmall, color = k.text3)
                                }
                                if (d.due > 0) Text("${d.due} due", color = k.accent, style = MaterialTheme.typography.labelLarge)
                                if (d.new > 0) { Spacer(Modifier.width(10.dp)); Text("${d.new} new", color = k.purple, style = MaterialTheme.typography.labelLarge) }
                            }
                        }
                    }
                    item {
                        val st = s.counts
                        Text(
                            listOf("new", "learning", "review", "relearning").joinToString(" · ") { "${st[it] ?: 0} $it" } + if (s.suspended > 0) " · ${s.suspended} suspended" else "",
                            style = MaterialTheme.typography.bodySmall, color = k.text3, modifier = Modifier.padding(20.dp),
                        )
                    }
                }
            }
        }
    }

    if (adding) NewCardSheet(ws, decks) { adding = false; scope.launch { load() } }
}

@Composable
private fun Stat(value: String, label: String) {
    Column {
        Text(value, style = MaterialTheme.typography.titleMedium)
        Text(label, style = MaterialTheme.typography.bodySmall, color = kern.text3)
    }
}

@Composable
private fun Forecast(days: List<Int>) {
    val k = kern
    val max = (days.maxOrNull() ?: 1).coerceAtLeast(1)
    Column(Modifier.padding(horizontal = 20.dp)) {
        Row(Modifier.fillMaxWidth().height(90.dp), verticalAlignment = Alignment.Bottom, horizontalArrangement = Arrangement.spacedBy(4.dp)) {
            days.forEachIndexed { i, n ->
                Column(Modifier.weight(1f), horizontalAlignment = Alignment.CenterHorizontally) {
                    if (n > 0) Text("$n", fontSize = 9.sp, color = k.text3)
                    Box(Modifier.fillMaxWidth().height((70f * n / max).dp.coerceAtLeast(2.dp)).clip(RoundedCornerShape(3.dp)).background(if (i == 0) k.accent else k.accent.copy(alpha = 0.45f)))
                }
            }
        }
        Row(Modifier.fillMaxWidth()) {
            Text("Today", style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.weight(1f))
            Text("+13d", style = MaterialTheme.typography.labelSmall, color = k.text3)
        }
    }
}

@Composable
private fun Heatmap(history: Map<String, Int>) {
    val k = kern
    val today = LocalDate.now()
    val weeks = 26
    val start = today.minusDays((weeks * 7 - 1).toLong() + (today.dayOfWeek.value % 7))
    val max = (history.values.maxOrNull() ?: 1).coerceAtLeast(1)
    Canvas(Modifier.padding(horizontal = 20.dp).fillMaxWidth().aspectRatio(weeks / 7f)) {
        val cell = size.width / weeks
        val gap = cell * 0.18f
        for (w in 0 until weeks) for (d in 0 until 7) {
            val day = start.plusDays((w * 7 + d).toLong())
            if (day.isAfter(today)) continue
            val n = history[day.toString()] ?: 0
            val c = if (n == 0) k.surface2 else k.accent.copy(alpha = 0.25f + 0.75f * n / max)
            drawRoundRect(c, Offset(w * cell, d * cell), Size(cell - gap, cell - gap), CornerRadius(cell * 0.2f))
        }
    }
}

@Composable
private fun NewCardSheet(ws: Workspace, decks: List<Deck>, onDone: () -> Unit) {
    var front by remember { mutableStateOf("") }
    var back by remember { mutableStateOf("") }
    var kind by remember { mutableStateOf("basic") }
    var deck by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    KSheet(onDone, "New flashcard") {
        Column(Modifier.padding(horizontal = 16.dp).verticalScroll(rememberScrollState()), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Choice("Basic", kind == "basic") { kind = "basic" }
                Choice("Both ways", kind == "concept") { kind = "concept" }
                Choice("Cloze", kind == "cloze") { kind = "cloze" }
            }
            KField(front, { front = it }, if (kind == "cloze") "Text with {{gaps}}" else if (kind == "concept") "Term" else "Question", singleLine = false, minLines = 2)
            if (kind != "cloze") KField(back, { back = it }, if (kind == "concept") "Definition" else "Answer", singleLine = false, minLines = 2)
            if (decks.any { it.id != "none" }) Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                Choice("Default", deck == null) { deck = null }
                decks.filter { it.id != "none" }.take(4).forEach { d -> Choice(d.name, deck == d.id) { deck = d.id } }
            }
            KButton("Add card", Modifier.fillMaxWidth(), primary = true, enabled = front.isNotBlank() && (kind == "cloze" || back.isNotBlank())) {
                scope.launch {
                    runCatching { ws.kern.createNote(kind, Html.esc(front).replace("\n", "<br>"), Html.esc(back).replace("\n", "<br>"), deck) }
                        .onSuccess { snack.show("Card added"); front = ""; back = "" }
                        .onFailure { snack.error(it) }
                }
            }
            Spacer(Modifier.height(8.dp))
        }
    }
}

// ------------------------------------------------------------------ review

@Composable
fun ReviewScreen(ws: Workspace, nav: Nav, deck: String?, doc: String?) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    var q by remember { mutableStateOf<CardQueue?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var revealed by remember { mutableStateOf(false) }
    var started by remember { mutableLongStateOf(System.currentTimeMillis()) }
    var done by remember { mutableIntStateOf(0) }
    var busy by remember { mutableStateOf(false) }
    val k = kern

    suspend fun next() {
        try { q = ws.kern.queue(deck, doc); err = null } catch (e: Exception) { err = e.message }
        revealed = false
        started = System.currentTimeMillis()
    }
    LaunchedEffect(Unit) { next() }

    fun rate(card: Card, r: Int) = scope.launch {
        if (busy) return@launch
        busy = true
        try {
            ws.kern.review(card.id, r, System.currentTimeMillis() - started)
            done++
            next()
            SyncWorker.refreshSoon(ctx)
        } catch (e: Exception) { snack.error(e) }
        busy = false
    }

    Column(Modifier.fillMaxSize().background(k.bg).statusBarsPadding().navigationBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(8.dp), verticalAlignment = Alignment.CenterVertically) {
            IconButton(onClick = { nav.back() }) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") }
            Column(Modifier.weight(1f)) {
                Text("Review", style = MaterialTheme.typography.titleMedium)
                q?.counts?.let { c ->
                    Row(horizontalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("${c.new} new", color = k.purple, style = MaterialTheme.typography.labelMedium)
                        Text("${c.learning} learning", color = k.red, style = MaterialTheme.typography.labelMedium)
                        Text("${c.review} review", color = k.green, style = MaterialTheme.typography.labelMedium)
                    }
                }
            }
            if (done > 0) IconButton(onClick = {
                scope.launch { runCatching { ws.kern.undoReview() }.onSuccess { done--; next(); snack.show("Undone") }.onFailure { snack.error(it) } }
            }) { Icon(Icons.AutoMirrored.Outlined.Undo, "Undo last answer", tint = k.text2) }
        }
        val card = q?.card
        when {
            q == null && err != null -> ErrorState(err!!) { scope.launch { next() } }
            q == null -> Loading()
            card == null -> Box(Modifier.weight(1f), contentAlignment = Alignment.Center) {
                Column(horizontalAlignment = Alignment.CenterHorizontally) {
                    EmptyState(Icons.Outlined.Celebration, if (done > 0) "Session complete" else "All caught up",
                        if (done > 0) "You reviewed $done card${if (done == 1) "" else "s"}." + (q?.nextLearning?.let { " More cards come back later today." } ?: "")
                        else "No cards are due right now.")
                    KButton("Done", primary = true) { nav.back() }
                }
            }
            else -> {
                Column(Modifier.weight(1f).verticalScroll(rememberScrollState()).padding(20.dp)) {
                    if (card.docTitle != null && card.document != null) Row(
                        Modifier.clip(RoundedCornerShape(6.dp)).clickable { nav.doc(card.document) }.padding(4.dp),
                        verticalAlignment = Alignment.CenterVertically,
                    ) {
                        Icon(Icons.Outlined.Description, null, tint = k.text3, modifier = Modifier.size(14.dp))
                        Spacer(Modifier.width(4.dp))
                        Text(card.docTitle.ifBlank { "Untitled" }, style = MaterialTheme.typography.bodySmall, color = k.text3)
                    }
                    Spacer(Modifier.height(12.dp))
                    Face(ws, card, false)
                    if (revealed) {
                        Box(Modifier.padding(vertical = 20.dp).fillMaxWidth().height(1.dp).background(k.border))
                        Face(ws, card, true)
                    }
                    Spacer(Modifier.height(24.dp))
                }
                Box(Modifier.fillMaxWidth().background(k.side).padding(16.dp)) {
                    if (!revealed) KButton("Show answer", Modifier.fillMaxWidth(), primary = true) { revealed = true }
                    else Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        listOf(1 to "Again", 2 to "Hard", 3 to "Good", 4 to "Easy").forEach { (r, label) ->
                            val color = when (r) { 1 -> k.red; 2 -> k.orange; 3 -> k.green; else -> k.blue }
                            Column(
                                Modifier.weight(1f).clip(RoundedCornerShape(12.dp)).background(k.tint(color)).border(1.dp, color.copy(alpha = 0.4f), RoundedCornerShape(12.dp))
                                    .clickable(enabled = !busy) { rate(card, r) }.padding(vertical = 10.dp),
                                horizontalAlignment = Alignment.CenterHorizontally,
                            ) {
                                Text(label, color = color, fontWeight = FontWeight.SemiBold, style = MaterialTheme.typography.labelLarge)
                                card.intervals?.get("$r")?.let { Text(interval(it), color = k.text3, style = MaterialTheme.typography.labelSmall) }
                            }
                        }
                    }
                }
            }
        }
    }
}

private fun interval(days: Double): String = when {
    days < 1.0 / 24 -> "${(days * 1440).toInt().coerceAtLeast(1)}m"
    days < 1 -> "${(days * 24).toInt()}h"
    days < 30 -> "${days.toInt()}d"
    days < 365 -> "%.1fmo".format(days / 30)
    else -> "%.1fy".format(days / 365)
}

@Composable
private fun Face(ws: Workspace, card: Card, back: Boolean) {
    val k = kern
    val palette = k.palette
    val ctx = LocalContext.current
    val html = if (back) card.back else card.front
    if (card.kind == "occlusion" && card.image != null) {
        BoxWithConstraints(Modifier.fillMaxWidth()) {
            var ratio by remember { mutableStateOf(1.5f) }
            val w = maxWidth
            Box(Modifier.fillMaxWidth().aspectRatio(ratio)) {
                AsyncImage(ws.kern.api.abs(card.image), null, contentScale = ContentScale.FillWidth, modifier = Modifier.fillMaxWidth(),
                    onSuccess = { s -> val d = s.result.drawable; if (d.intrinsicHeight > 0) ratio = d.intrinsicWidth.toFloat() / d.intrinsicHeight })
                val h = w / ratio
                card.regions.orEmpty().forEach { r ->
                    val target = r.n == card.ordinal + 1
                    if (back && target) Box(Modifier.offset(w * r.x.toFloat(), h * r.y.toFloat()).size(w * r.w.toFloat(), h * r.h.toFloat()).border(2.dp, k.accent, RoundedCornerShape(4.dp)))
                    else if (!back || !target) Box(
                        Modifier.offset(w * r.x.toFloat(), h * r.y.toFloat()).size(w * r.w.toFloat(), h * r.h.toFloat()).clip(RoundedCornerShape(4.dp))
                            .background(if (target) k.accent else k.surface2.copy(alpha = 0.95f)),
                        contentAlignment = Alignment.Center,
                    ) { if (target) Text("?", color = k.onAccent, fontWeight = FontWeight.Bold) }
                }
            }
        }
        if (back && html.isNotBlank()) Text(Html.annotate(html, palette), style = MaterialTheme.typography.bodyLarge, modifier = Modifier.padding(top = 12.dp))
        return
    }
    if (back && card.kind == "cloze") {
        Text(Html.annotate(html, palette) { t -> if (t.startsWith("http")) openUrl(ctx, t) }, style = MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Normal, lineHeight = 30.sp), color = k.text)
        return
    }
    Text(
        Html.annotate(html, palette) { t -> if (t.startsWith("http")) openUrl(ctx, t) },
        style = if (back) MaterialTheme.typography.bodyLarge.copy(fontSize = 18.sp, lineHeight = 27.sp) else MaterialTheme.typography.titleLarge.copy(fontWeight = FontWeight.Medium, lineHeight = 30.sp),
        color = if (back) k.text else k.text,
        textAlign = TextAlign.Start,
    )
}
