package app.kern.ui.stats

import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.PrimaryTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Modifier
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.kern.data.Card
import app.kern.data.CardStats
import app.kern.data.Chat
import app.kern.data.Deck
import app.kern.data.Doc
import app.kern.data.Html
import app.kern.data.LibraryFile
import app.kern.data.Repo
import app.kern.data.Storage
import app.kern.data.Tag
import app.kern.data.Task
import app.kern.data.WebItem
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.KTopBar
import app.kern.ui.components.Loading
import app.kern.ui.components.bytes
import app.kern.ui.components.dueLabel
import app.kern.ui.components.parseInstant
import app.kern.ui.theme.kern
import kotlinx.coroutines.async
import kotlinx.coroutines.coroutineScope
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.LocalDate
import java.time.YearMonth
import java.time.ZoneId
import java.time.format.TextStyle
import java.time.temporal.ChronoUnit
import java.util.Locale

/** Everything the stats are computed from; each part may be missing if its request failed. */
class StatsData(
    val cardStats: CardStats?,
    val cards: List<Card>,
    val decks: List<Deck>,
    val tasks: List<Task>,
    val storage: Storage?,
    val tree: List<Doc>,
    val tags: List<Tag>,
    val web: List<WebItem>,
    val files: List<LibraryFile>,
    val repos: List<Repo>,
    val chats: List<Chat>,
)

private suspend fun loadStats(ws: Workspace): StatsData = coroutineScope {
    val k = ws.kern
    fun <T> safe(block: suspend () -> T) = async { runCatching { block() }.getOrNull() }
    val cs = safe { k.cardStats() }; val cards = safe { k.allCards() }; val decks = safe { k.decks() }
    val tasks = safe { k.tasks("all") }; val storage = safe { k.storage() }; val tree = safe { k.tree() }
    val tags = safe { k.tags() }; val web = safe { k.web() }; val files = safe { k.library() }
    val repos = safe { k.repos() }; val chats = safe { k.chats() }
    StatsData(
        cs.await(), cards.await().orEmpty(), decks.await().orEmpty(), tasks.await().orEmpty(), storage.await(),
        tree.await().orEmpty(), tags.await().orEmpty(), web.await().orEmpty(), files.await().orEmpty(),
        repos.await().orEmpty(), chats.await().orEmpty(),
    )
}

private fun localDate(s: String?): LocalDate? = parseInstant(s)?.atZone(ZoneId.systemDefault())?.toLocalDate()
/** "1 review", "2 reviews". */
private fun pl(n: Int, one: String, many: String = one + "s") = "${app.kern.ui.stats.num(n)} ${if (n == 1) one else many}"
private fun pct(a: Int, b: Int) = if (b == 0) "—" else "${(100.0 * a / b).toInt()}%"
private fun wd(d: DayOfWeek) = d.getDisplayName(TextStyle.SHORT, Locale.getDefault())
private fun days(d: Double) = when {
    d < 1 -> "<1 day"
    d < 30 -> "%.1f days".format(d)
    d < 365 -> "%.1f months".format(d / 30)
    else -> "%.1f years".format(d / 365)
}

private val TABS = listOf("Flashcards", "Tasks", "Workspace")

@Composable
fun StatsScreen(ws: Workspace, nav: Nav) {
    var data by remember { mutableStateOf<StatsData?>(null) }
    var tab by rememberSaveable { mutableStateOf(0) }
    var refreshing by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    LaunchedEffect(Unit) { data = loadStats(ws) }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Stats", onBack = { nav.back() })
        PrimaryTabRow(
            selectedTabIndex = tab, containerColor = kern.bg, contentColor = kern.text,
            divider = { app.kern.ui.components.Divider() },
            indicator = { TabRowDefaults.PrimaryIndicator(Modifier.tabIndicatorOffset(tab, matchContentSize = true), color = kern.accent, width = Dp.Unspecified) },
        ) {
            TABS.forEachIndexed { i, t ->
                Tab(i == tab, { tab = i }, text = { Text(t, style = MaterialTheme.typography.labelLarge, color = if (i == tab) kern.text else kern.text2) })
            }
        }
        PullToRefreshBox(refreshing, { scope.launch { refreshing = true; data = loadStats(ws); refreshing = false } }, Modifier.weight(1f)) {
            val d = data
            if (d == null) Loading()
            // Each tab gets its own list, so switching tabs starts at the top.
            else androidx.compose.runtime.key(tab) { LazyColumn(Modifier.fillMaxSize()) {
                item { Spacer(Modifier.height(8.dp)) }
                when (tab) {
                    0 -> item { CardStatsView(d, nav) }
                    1 -> item { TaskStatsView(d, nav) }
                    else -> item { WorkspaceStatsView(d, nav) }
                }
                item { Spacer(Modifier.height(32.dp)) }
            } }
        }
    }
}

