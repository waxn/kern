package app.kern.widget

import android.content.Context
import android.content.Intent
import androidx.compose.runtime.Composable
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import androidx.glance.ColorFilter
import androidx.glance.GlanceId
import androidx.glance.GlanceModifier
import androidx.glance.GlanceTheme
import androidx.glance.Image
import androidx.glance.ImageProvider
import androidx.glance.action.ActionParameters
import androidx.glance.action.actionParametersOf
import androidx.glance.action.clickable
import androidx.glance.appwidget.GlanceAppWidget
import androidx.glance.appwidget.GlanceAppWidgetReceiver
import androidx.glance.appwidget.SizeMode
import androidx.glance.appwidget.action.ActionCallback
import androidx.glance.appwidget.action.actionRunCallback
import androidx.glance.appwidget.action.actionStartActivity
import androidx.glance.appwidget.cornerRadius
import androidx.glance.appwidget.lazy.LazyColumn
import androidx.glance.appwidget.lazy.items
import androidx.glance.appwidget.provideContent
import androidx.glance.appwidget.updateAll
import androidx.glance.background
import androidx.glance.color.ColorProvider
import androidx.glance.layout.Alignment
import androidx.glance.layout.Box
import androidx.glance.layout.Column
import androidx.glance.layout.Row
import androidx.glance.layout.Spacer
import androidx.glance.layout.fillMaxSize
import androidx.glance.layout.fillMaxWidth
import androidx.glance.layout.height
import androidx.glance.layout.padding
import androidx.glance.layout.size
import androidx.glance.layout.width
import androidx.glance.text.FontWeight
import androidx.glance.text.Text
import androidx.glance.text.TextStyle
import app.kern.MainActivity
import app.kern.R
import app.kern.app
import app.kern.data.Task
import app.kern.notify.SyncWorker
import java.time.LocalDate

private object W {
    val bg = ColorProvider(day = Color(0xFFFCFBF9), night = Color(0xFF131315))
    val surface = ColorProvider(day = Color(0xFFF1EFEA), night = Color(0xFF212125))
    val text = ColorProvider(day = Color(0xFF23221F), night = Color(0xFFE7E5E0))
    val text2 = ColorProvider(day = Color(0xFF696761), night = Color(0xFFA5A39D))
    val text3 = ColorProvider(day = Color(0xFF9A978F), night = Color(0xFF706E69))
    val accent = ColorProvider(day = Color(0xFFB4721F), night = Color(0xFFE2A85A))
    val onAccent = ColorProvider(day = Color(0xFFFFFFFF), night = Color(0xFF17130C))
    val blue = ColorProvider(day = Color(0xFF2F74B8), night = Color(0xFF74A9E0))
    val danger = ColorProvider(day = Color(0xFFC9443A), night = Color(0xFFE8695F))
}

fun openApp(ctx: Context, route: String): Intent = Intent(ctx, MainActivity::class.java).apply {
    action = "app.kern.ROUTE.$route" // unique per route so the intents are not merged
    putExtra(MainActivity.EXTRA_ROUTE, route)
    flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_CLEAR_TOP
}

object Widgets {
    suspend fun updateAll(ctx: Context) {
        runCatching { TasksWidget().updateAll(ctx) }
        runCatching { CardsWidget().updateAll(ctx) }
        runCatching { RecentWidget().updateAll(ctx) }
    }
}

@Composable
private fun Header(title: String, sub: String?, ctx: Context, plusRoute: String?) {
    Row(GlanceModifier.fillMaxWidth().padding(start = 14.dp, end = 8.dp, top = 12.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(GlanceModifier.defaultWeight().clickable(actionStartActivity(openApp(ctx, if (plusRoute == "new-task") "tasks" else "home")))) {
            Text(title, style = TextStyle(color = W.text, fontSize = 15.sp, fontWeight = FontWeight.Bold))
            if (sub != null) Text(sub, style = TextStyle(color = W.text3, fontSize = 11.sp))
        }
        Image(
            ImageProvider(R.drawable.ic_w_refresh), "Refresh",
            modifier = GlanceModifier.size(30.dp).padding(6.dp).clickable(actionRunCallback<RefreshAction>()),
            colorFilter = ColorFilter.tint(W.text3),
        )
        if (plusRoute != null) {
            Box(
                GlanceModifier.size(30.dp).cornerRadius(15.dp).background(W.accent).clickable(actionStartActivity(openApp(ctx, plusRoute))),
                contentAlignment = Alignment.Center,
            ) {
                Image(ImageProvider(R.drawable.ic_w_add), "Add", modifier = GlanceModifier.size(18.dp), colorFilter = ColorFilter.tint(W.onAccent))
            }
        }
    }
}

class RefreshAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        runCatching { SyncWorker.refresh(context) }
    }
}

