package app.kern.ui.screens

import android.content.Intent
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import app.kern.data.Settings
import app.kern.notify.Notifications
import app.kern.notify.SyncWorker
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.Divider
import app.kern.ui.components.KButton
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import java.time.DayOfWeek
import java.time.format.TextStyle
import java.util.Locale

private fun every(m: Int) = when (m) { 0 -> "once a day"; 60 -> "every hour"; 90 -> "every 1½ h"; else -> "every ${m / 60} h" }

/** One line for the Settings row. */
fun reminderSummary(s: Settings): String = buildList {
    if (s.notifyCards) add("Cards ${every(s.cardsEveryMin)}")
    if (s.notifyTasks) add("tasks daily")
    if (isEmpty()) add("Off")
    add("%02d:00–%s".format(s.notifyHour, if (s.quietHour == 24) "midnight" else "%02d:00".format(s.quietHour)))
}.joinToString(" · ").replaceFirstChar { it.uppercase() }

@Composable
fun RemindersScreen(ws: Workspace, nav: Nav) {
    val s = ws.settings
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current

    var cards by remember { mutableStateOf(s.notifyCards) }
    var every by remember { mutableStateOf(s.cardsEveryMin) }
    var min by remember { mutableStateOf(s.cardsMin) }
    var includeNew by remember { mutableStateOf(s.cardsIncludeNew) }
    var snooze by remember { mutableStateOf(s.cardsSnoozeMin) }
    var tasks by remember { mutableStateOf(s.notifyTasks) }
    var overdue by remember { mutableStateOf(s.tasksIncludeOverdue) }
    var priority by remember { mutableStateOf(s.tasksMinPriority) }
    var from by remember { mutableStateOf(s.notifyHour) }
    var quiet by remember { mutableStateOf(s.quietHour) }
    var days by remember { mutableStateOf(s.reminderDays) }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Reminders", onBack = { nav.back() })
        LazyColumn {
            item { Heading("Flashcards") }
            item {
                Bordered {
                    Switchy("Remind me to study", "While cards are waiting, again after a break", cards) { cards = it; s.notifyCards = it }
                    if (cards) {
                        Divider()
                        Options("How often", listOf(60 to "Every hour", 90 to "Every 1½ h", 120 to "Every 2 h", 180 to "Every 3 h", 240 to "Every 4 h", 0 to "Once a day"), every) {
                            every = it; s.cardsEveryMin = it
                        }
                        Hint("Studying restarts the wait, so you're not reminded right after a session.")
                        Divider()
                        Options("Only when at least", listOf(1 to "1 card", 5 to "5 cards", 10 to "10", 20 to "20", 50 to "50"), min) { min = it; s.cardsMin = it }
                        Hint("are waiting")
                        Divider()
                        Switchy("Count new cards", "Off: only cards due for review trigger a reminder", includeNew) { includeNew = it; s.cardsIncludeNew = it }
                        Divider()
                        Options("“Later” waits", listOf(15 to "15 min", 30 to "30 min", 60 to "1 h", 120 to "2 h", 240 to "4 h"), snooze) { snooze = it; s.cardsSnoozeMin = it }
                    }
                }
            }
            item { Heading("Tasks") }
            item {
                Bordered {
                    Switchy("Tasks due today", "Once a day, each with Done and Tomorrow buttons", tasks) { tasks = it; s.notifyTasks = it }
                    if (tasks) {
                        Divider()
                        Switchy("Include overdue tasks", "Tasks whose date has passed", overdue) { overdue = it; s.tasksIncludeOverdue = it }
                        Divider()
                        Options("Which tasks", listOf(0 to "All", 1 to "Low and up", 2 to "Medium and up", 3 to "High only"), priority) { priority = it; s.tasksMinPriority = it }
                    }
                }
            }
            item { Heading("Schedule") }
            item {
                Bordered {
                    Options("Start at", listOf(6, 7, 8, 9, 10, 12).map { it to "%02d:00".format(it) }, from) { from = it; s.notifyHour = it }
                    Hint("Task reminders are sent at this time; card reminders can start then.")
                    Divider()
                    Options("Quiet after", listOf(18, 20, 21, 22, 23, 24).map { it to if (it == 24) "Midnight" else "%02d:00".format(it) }, quiet) { quiet = it; s.quietHour = it }
                    Divider()
                    Column(Modifier.padding(14.dp)) {
                        Text("Days", style = MaterialTheme.typography.bodyLarge)
                        Spacer(Modifier.height(8.dp))
                        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                            DayOfWeek.entries.forEach { d ->
                                val on = d.value in days
                                Choice(d.getDisplayName(TextStyle.SHORT, Locale.getDefault()), on) {
                                    val next = if (on) days - d.value else days + d.value
                                    if (next.isNotEmpty()) { days = next; s.reminderDays = next }
                                }
                            }
                        }
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            Choice("Every day", days.size == 7) { days = (1..7).toSet(); s.reminderDays = days }
                            Choice("Weekdays", days == (1..5).toSet()) { days = (1..5).toSet(); s.reminderDays = days }
                            Choice("Weekends", days == setOf(6, 7)) { days = setOf(6, 7); s.reminderDays = days }
                        }
                    }
                }
            }
            item {
                Row(Modifier.fillMaxWidth().padding(16.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KButton("Send a test") {
                        scope.launch {
                            runCatching { SyncWorker.refresh(ctx) }
                            val t = s.cachedTasks.filter { !it.done }
                            if (t.isNotEmpty()) Notifications.showTasks(ctx, t) else Notifications.showGeneral(ctx, "Kern reminders work", "Nothing is due today.", "tasks")
                            if (s.cachedDue + s.cachedNew > 0) Notifications.showCards(ctx, s.cachedDue, s.cachedNew)
                            if (!Notifications.allowed(ctx)) snack.show("Notifications are turned off for Kern in Android settings.")
                        }
                    }
                    KButton("Sound & vibration") {
                        ctx.startActivity(Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(AndroidSettings.EXTRA_APP_PACKAGE, ctx.packageName))
                    }
                }
            }
            item { Spacer(Modifier.height(24.dp)) }
        }
    }
}

@Composable
private fun Switchy(title: String, sub: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onChange(!on) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(sub, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
        Switch(on, onChange, colors = SwitchDefaults.colors(checkedTrackColor = kern.accent, checkedThumbColor = kern.onAccent))
    }
}

@Composable
private fun Options(title: String, options: List<Pair<Int, String>>, value: Int, onPick: (Int) -> Unit) {
    Column(Modifier.padding(start = 14.dp, end = 14.dp, top = 14.dp, bottom = 10.dp)) {
        Text(title, style = MaterialTheme.typography.bodyLarge)
        Spacer(Modifier.height(8.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(8.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
            options.forEach { (v, l) -> Choice(l, value == v) { onPick(v) } }
        }
    }
}

@Composable
private fun Hint(text: String) =
    Text(text, style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(start = 14.dp, end = 14.dp, bottom = 12.dp))