// ------------------------------------------------------------------ flashcards

@Composable
private fun CardStatsView(d: StatsData, nav: Nav) {
    val s = d.cardStats
    val today = LocalDate.now()
    val history = s?.history.orEmpty()
    val daily = (0 until 182).map { today.minusDays(it.toLong()) }.associateWith { history[it.toString()] ?: 0 }
    val total = daily.values.sum()
    val studied = daily.values.count { it > 0 }
    // Current streak: today counts if studied, otherwise it starts from yesterday.
    var streak = 0
    var day = if ((daily[today] ?: 0) > 0) today else today.minusDays(1)
    while ((daily[day] ?: 0) > 0) { streak++; day = day.minusDays(1) }
    var longest = 0; var run = 0
    for (i in 181 downTo 0) { if ((daily[today.minusDays(i.toLong())] ?: 0) > 0) { run++; longest = maxOf(longest, run) } else run = 0 }
    val best = daily.maxByOrNull { it.value }?.takeIf { it.value > 0 }
    val last30 = (29 downTo 0).map { daily[today.minusDays(it.toLong())] ?: 0 }
    val weekday = DayOfWeek.entries.map { dw -> daily.filterKeys { it.dayOfWeek == dw }.values.sum() }

    val cards = d.cards
    val live = cards.filter { !it.suspended }
    val review = live.filter { it.state == "review" }
    val mature = review.count { it.stability >= 21 }
    val young = review.size - mature
    val avgStab = review.map { it.stability }.average().takeIf { !it.isNaN() }
    val avgDiff = live.filter { it.reps > 0 }.map { it.difficulty }.average().takeIf { !it.isNaN() }
    val totalReps = cards.sumOf { it.reps }
    val totalLapses = cards.sumOf { it.lapses }
    val stabBuckets = listOf(
        "<1d" to review.count { it.stability < 1 },
        "1–7d" to review.count { it.stability in 1.0..<7.0 },
        "1–3w" to review.count { it.stability in 7.0..<21.0 },
        "3w–3m" to review.count { it.stability in 21.0..<90.0 },
        "3m+" to review.count { it.stability >= 90 },
    )
    val hardest = cards.filter { it.lapses > 0 }.sortedWith(compareByDescending<Card> { it.lapses }.thenByDescending { it.difficulty }).take(6)
    val byPage = cards.filter { it.docTitle != null }.groupBy { it.document to it.docTitle!! }.map { it.key to it.value.size }.sortedByDescending { it.second }.take(6)

    Tiles(listOf(
        Tile(app.kern.ui.stats.num(cards.size), "cards", "${app.kern.ui.stats.num(mature)} mature"),
        Tile("$streak", "day streak", "longest $longest"),
        Tile(app.kern.ui.stats.num(total), "reviews · 26 weeks", "${app.kern.ui.stats.num(s?.reviewedToday ?: 0)} today"),
        Tile(s?.accuracy30d?.let { "${it.toInt()}%" } ?: "—", "right · 30 days", s?.accuracyToday?.let { "${it.toInt()}% today" }),
        Tile(if (studied == 0) "—" else app.kern.ui.stats.num(total / studied), "reviews per study day", "studied $studied of 182 days"),
        Tile("${(s?.timeTodayMs ?: 0) / 60000}m", "studied today", "${s?.dueToday ?: 0} due · ${s?.newAvailable ?: 0} new"),
    ))
    Spacer(Modifier.height(6.dp))
    Panel("Reviews, last 30 days") {
        Bars(last30, emptyList(), detail = { i -> val dd = today.minusDays((29 - i).toLong()); "${dueLabel(dd.toString())} · ${pl(last30[i], "review")}" },
            axis = "30 days ago" to "Today")
    }
    Panel("Activity", "Every review in the last 26 weeks") { Heatmap(history) }
    Panel("Due in the next 30 days", "Cards in review, by the day they come due") {
        val f = s?.forecast.orEmpty().take(30)
        if (f.isEmpty()) Text("Nothing scheduled.", color = kern.text3)
        else Bars(f, emptyList(), detail = { i -> "${dueLabel(today.plusDays(i.toLong()).toString())} · ${f[i]} due" }, axis = "Today" to "+29d", highlight = 0)
    }
    Panel("Card states") {
        val c = s?.counts.orEmpty()
        Stacked(listOf(
            Segment("New", (c["new"] ?: 0).toLong()),
            Segment("Learning", (c["learning"] ?: 0).toLong()),
            Segment("Young", young.toLong()),
            Segment("Mature", mature.toLong()),
            Segment("Relearning", (c["relearning"] ?: 0).toLong()),
        ))
        if ((s?.suspended ?: 0) > 0) Text("${s!!.suspended} suspended", style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(top = 8.dp))
    }
    Panel("Memory strength", "How long cards in review are expected to stick (FSRS stability)") {
        Bars(stabBuckets.map { it.second }, stabBuckets.map { it.first }, detail = { i -> "${stabBuckets[i].first} · ${pl(stabBuckets[i].second, "card")}" }, height = 90)
    }
    Panel("When you study") {
        Bars(weekday, DayOfWeek.entries.map { wd(it).take(2) }, detail = { i -> "${wd(DayOfWeek.entries[i])} · ${pl(weekday[i], "review")}" }, height = 90)
    }
    Panel("Totals") {
        Facts(listOfNotNull(
            "Reviews ever (all cards)" to app.kern.ui.stats.num(totalReps),
            "Lapses (forgotten after learning)" to app.kern.ui.stats.num(totalLapses),
            "Lapse rate" to pct(totalLapses, totalReps),
            avgStab?.let { "Average stability" to days(it) },
            avgDiff?.let { "Average difficulty" to "%.1f / 10".format(it) },
            best?.let { "Best day" to "${it.value} on ${it.key}" },
            "Decks" to "${d.decks.size}",
            "Daily limits" to "${s?.settings?.newPerDay ?: 0} new · ${s?.settings?.reviewsPerDay ?: 0} reviews",
            "Target retention" to "${((s?.settings?.retention ?: 0.9) * 100).toInt()}%",
        ))
    }
    if (d.decks.isNotEmpty()) Panel("Decks") { Ranked(d.decks.sortedByDescending { it.total }.map { "${it.name} · ${it.due} due" to it.total }) { i -> nav.go("review?deck=${d.decks.sortedByDescending { it.total }[i].id}") } }
    if (byPage.isNotEmpty()) Panel("Pages with the most cards") { Ranked(byPage.map { it.first.second.ifBlank { "Untitled" } to it.second }) { i -> byPage[i].first.first?.let { nav.doc(it) } } }
    if (hardest.isNotEmpty()) Panel("Hardest cards", "Most often forgotten") {
        Ranked(hardest.map { Html.oneLine(it.front, 60).ifBlank { "Image card" } to it.lapses }) { i -> hardest[i].document?.let { nav.doc(it) } }
    }
}

