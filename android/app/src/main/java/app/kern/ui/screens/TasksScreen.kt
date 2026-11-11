package app.kern.ui.screens

import androidx.compose.animation.AnimatedVisibility
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.verticalScroll
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
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.BasicTextField
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowForward
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.CalendarToday
import androidx.compose.material.icons.outlined.Check
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Delete
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Flag
import androidx.compose.material.icons.outlined.Inbox
import androidx.compose.material.icons.outlined.Repeat
import androidx.compose.material.icons.outlined.Close
import androidx.compose.material3.DatePicker
import androidx.compose.material3.DatePickerDialog
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.PrimaryScrollableTabRow
import androidx.compose.material3.Tab
import androidx.compose.material3.TabRowDefaults
import androidx.compose.material3.TabRowDefaults.tabIndicatorOffset
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.pulltorefresh.PullToRefreshBox
import androidx.compose.material3.rememberDatePickerState
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
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
import androidx.compose.ui.focus.FocusRequester
import androidx.compose.ui.focus.focusRequester
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.SolidColor
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.dp
import app.kern.data.Recurrence
import app.kern.data.Tag
import app.kern.data.Task
import app.kern.data.TaskParse
import app.kern.notify.SyncWorker
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.Pill
import app.kern.ui.components.dueLabel
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.ZoneOffset

private val VIEWS = listOf("today" to "Today", "upcoming" to "Upcoming", "inbox" to "Inbox", "open" to "All open", "completed" to "Done")

@Composable
fun priorityColor(p: Int): Color = when (p) { 3 -> kern.red; 2 -> kern.orange; 1 -> kern.blue; else -> kern.text3 }