// ------------------------------------------------------------------ tasks

private val TaskKey = ActionParameters.Key<String>("task")

class CompleteTaskAction : ActionCallback {
    override suspend fun onAction(context: Context, glanceId: GlanceId, parameters: ActionParameters) {
        val id = parameters[TaskKey] ?: return
        val s = context.app.settings
        // Optimistic: drop it from the list at once, then tell the server.
        s.cachedTasks = s.cachedTasks.filter { it.id != id }
        TasksWidget().updateAll(context)
        runCatching { context.app.kern.updateTask(id, "done" to true) }
        runCatching { SyncWorker.refresh(context) }
    }
}

class TasksWidget : GlanceAppWidget() {
    override val sizeMode = SizeMode.Exact
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent {
            GlanceTheme {
                TasksContent(context, context.app.settings.cachedTasks.filter { !it.done }, context.app.settings.user != null)
            }
        }
    }
}

@Composable
private fun TasksContent(ctx: Context, tasks: List<Task>, signedIn: Boolean) {
    val today = LocalDate.now().toString()
    val overdue = tasks.count { (it.due ?: today) < today }
    Column(GlanceModifier.fillMaxSize().background(W.bg).cornerRadius(20.dp)) {
        Header("Today", if (!signedIn) "Sign in to Kern" else if (tasks.isEmpty()) "Nothing due" else "${tasks.size} open" + if (overdue > 0) " · $overdue overdue" else "", ctx, "new-task")
        if (tasks.isEmpty()) {
            Box(GlanceModifier.fillMaxSize().padding(16.dp), contentAlignment = Alignment.Center) {
                Text(if (signedIn) "All clear ✓" else "Open Kern to sign in", style = TextStyle(color = W.text2, fontSize = 13.sp))
            }
        } else {
            LazyColumn(GlanceModifier.fillMaxSize().padding(horizontal = 6.dp)) {
                items(tasks, itemId = { it.id.hashCode().toLong() }) { t ->
                    val late = (t.due ?: today) < today
                    Row(GlanceModifier.fillMaxWidth().padding(vertical = 3.dp), verticalAlignment = Alignment.CenterVertically) {
                        Image(
                            ImageProvider(R.drawable.ic_w_check_off), "Complete",
                            modifier = GlanceModifier.size(36.dp).padding(8.dp).clickable(actionRunCallback<CompleteTaskAction>(actionParametersOf(TaskKey to t.id))),
                            colorFilter = ColorFilter.tint(when (t.priority) { 3 -> W.danger; 2 -> W.accent; 1 -> W.blue; else -> W.text3 }),
                        )
                        Column(GlanceModifier.defaultWeight().clickable(actionStartActivity(openApp(ctx, "tasks?task=${t.id}")))) {
                            Text(t.title.ifBlank { "Untitled" }, maxLines = 2, style = TextStyle(color = W.text, fontSize = 13.5.sp))
                            if (late) Text("Overdue · ${t.due}", style = TextStyle(color = W.danger, fontSize = 11.sp))
                        }
                    }
                }
            }
        }
    }
}

class TasksWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = TasksWidget()
}

// ------------------------------------------------------------------ flashcards

class CardsWidget : GlanceAppWidget() {
    override val sizeMode = SizeMode.Exact
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val s = context.app.settings
        provideContent {
            GlanceTheme {
                val due = s.cachedDue
                val new = s.cachedNew
                Column(
                    GlanceModifier.fillMaxSize().background(W.bg).cornerRadius(20.dp).padding(14.dp)
                        .clickable(actionStartActivity(openApp(context, "review"))),
                    verticalAlignment = Alignment.CenterVertically,
                    horizontalAlignment = Alignment.CenterHorizontally,
                ) {
                    Image(ImageProvider(R.drawable.ic_w_cards), null, modifier = GlanceModifier.size(20.dp), colorFilter = ColorFilter.tint(W.accent))
                    Spacer(GlanceModifier.height(4.dp))
                    Text("$due", style = TextStyle(color = if (due > 0) W.text else W.text3, fontSize = 34.sp, fontWeight = FontWeight.Bold))
                    Text(if (due == 1) "card due" else "cards due", style = TextStyle(color = W.text2, fontSize = 12.sp))
                    if (new > 0) Text("+ $new new", style = TextStyle(color = W.accent, fontSize = 11.sp, fontWeight = FontWeight.Medium))
                }
            }
        }
    }
}

class CardsWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = CardsWidget()
}

// ------------------------------------------------------------------ capture bar

class CaptureWidget : GlanceAppWidget() {
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        provideContent {
            GlanceTheme {
                Row(
                    GlanceModifier.fillMaxSize().background(W.bg).cornerRadius(28.dp).padding(horizontal = 6.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Box(GlanceModifier.size(44.dp).clickable(actionStartActivity(openApp(context, "home"))), contentAlignment = Alignment.Center) {
                        Image(ImageProvider(R.drawable.ic_w_logo), "Kern", modifier = GlanceModifier.size(26.dp))
                    }
                    Box(
                        GlanceModifier.defaultWeight().height(40.dp).cornerRadius(20.dp).background(W.surface)
                            .clickable(actionStartActivity(openApp(context, "search"))),
                        contentAlignment = Alignment.CenterStart,
                    ) {
                        Row(GlanceModifier.padding(horizontal = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                            Image(ImageProvider(R.drawable.ic_w_search), null, modifier = GlanceModifier.size(16.dp), colorFilter = ColorFilter.tint(W.text3))
                            Spacer(GlanceModifier.width(8.dp))
                            Text("Search", style = TextStyle(color = W.text3, fontSize = 13.sp))
                        }
                    }
                    CaptureButton(context, R.drawable.ic_w_page, "New page", "new-page")
                    CaptureButton(context, R.drawable.ic_w_task, "New task", "new-task")
                    CaptureButton(context, R.drawable.ic_w_bookmark, "Bookmark", "new-bookmark")
                }
            }
        }
    }
}

@Composable
private fun CaptureButton(ctx: Context, icon: Int, label: String, route: String) {
    Box(GlanceModifier.size(42.dp).clickable(actionStartActivity(openApp(ctx, route))), contentAlignment = Alignment.Center) {
        Image(ImageProvider(icon), label, modifier = GlanceModifier.size(22.dp), colorFilter = ColorFilter.tint(W.accent))
    }
}

class CaptureWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = CaptureWidget()
}

// ------------------------------------------------------------------ pages

class RecentWidget : GlanceAppWidget() {
    override val sizeMode = SizeMode.Exact
    override suspend fun provideGlance(context: Context, id: GlanceId) {
        val docs = context.app.settings.cachedDocs
        provideContent {
            GlanceTheme {
                Column(GlanceModifier.fillMaxSize().background(W.bg).cornerRadius(20.dp)) {
                    Header("Pages", if (docs.isEmpty()) "Nothing yet" else null, context, "new-page")
                    LazyColumn(GlanceModifier.fillMaxSize().padding(horizontal = 8.dp)) {
                        items(docs, itemId = { it.id.hashCode().toLong() }) { d ->
                            Row(
                                GlanceModifier.fillMaxWidth().padding(horizontal = 6.dp, vertical = 7.dp)
                                    .clickable(actionStartActivity(openApp(context, "doc/${d.id}"))),
                                verticalAlignment = Alignment.CenterVertically,
                            ) {
                                if (d.icon.isNotBlank()) Text(d.icon, style = TextStyle(fontSize = 14.sp))
                                else Image(ImageProvider(R.drawable.ic_w_page), null, modifier = GlanceModifier.size(15.dp), colorFilter = ColorFilter.tint(W.text3))
                                Spacer(GlanceModifier.width(8.dp))
                                Text(d.displayTitle, maxLines = 1, style = TextStyle(color = W.text, fontSize = 13.5.sp), modifier = GlanceModifier.defaultWeight())
                                if (d.isFavorite) Image(ImageProvider(R.drawable.ic_w_star), null, modifier = GlanceModifier.size(12.dp), colorFilter = ColorFilter.tint(W.accent))
                            }
                        }
                    }
                }
            }
        }
    }
}

class RecentWidgetReceiver : GlanceAppWidgetReceiver() {
    override val glanceAppWidget: GlanceAppWidget = RecentWidget()
}
