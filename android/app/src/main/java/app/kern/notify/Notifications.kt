package app.kern.notify

import android.Manifest
import android.app.NotificationChannel
import android.app.NotificationManager
import android.app.PendingIntent
import android.content.Context
import android.content.Intent
import android.content.pm.PackageManager
import android.os.Build
import androidx.core.app.NotificationCompat
import androidx.core.app.NotificationManagerCompat
import androidx.core.content.ContextCompat
import app.kern.MainActivity
import app.kern.R
import app.kern.data.Task
import java.time.LocalDate

object Notifications {
    const val CH_TASKS = "tasks"
    const val CH_CARDS = "cards"
    const val CH_GENERAL = "general"
    private const val GROUP_TASKS = "app.kern.TASKS"
    const val ID_CARDS = 2
    const val ID_TASK_SUMMARY = 3
    const val ID_GENERAL = 4
    private const val ACCENT = 0xFFE2A85A.toInt()

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        nm.createNotificationChannels(
            listOf(
                NotificationChannel(CH_TASKS, "Tasks due", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Tasks due today and overdue tasks, once a day"
                },
                NotificationChannel(CH_CARDS, "Flashcard reviews", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "A daily reminder when flashcards are due"
                },
                NotificationChannel(CH_GENERAL, "Updates", NotificationManager.IMPORTANCE_LOW).apply {
                    description = "Bookmarks finished saving and similar updates"
                },
            )
        )
    }

    fun allowed(ctx: Context) = Build.VERSION.SDK_INT < 33 ||
        ContextCompat.checkSelfPermission(ctx, Manifest.permission.POST_NOTIFICATIONS) == PackageManager.PERMISSION_GRANTED

    fun openIntent(ctx: Context, route: String, code: Int): PendingIntent {
        val i = Intent(ctx, MainActivity::class.java).apply {
            action = Intent.ACTION_VIEW
            putExtra(MainActivity.EXTRA_ROUTE, route)
            flags = Intent.FLAG_ACTIVITY_NEW_TASK or Intent.FLAG_ACTIVITY_SINGLE_TOP
        }
        return PendingIntent.getActivity(ctx, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    private fun actionIntent(ctx: Context, action: String, task: Task, code: Int): PendingIntent {
        val i = Intent(ctx, ActionReceiver::class.java).apply {
            this.action = action
            putExtra(ActionReceiver.EXTRA_TASK, task.id)
            putExtra(ActionReceiver.EXTRA_NOTIFICATION, task.id.hashCode())
        }
        return PendingIntent.getBroadcast(ctx, code, i, PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT)
    }

    fun taskId(task: Task) = task.id.hashCode()

    fun showTasks(ctx: Context, tasks: List<Task>) {
        if (!allowed(ctx) || tasks.isEmpty()) return
        val nm = NotificationManagerCompat.from(ctx)
        val today = LocalDate.now().toString()
        val overdue = tasks.count { (it.due ?: today) < today }
        val shown = tasks.take(6)
        try {
            for ((n, t) in shown.withIndex()) {
                val late = (t.due ?: today) < today
                val b = NotificationCompat.Builder(ctx, CH_TASKS)
                    .setSmallIcon(R.drawable.ic_stat_kern)
                    .setColor(ACCENT)
                    .setContentTitle(t.title.ifBlank { "Untitled task" })
                    .setContentText(if (late) "Overdue · was due ${t.due}" else "Due today" + priorityLabel(t.priority))
                    .setGroup(GROUP_TASKS)
                    .setAutoCancel(true)
                    .setContentIntent(openIntent(ctx, "tasks?task=${t.id}", 100 + n))
                    .addAction(0, "Done", actionIntent(ctx, ActionReceiver.ACTION_DONE, t, 200 + n))
                    .addAction(0, "Tomorrow", actionIntent(ctx, ActionReceiver.ACTION_TOMORROW, t, 300 + n))
                    .setCategory(NotificationCompat.CATEGORY_REMINDER)
                if (t.description.isNotBlank()) b.setStyle(NotificationCompat.BigTextStyle().bigText(t.description.take(400)))
                nm.notify(taskId(t), b.build())
            }
            val summary = NotificationCompat.Builder(ctx, CH_TASKS)
                .setSmallIcon(R.drawable.ic_stat_kern)
                .setColor(ACCENT)
                .setContentTitle("${tasks.size} task${if (tasks.size == 1) "" else "s"} for today")
                .setContentText(if (overdue > 0) "$overdue overdue" else shown.joinToString(", ") { it.title })
                .setStyle(NotificationCompat.InboxStyle().also { s -> shown.forEach { s.addLine(it.title) } })
                .setGroup(GROUP_TASKS)
                .setGroupSummary(true)
                .setAutoCancel(true)
                .setContentIntent(openIntent(ctx, "tasks", 99))
                .build()
            nm.notify(ID_TASK_SUMMARY, summary)
        } catch (_: SecurityException) {
        }
    }

    private fun priorityLabel(p: Int) = when (p) { 3 -> " · high priority"; 2 -> " · medium priority"; 1 -> " · low priority"; else -> "" }

    fun showCards(ctx: Context, due: Int, new: Int) {
        if (!allowed(ctx) || due + new == 0) return
        val text = buildList {
            if (due > 0) add("$due to review")
            if (new > 0) add("$new new")
        }.joinToString(" · ")
        val n = NotificationCompat.Builder(ctx, CH_CARDS)
            .setSmallIcon(R.drawable.ic_stat_kern)
            .setColor(ACCENT)
            .setContentTitle("Flashcards are waiting")
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(openIntent(ctx, "review", 50))
            .addAction(0, "Review now", openIntent(ctx, "review", 51))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(ID_CARDS, n) } catch (_: SecurityException) {}
    }

    fun showGeneral(ctx: Context, title: String, text: String, route: String) {
        if (!allowed(ctx)) return
        val n = NotificationCompat.Builder(ctx, CH_GENERAL)
            .setSmallIcon(R.drawable.ic_stat_kern)
            .setColor(ACCENT)
            .setContentTitle(title)
            .setContentText(text)
            .setAutoCancel(true)
            .setContentIntent(openIntent(ctx, route, 60))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(ID_GENERAL + route.hashCode(), n) } catch (_: SecurityException) {}
    }

    fun cancel(ctx: Context, id: Int) = NotificationManagerCompat.from(ctx).cancel(id)
}