@Composable
fun TaskCheck(done: Boolean, priority: Int, onToggle: () -> Unit) {
    val c = priorityColor(priority)
    Box(
        Modifier.size(40.dp).clip(CircleShape).clickable(onClick = onToggle),
        contentAlignment = Alignment.Center,
    ) {
        Box(
            Modifier.size(20.dp).clip(CircleShape)
                .background(if (done) kern.accent else if (priority > 0) kern.tint(c) else Color.Transparent)
                .border(1.6.dp, if (done) kern.accent else c, CircleShape),
            contentAlignment = Alignment.Center,
        ) { if (done) Icon(Icons.Outlined.Check, null, Modifier.size(13.dp), tint = kern.onAccent) }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
fun TaskRow(t: Task, tags: List<Tag> = emptyList(), onToggle: () -> Unit, onClick: () -> Unit) {
    val today = LocalDate.now().toString()
    val late = !t.done && t.due != null && t.due < today
    Row(Modifier.fillMaxWidth().clickable(onClick = onClick).padding(start = 4.dp, end = 14.dp, top = 2.dp, bottom = 2.dp), verticalAlignment = Alignment.CenterVertically) {
        TaskCheck(t.done, t.priority, onToggle)
        Column(Modifier.weight(1f).padding(vertical = 8.dp)) {
            Text(
                t.title.ifBlank { "Untitled" },
                style = MaterialTheme.typography.bodyLarge,
                color = if (t.done) kern.text3 else kern.text,
                textDecoration = if (t.done) TextDecoration.LineThrough else null,
                maxLines = 3,
            )
            val hasMeta = t.due != null || t.recurrence != null || t.tags.isNotEmpty() || t.description.isNotBlank() || t.document != null
            if (hasMeta) {
                FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(2.dp), modifier = Modifier.padding(top = 2.dp)) {
                    if (t.due != null) Row(verticalAlignment = Alignment.CenterVertically) {
                        Icon(Icons.Outlined.CalendarToday, null, Modifier.size(12.dp), tint = if (late) kern.danger else kern.text3)
                        Spacer(Modifier.width(3.dp))
                        Text(dueLabel(t.due), style = MaterialTheme.typography.bodySmall, color = if (late) kern.danger else if (t.due == today) kern.green else kern.text3)
                    }
                    if (t.recurrence != null) Icon(Icons.Outlined.Repeat, "Repeats", Modifier.size(13.dp), tint = kern.text3)
                    if (t.document != null) Icon(Icons.Outlined.Description, "From a page", Modifier.size(13.dp), tint = kern.text3)
                    for (id in t.tags) tags.firstOrNull { it.id == id }?.let { tag -> Text("#${tag.name}", style = MaterialTheme.typography.bodySmall, color = kern.named(tag.color.ifBlank { "gray" })) }
                }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun TasksScreen(ws: Workspace, nav: Nav, openAdd: Boolean, openTask: String?) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val ctx = LocalContext.current
    val tags by ws.tags.collectAsState()
    var view by rememberSaveable { mutableStateOf("today") }
    var tasks by remember { mutableStateOf<List<Task>?>(null) }
    var error by remember { mutableStateOf<String?>(null) }
    var refreshing by remember { mutableStateOf(false) }
    var summary by remember { mutableStateOf<app.kern.data.TaskSummary?>(null) }
    var selected by remember { mutableStateOf<Task?>(null) }
    var adding by rememberSaveable { mutableStateOf(openAdd) }

    suspend fun load() {
        try {
            tasks = ws.kern.tasks(view)
            error = null
        } catch (e: Exception) { error = e.message }
        runCatching { summary = ws.kern.taskSummary() }
    }
    LaunchedEffect(view) { load() }
    LaunchedEffect(openTask) {
        if (openTask != null) runCatching { selected = ws.kern.api.get<Task>("/tasks/$openTask") }
    }

    fun toggle(t: Task) = scope.launch {
        tasks = tasks?.map { if (it.id == t.id) it.copy(done = !t.done) else it }
        try {
            ws.kern.updateTask(t.id, "done" to !t.done)
            SyncWorker.refreshSoon(ctx)
            if (!t.done) snack.show(if (t.recurrence != null) "Done — next one scheduled" else "Completed")
            kotlinx.coroutines.delay(600)
            load()
        } catch (e: Exception) { snack.error(e) }
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        Row(Modifier.fillMaxWidth().padding(start = 20.dp, end = 8.dp, top = 12.dp, bottom = 4.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text("Tasks", style = MaterialTheme.typography.headlineMedium)
                summary?.let { s ->
                    Text(
                        buildList {
                            add("${s.open} open")
                            if (s.overdue > 0) add("${s.overdue} overdue")
                            add("${s.completedWeek} done this week")
                        }.joinToString(" · "),
                        style = MaterialTheme.typography.bodySmall, color = kern.text3,
                    )
                }
            }
            IconButton(onClick = { adding = !adding }) { Icon(if (adding) Icons.Outlined.Close else Icons.Outlined.Add, "Add task", tint = kern.accent) }
        }
        val idx = VIEWS.indexOfFirst { it.first == view }
        PrimaryScrollableTabRow(
            selectedTabIndex = idx, edgePadding = 12.dp, containerColor = kern.bg, contentColor = kern.text,
            divider = { app.kern.ui.components.Divider() },
            indicator = { TabRowDefaults.PrimaryIndicator(Modifier.tabIndicatorOffset(idx, matchContentSize = true), color = kern.accent, width = androidx.compose.ui.unit.Dp.Unspecified) },
        ) {
            VIEWS.forEachIndexed { i, (key, label) ->
                val count = summary?.let { s -> when (key) { "today" -> s.today + s.overdue; "upcoming" -> s.upcoming; "inbox" -> s.inbox; else -> null } }
                Tab(i == idx, { view = key }, text = {
                    Text(if (count != null && count > 0) "$label  $count" else label, style = MaterialTheme.typography.labelLarge, color = if (i == idx) kern.text else kern.text2)
                })
            }
        }
        AnimatedVisibility(adding) {
            QuickAdd(ws, onAdded = { scope.launch { load(); SyncWorker.refreshSoon(ctx) } }, onClose = { adding = false })
        }
        PullToRefreshBox(refreshing, onRefresh = { scope.launch { refreshing = true; load(); refreshing = false } }, Modifier.weight(1f)) {
            when {
                tasks == null && error != null -> ErrorState(error!!) { scope.launch { load() } }
                tasks == null -> Loading()
                tasks!!.isEmpty() -> LazyColumn(Modifier.fillMaxSize()) {
                    item {
                        when (view) {
                            "today" -> EmptyState(Icons.Outlined.CheckCircle, "All clear for today", "Add a task with + — try “Call mum tomorrow !2 #family”.", action = "Add a task" to { adding = true })
                            "inbox" -> EmptyState(Icons.Outlined.Inbox, "Inbox zero", "Tasks without a date or project land here.")
                            else -> EmptyState(Icons.Outlined.CheckCircle, "No tasks here")
                        }
                    }
                }
                else -> {
                    val list = tasks!!
                    val today = LocalDate.now().toString()
                    val groups: List<Pair<String, List<Task>>> = when (view) {
                        "today" -> listOf("Overdue" to list.filter { (it.due ?: today) < today }, "Today" to list.filter { (it.due ?: today) >= today }).filter { it.second.isNotEmpty() }
                        "upcoming" -> list.groupBy { dueLabel(it.due) }.toList()
                        else -> listOf("" to list)
                    }
                    LazyColumn(Modifier.fillMaxSize()) {
                        for ((label, items) in groups) {
                            if (label.isNotEmpty()) item(key = "h-$label") {
                                Text(
                                    label.uppercase(), style = MaterialTheme.typography.labelSmall,
                                    color = if (label == "Overdue") kern.danger else kern.text3,
                                    modifier = Modifier.padding(start = 20.dp, top = 16.dp, bottom = 4.dp),
                                )
                            }
                            items(items, key = { it.id }) { t ->
                                Column(Modifier.animateItem()) {
                                    TaskRow(t, tags, onToggle = { toggle(t) }) { selected = t }
                                    app.kern.ui.components.Divider(Modifier.padding(start = 48.dp))
                                }
                            }
                        }
                        item { Spacer(Modifier.height(80.dp)) }
                    }
                }
            }
        }
    }

    selected?.let { t ->
        TaskSheet(ws, nav, t, onDismiss = { selected = null }, onChanged = { scope.launch { load(); SyncWorker.refreshSoon(ctx) } })
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun QuickAdd(ws: Workspace, onAdded: () -> Unit, onClose: () -> Unit) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var text by rememberSaveable { mutableStateOf("") }
    val parsed = remember(text) { TaskParse.parse(text) }
    val focus = remember { FocusRequester() }
    LaunchedEffect(Unit) { runCatching { focus.requestFocus() } }

    fun submit() {
        if (parsed.title.isBlank()) return
        val p = parsed
        text = ""
        scope.launch {
            try {
                val tagIds = p.tags.map { ws.ensureTag(it).id }
                ws.kern.createTask(p.title, p.due, p.priority, tagIds, p.recurrence)
                onAdded()
            } catch (e: Exception) { snack.error(e) }
        }
    }

    Column(Modifier.fillMaxWidth().background(kern.side).padding(horizontal = 16.dp, vertical = 10.dp)) {
        Row(
            Modifier.fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(kern.bg).border(1.dp, kern.borderStrong, RoundedCornerShape(12.dp)).padding(start = 14.dp, end = 4.dp),
            verticalAlignment = Alignment.CenterVertically,
        ) {
            Box(Modifier.weight(1f).padding(vertical = 12.dp)) {
                if (text.isEmpty()) Text("Pay rent tomorrow !2 #home every month", color = kern.text3, style = MaterialTheme.typography.bodyLarge)
                BasicTextField(
                    text, { v -> if (v.contains('\n')) { text = v.replace("\n", ""); submit() } else text = v },
                    singleLine = true,
                    textStyle = MaterialTheme.typography.bodyLarge.copy(color = kern.text),
                    cursorBrush = SolidColor(kern.accent),
                    keyboardOptions = KeyboardOptions(imeAction = ImeAction.Done),
                    keyboardActions = KeyboardActions(onDone = { submit() }),
                    modifier = Modifier.fillMaxWidth().focusRequester(focus),
                )
            }
            IconButton(onClick = { submit() }, enabled = parsed.title.isNotBlank()) {
                Icon(Icons.AutoMirrored.Outlined.ArrowForward, "Add", tint = if (parsed.title.isNotBlank()) kern.accent else kern.text3)
            }
        }
        if (parsed.tokens.isNotEmpty() || parsed.due != null) {
            FlowRow(Modifier.padding(top = 8.dp), horizontalArrangement = Arrangement.spacedBy(6.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                parsed.due?.let { Pill(dueLabel(it), kern.green) }
                if (parsed.priority > 0) Pill("Priority ${parsed.priority}", priorityColor(parsed.priority))
                parsed.recurrence?.let { Pill("Every ${if (it.interval > 1) "${it.interval} ${it.freq}s" else it.freq}", kern.purple) }
                parsed.tags.forEach { Pill("#$it", kern.blue) }
            }
        }
    }
}

@OptIn(ExperimentalMaterial3Api::class, ExperimentalLayoutApi::class)
@Composable
fun TaskSheet(ws: Workspace, nav: Nav, task: Task, onDismiss: () -> Unit, onChanged: () -> Unit) {
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val allTags by ws.tags.collectAsState()
    var t by remember(task.id) { mutableStateOf(task) }
    var title by remember(task.id) { mutableStateOf(task.title) }
    var desc by remember(task.id) { mutableStateOf(task.description) }
    var picking by remember { mutableStateOf(false) }
    var newTag by remember { mutableStateOf("") }

    fun save(vararg f: Pair<String, Any?>) = scope.launch {
        try { t = ws.kern.updateTask(t.id, *f); onChanged() } catch (e: Exception) { snack.error(e) }
    }

    ModalBottomSheet(
        onDismissRequest = {
            if (title != t.title || desc != t.description) save("title" to title, "description" to desc)
            onDismiss()
        },
        sheetState = sheet, containerColor = kern.surface,
    ) {
        Column(Modifier.fillMaxWidth().verticalScroll(rememberScrollState()).imePadding().navigationBarsPadding().padding(horizontal = 20.dp).padding(bottom = 16.dp), verticalArrangement = Arrangement.spacedBy(14.dp)) {
            Row(verticalAlignment = Alignment.Top) {
                Box(Modifier.padding(top = 4.dp)) { TaskCheck(t.done, t.priority) { save("done" to !t.done) } }
                BasicTextField(
                    title, { title = it },
                    textStyle = MaterialTheme.typography.titleLarge.copy(color = kern.text),
                    cursorBrush = SolidColor(kern.accent),
                    modifier = Modifier.weight(1f).padding(top = 12.dp),
                )
            }
            KField(desc, { desc = it }, "Notes", singleLine = false, minLines = 2)

            Text("DUE", style = MaterialTheme.typography.labelSmall, color = kern.text3)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                val today = LocalDate.now()
                Choice("Today", t.due == today.toString()) { save("due" to today.toString()) }
                Choice("Tomorrow", t.due == today.plusDays(1).toString()) { save("due" to today.plusDays(1).toString()) }
                Choice("Next week", t.due == today.plusDays(7).toString()) { save("due" to today.plusDays(7).toString()) }
                Choice(if (t.due != null && t.due!! !in listOf(today.toString(), today.plusDays(1).toString(), today.plusDays(7).toString())) dueLabel(t.due) else "Pick date…", false) { picking = true }
                if (t.due != null) Choice("No date", false) { save("due" to null) }
            }

            Text("PRIORITY", style = MaterialTheme.typography.labelSmall, color = kern.text3)
            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                listOf(0 to "None", 1 to "Low", 2 to "Medium", 3 to "High").forEach { (p, l) ->
                    Choice(l, t.priority == p, if (p > 0) priorityColor(p) else null) { save("priority" to p) }
                }
            }

            Text("REPEAT", style = MaterialTheme.typography.labelSmall, color = kern.text3)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                Choice("Never", t.recurrence == null) { save("recurrence" to null) }
                listOf("day" to "Daily", "week" to "Weekly", "month" to "Monthly", "year" to "Yearly").forEach { (f, l) ->
                    Choice(l, t.recurrence?.freq == f && t.recurrence?.interval == 1) { save("recurrence" to Recurrence(f, 1), "due" to (t.due ?: LocalDate.now().toString())) }
                }
            }

            Text("TAGS", style = MaterialTheme.typography.labelSmall, color = kern.text3)
            FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                for (tag in allTags.sortedByDescending { it.id in t.tags }.take(24)) {
                    val on = tag.id in t.tags
                    Choice("#${tag.name}", on, kern.named(tag.color.ifBlank { "gray" })) {
                        save("tags" to if (on) t.tags - tag.id else t.tags + tag.id)
                    }
                }
            }
            Row(verticalAlignment = Alignment.CenterVertically) {
                KField(newTag, { newTag = it.trimStart('#') }, "New tag", Modifier.weight(1f), keyboard = KeyboardOptions(imeAction = ImeAction.Done),
                    actions = KeyboardActions(onDone = {
                        val name = newTag.trim(); if (name.isEmpty()) return@KeyboardActions
                        newTag = ""
                        scope.launch { runCatching { val tg = ws.ensureTag(name); t = ws.kern.updateTask(t.id, "tags" to t.tags + tg.id); onChanged() }.onFailure { snack.error(it) } }
                    }))
            }

            Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                val doc = t.document ?: t.project
                if (doc != null) KButton("Open page", icon = Icons.Outlined.Description) { onDismiss(); nav.doc(doc) }
                Spacer(Modifier.weight(1f))
                KButton("Delete", icon = Icons.Outlined.Delete) {
                    scope.launch { runCatching { ws.kern.deleteTask(t.id) }.onSuccess { onChanged(); onDismiss() }.onFailure { snack.error(it) } }
                }
            }
        }
    }

    if (picking) {
        val state = rememberDatePickerState(
            initialSelectedDateMillis = (t.due?.let { runCatching { LocalDate.parse(it) }.getOrNull() } ?: LocalDate.now()).atStartOfDay().toInstant(ZoneOffset.UTC).toEpochMilli()
        )
        DatePickerDialog(
            onDismissRequest = { picking = false },
            confirmButton = {
                TextButton(onClick = {
                    picking = false
                    state.selectedDateMillis?.let { save("due" to Instant.ofEpochMilli(it).atZone(ZoneOffset.UTC).toLocalDate().toString()) }
                }) { Text("Set", color = kern.accent) }
            },
            dismissButton = { TextButton(onClick = { picking = false }) { Text("Cancel", color = kern.text2) } },
        ) { DatePicker(state) }
    }
}

@Composable
fun Choice(label: String, selected: Boolean, color: Color? = null, onClick: () -> Unit) {
    val c = color ?: kern.accent
    val shape = RoundedCornerShape(8.dp)
    Text(
        label,
        style = MaterialTheme.typography.labelLarge,
        fontWeight = if (selected) FontWeight.SemiBold else FontWeight.Normal,
        color = if (selected) c else if (color != null) color else kern.text2,
        modifier = Modifier.clip(shape)
            .background(if (selected) kern.tint(c) else Color.Transparent)
            .border(1.dp, if (selected) c.copy(alpha = 0.5f) else kern.borderStrong, shape)
            .clickable(onClick = onClick)
            .padding(horizontal = 12.dp, vertical = 7.dp),
    )
}