// ------------------------------------------------------------------ tasks

@Composable
private fun TaskStatsView(d: StatsData, nav: Nav) {
    val today = LocalDate.now()
    val tasks = d.tasks
    val done = tasks.filter { it.done }
    val open = tasks.filter { !it.done }
    val doneOn = done.mapNotNull { localDate(it.completedAt) }
    val last30 = (29 downTo 0).map { back -> val dd = today.minusDays(back.toLong()); doneOn.count { it == dd } }
    val week = doneOn.count { !it.isBefore(today.minusDays(6)) }
    val month = doneOn.count { !it.isBefore(today.minusDays(29)) }
    val withDue = done.filter { it.due != null && it.completedAt != null }
    val onTime = withDue.count { t -> localDate(t.completedAt)?.let { it.toString() <= t.due!! } == true }
    val overdue = open.count { it.due != null && it.due < today.toString() }
    val dueToday = open.count { it.due == today.toString() }
    val leadDays = done.mapNotNull { t ->
        val a = parseInstant(t.createdAt); val b = parseInstant(t.completedAt)
        if (a != null && b != null) ChronoUnit.HOURS.between(a, b) / 24.0 else null
    }.sorted()
    val median = leadDays.getOrNull(leadDays.size / 2)
    val weekday = DayOfWeek.entries.map { dw -> doneOn.count { it.dayOfWeek == dw } }
    var streak = 0
    var day = if (doneOn.contains(today)) today else today.minusDays(1)
    while (doneOn.contains(day)) { streak++; day = day.minusDays(1) }
    val tagCounts = open.flatMap { it.tags }.groupingBy { it }.eachCount()
        .mapNotNull { (id, n) -> d.tags.firstOrNull { it.id == id }?.let { "#${it.name}" to n } }.sortedByDescending { it.second }.take(6)
    val heat = doneOn.groupingBy { it.toString() }.eachCount()

    Tiles(listOf(
        Tile(app.kern.ui.stats.num(open.size), "open", "$dueToday due today"),
        Tile(app.kern.ui.stats.num(done.size), "completed", "${pct(done.size, tasks.size)} of all tasks"),
        Tile("$week", "done this week", "$month in 30 days"),
        Tile("$overdue", "overdue", if (overdue == 0) "nothing late" else "need a new date"),
        Tile(pct(onTime, withDue.size), "done on time", "${withDue.size} with a due date"),
        Tile("$streak", "day streak", median?.let { "median ${days(it)} to finish" }),
    ))
    Spacer(Modifier.height(6.dp))
    Panel("Completed, last 30 days") {
        Bars(last30, emptyList(), detail = { i -> "${dueLabel(today.minusDays((29 - i).toLong()).toString())} · ${last30[i]} done" }, axis = "30 days ago" to "Today")
    }
    Panel("Completions", "Last 26 weeks") { Heatmap(heat, unit = "done") }
    Panel("Open tasks by priority") {
        Stacked(listOf(
            Segment("None", open.count { it.priority == 0 }.toLong()),
            Segment("Low", open.count { it.priority == 1 }.toLong()),
            Segment("Medium", open.count { it.priority == 2 }.toLong()),
            Segment("High", open.count { it.priority == 3 }.toLong()),
        ))
    }
    Panel("Open tasks by when") {
        Stacked(listOf(
            Segment("Overdue", overdue.toLong()),
            Segment("Today", dueToday.toLong()),
            Segment("This week", open.count { it.due != null && it.due > today.toString() && it.due <= today.plusDays(7).toString() }.toLong()),
            Segment("Later", open.count { it.due != null && it.due > today.plusDays(7).toString() }.toLong()),
            Segment("No date", open.count { it.due == null }.toLong()),
        ))
    }
    Panel("Which days you get things done") {
        Bars(weekday, DayOfWeek.entries.map { wd(it).take(2) }, detail = { i -> "${wd(DayOfWeek.entries[i])} · ${weekday[i]} done" }, height = 90)
    }
    Panel("More") {
        Facts(listOfNotNull(
            "Repeating tasks" to "${open.count { it.recurrence != null }}",
            "From pages (checklists)" to "${tasks.count { it.block != null }}",
            "In projects" to "${tasks.count { it.project != null }}",
            "With notes" to "${tasks.count { it.description.isNotBlank() }}",
            median?.let { "Median time to finish" to days(it) },
            leadDays.lastOrNull()?.let { "Longest time to finish" to days(it) },
            doneOn.groupingBy { it }.eachCount().maxByOrNull { it.value }?.let { "Most done in a day" to "${it.value} on ${it.key}" },
        ))
    }
    if (tagCounts.isNotEmpty()) Panel("Open tasks by tag") { Ranked(tagCounts) }
}

// ------------------------------------------------------------------ workspace

@Composable
private fun WorkspaceStatsView(d: StatsData, nav: Nav) {
    val st = d.storage
    val c = st?.counts
    val pages = d.tree.filter { it.entryOf == null && !it.isTemplate }
    val months = (11 downTo 0).map { YearMonth.now().minusMonths(it.toLong()) }
    val created = months.map { m -> pages.count { localDate(it.createdAt)?.let { YearMonth.from(it) } == m } }
    val edited7 = d.tree.count { localDate(it.updatedAt)?.isAfter(LocalDate.now().minusDays(7)) == true }
    fun depth(doc: Doc): Int { var n = 0; var p = doc.parent; val seen = mutableSetOf<String>(); while (p != null && seen.add(p)) { n++; p = d.tree.firstOrNull { it.id == p }?.parent }; return n }
    val deepest = pages.maxOfOrNull { depth(it) } ?: 0
    val oldest = pages.minByOrNull { it.createdAt ?: "~" }
    val biggestParent = pages.groupBy { it.parent }.filterKeys { it != null }.maxByOrNull { it.value.size }
    val topTags = d.tags.filter { (it.docCount ?: 0) > 0 }.sortedByDescending { it.docCount }.take(8)

    Tiles(listOf(
        Tile(app.kern.ui.stats.num(c?.pages ?: pages.size), "pages", pl(c?.entries ?: 0, "database entry", "database entries")),
        Tile(app.kern.ui.stats.num(c?.blocks ?: 0), "blocks", c?.let { if (it.pages > 0) "${it.blocks / it.pages} per page" else null }),
        Tile("${d.tags.size}", "tags", pl(c?.databases ?: 0, "database")),
        Tile("$edited7", "edited this week", pl(pages.count { it.isFavorite }, "favorite")),
        Tile(st?.let { bytes(it.databaseBytes + it.mediaBytes + it.gitBytes + it.backupsBytes) } ?: "—", "stored", pl(c?.files ?: d.files.size, "file")),
        Tile("${d.web.size}", "bookmarks", "${pl(d.chats.size, "chat")} · ${pl(d.repos.size, "repo")}"),
    ))
    Spacer(Modifier.height(6.dp))
    Panel("Pages created, last 12 months") {
        Bars(created, months.map { it.month.getDisplayName(TextStyle.NARROW, Locale.getDefault()) },
            detail = { i -> "${months[i].month.getDisplayName(TextStyle.FULL, Locale.getDefault())} ${months[i].year} · ${pl(created[i], "page")}" }, height = 100)
    }
    if (st != null) Panel("Storage") {
        Stacked(listOf(
            Segment("Notes", st.databaseBytes, bytes(st.databaseBytes)),
            Segment("Files", (st.mediaBytes - st.downloadsBytes).coerceAtLeast(0), bytes((st.mediaBytes - st.downloadsBytes).coerceAtLeast(0))),
            Segment("Videos", st.downloadsBytes, bytes(st.downloadsBytes)),
            Segment("Git", st.gitBytes, bytes(st.gitBytes)),
            Segment("Backups", st.backupsBytes, bytes(st.backupsBytes)),
        ))
    }
    if (d.files.isNotEmpty()) Panel("Files by type") {
        fun kind(f: LibraryFile) = when { f.mime.startsWith("image/") -> 0; f.mime.startsWith("video/") -> 1; f.mime.startsWith("audio/") -> 2; f.mime == "application/pdf" -> 3; else -> 4 }
        val names = listOf("Images", "Video", "Audio", "PDF", "Other")
        Stacked(names.mapIndexed { i, n -> d.files.filter { kind(it) == i }.let { fs -> Segment(n, fs.sumOf { it.size }, "${fs.size} · ${bytes(fs.sumOf { it.size })}") } })
    }
    if (d.web.isNotEmpty()) Panel("Bookmarks") {
        Stacked(listOf(
            Segment("Pages", d.web.count { it.kind == "web" }.toLong()),
            Segment("Videos", d.web.count { it.kind == "video" }.toLong()),
            Segment("Images", d.web.count { it.kind == "image" }.toLong()),
            Segment("Mixed", d.web.count { it.kind == "mixed" }.toLong()),
        ))
    }
    if (topTags.isNotEmpty()) Panel("Most used tags") { Ranked(topTags.map { "#${it.name}" to (it.docCount ?: 0) }) { i -> nav.go("tag/${topTags[i].id}") } }
    if (d.repos.isNotEmpty()) Panel("Git repositories") { Ranked(d.repos.sortedByDescending { it.size }.map { "${it.name} · ${bytes(it.size)}" to it.branches }) }
    Panel("More") {
        Facts(listOfNotNull(
            "Page versions kept" to app.kern.ui.stats.num(c?.versions ?: 0),
            "In the trash" to "${c?.trashed ?: 0}",
            "Archived" to "${pages.count { it.isArchived }}",
            "Templates" to "${d.tree.count { it.isTemplate }}",
            "Groups" to "${pages.count { it.kind == "group" }}",
            "Pages with an icon" to pct(pages.count { it.icon.isNotBlank() }, pages.size),
            "Deepest nesting" to pl(deepest, "level"),
            biggestParent?.let { (p, kids) -> "Most sub-pages" to "${kids.size} in ${d.tree.firstOrNull { it.id == p }?.displayTitle ?: "a page"}" },
            oldest?.let { "Oldest page" to "${it.displayTitle} · ${localDate(it.createdAt) ?: ""}" },
            "Flashcards / tasks" to "${c?.cards ?: 0} / ${c?.tasks ?: 0}",
        ))
    }
    Box(Modifier.padding(16.dp)) { Text("Pull down to refresh.", style = MaterialTheme.typography.bodySmall, color = kern.text3) }
}
