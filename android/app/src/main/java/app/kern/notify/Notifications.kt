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
import app.kern.app
import app.kern.data.Task
import java.time.LocalDate

object Notifications {
    const val CH_TASKS = "tasks"
    const val CH_CARDS = "cards"
    const val CH_GENERAL = "general"
    const val CH_WEB = "web"
    const val CH_MAIL = "mail"
    const val ID_MAIL = 5
    // Kern Mail
    const val CH_MAIL_NEW = "mail_new"
    const val CH_PUSH = "mail_push"
    const val ID_PUSH = 6
    private const val GROUP_MAIL = "app.kern.MAIL"
    private const val ID_MAIL_SUMMARY = 7
    private const val GROUP_TASKS = "app.kern.TASKS"
    const val ID_CARDS = 2
    const val ID_TASK_SUMMARY = 3
    const val ID_GENERAL = 4
    private const val ACCENT = 0xFFE2A85A.toInt()

    fun createChannels(ctx: Context) {
        val nm = ctx.getSystemService(NotificationManager::class.java)
        if (app.kern.BuildConfig.MAIL_APP) {
            nm.createNotificationChannels(
                listOf(
                    NotificationChannel(CH_MAIL_NEW, "New mail", NotificationManager.IMPORTANCE_HIGH).apply {
                        description = "Each new conversation in your Inbox, as it arrives"
                        lockscreenVisibility = NotificationCompat.VISIBILITY_PRIVATE
                    },
                    NotificationChannel(CH_PUSH, "Connection", NotificationManager.IMPORTANCE_MIN).apply {
                        description = "The quiet notice Android shows while instant notifications are on. Turn this off to hide it."
                        setShowBadge(false)
                    },
                )
            )
            return
        }
        nm.createNotificationChannels(
            listOf(
                NotificationChannel(CH_TASKS, "Tasks due", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "Tasks due today and overdue tasks, once a day"
                },
                NotificationChannel(CH_CARDS, "Flashcard reviews", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "A daily reminder when flashcards are due"
                },
                NotificationChannel(CH_WEB, "Watched pages", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "New posts, price changes and edits on bookmarks you watch"
                },
                NotificationChannel(CH_MAIL, "New mail", NotificationManager.IMPORTANCE_DEFAULT).apply {
                    description = "When new mail arrives in your Inbox (never shows the sender or subject)"
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
            .addAction(0, "Later", PendingIntent.getBroadcast(
                ctx, 52, Intent(ctx, ActionReceiver::class.java).setAction(ActionReceiver.ACTION_CARDS_LATER),
                PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
            ))
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

    /** Deliberately generic, like the web app: no sender or subject on the lock screen. */
    fun showMail(ctx: Context, newCount: Int) {
        if (!allowed(ctx)) return
        val n = NotificationCompat.Builder(ctx, CH_MAIL)
            .setSmallIcon(R.drawable.ic_stat_kern)
            .setColor(ACCENT)
            .setContentTitle("New mail")
            .setContentText(if (newCount == 1) "You have a new message in Kern." else "You have $newCount new messages in Kern.")
            .setAutoCancel(true)
            .setContentIntent(openIntent(ctx, "mail", 70))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(ID_MAIL, n) } catch (_: SecurityException) {}
    }

    // ---- Kern Mail --------------------------------------------------------------

    fun mailId(thread: Long) = 2_000_000 + (thread % 1_000_000_000).toInt()

    /** The silent notice for the push connection (Android requires one while it runs). */
    fun pushStatus(ctx: Context): android.app.Notification =
        NotificationCompat.Builder(ctx, CH_PUSH)
            .setSmallIcon(R.drawable.ic_stat_mail)
            .setColor(ACCENT)
            .setContentTitle("Instant notifications are on")
            .setContentText("Long-press to hide this notice")
            .setOngoing(true)
            .setSilent(true)
            .setShowWhen(false)
            .setPriority(NotificationCompat.PRIORITY_MIN)
            .setCategory(NotificationCompat.CATEGORY_SERVICE)
            .setContentIntent(openIntent(ctx, "mail", 80))
            .build()

    private fun mailAction(ctx: Context, action: String, thread: Long, code: Int): PendingIntent =
        PendingIntent.getBroadcast(
            ctx, code,
            Intent(ctx, MailActionReceiver::class.java).setAction(action).putExtra(MailActionReceiver.EXTRA_THREAD, thread),
            PendingIntent.FLAG_IMMUTABLE or PendingIntent.FLAG_UPDATE_CURRENT,
        )

    private fun sender(t: app.kern.data.MailThread): String =
        t.participants.firstOrNull { it.name.isNotBlank() }?.name ?: t.participants.firstOrNull()?.addr ?: "New mail"

    /**
     * One notification per new conversation (grouped), with Archive and Mark read. With
     * "show sender and subject" off, or on a locked screen, it only says "New mail".
     */
    fun showMailThreads(ctx: Context, threads: List<app.kern.data.MailThread>) {
        if (!allowed(ctx) || threads.isEmpty()) return
        val s = ctx.app.settings
        val details = s.mailShowDetails
        val nm = NotificationManagerCompat.from(ctx)
        val notified = s.mailNotified.toMutableSet()
        try {
            for (t in threads.take(8)) {
                val id = mailId(t.id)
                val generic = NotificationCompat.Builder(ctx, CH_MAIL_NEW)
                    .setSmallIcon(R.drawable.ic_stat_mail)
                    .setColor(ACCENT)
                    .setContentTitle("New mail")
                    .setContentText("Unlock to read")
                    .build()
                val b = NotificationCompat.Builder(ctx, CH_MAIL_NEW)
                    .setSmallIcon(R.drawable.ic_stat_mail)
                    .setColor(ACCENT)
                    .setGroup(GROUP_MAIL)
                    .setAutoCancel(true)
                    .setCategory(NotificationCompat.CATEGORY_EMAIL)
                    .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                    .setPublicVersion(generic)
                    .setOnlyAlertOnce(true)
                    .setContentIntent(openIntent(ctx, "mail/thread/${t.id}", id))
                    .addAction(0, "Archive", mailAction(ctx, MailActionReceiver.ACTION_ARCHIVE, t.id, id + 1))
                    .addAction(0, "Mark read", mailAction(ctx, MailActionReceiver.ACTION_READ, t.id, id + 2))
                if (details) {
                    val subject = t.subject.ifBlank { "(no subject)" }
                    b.setContentTitle(sender(t))
                        .setContentText(subject)
                        .setStyle(NotificationCompat.BigTextStyle().bigText(subject + if (t.snippet.isNotBlank()) "\n" + t.snippet.take(300) else ""))
                    t.lastDate?.let { d -> runCatching { java.time.OffsetDateTime.parse(d).toInstant().toEpochMilli() }.getOrNull()?.let { b.setWhen(it).setShowWhen(true) } }
                } else {
                    b.setContentTitle("New mail").setContentText("You have a new message.")
                }
                nm.notify(id, b.build())
                notified += t.id
            }
            if (notified.size > 1) {
                val summary = NotificationCompat.Builder(ctx, CH_MAIL_NEW)
                    .setSmallIcon(R.drawable.ic_stat_mail)
                    .setColor(ACCENT)
                    .setContentTitle("${notified.size} new conversations")
                    .setGroup(GROUP_MAIL)
                    .setGroupSummary(true)
                    .setAutoCancel(true)
                    .setVisibility(NotificationCompat.VISIBILITY_PRIVATE)
                    .setContentIntent(openIntent(ctx, "mail", 81))
                    .build()
                nm.notify(ID_MAIL_SUMMARY, summary)
            }
        } catch (_: SecurityException) {
        }
        s.mailNotified = notified
    }

    fun cancelMailThread(ctx: Context, thread: Long) {
        val nm = NotificationManagerCompat.from(ctx)
        nm.cancel(mailId(thread))
        val s = ctx.app.settings
        val left = s.mailNotified - thread
        s.mailNotified = left
        if (left.size <= 1) nm.cancel(ID_MAIL_SUMMARY)
    }

    /** Opened the app: the notifications have done their job. */
    fun clearMail(ctx: Context) {
        val nm = NotificationManagerCompat.from(ctx)
        val s = ctx.app.settings
        s.mailNotified.forEach { nm.cancel(mailId(it)) }
        nm.cancel(ID_MAIL_SUMMARY)
        nm.cancel(ID_MAIL)
        s.mailNotified = emptySet()
    }

    fun webId(bookmark: Long) = 10_000 + (bookmark % 1_000_000).toInt()

    fun showWebChange(ctx: Context, n: SyncWorker.Companion.WebNotice) {
        if (!allowed(ctx)) return
        val note = NotificationCompat.Builder(ctx, CH_WEB)
            .setSmallIcon(R.drawable.ic_stat_kern)
            .setColor(ACCENT)
            .setContentTitle(n.title)
            .setContentText(n.text)
            .setAutoCancel(true)
            .setContentIntent(openIntent(ctx, "bookmark/${n.id}", webId(n.id)))
            .build()
        try { NotificationManagerCompat.from(ctx).notify(webId(n.id), note) } catch (_: SecurityException) {}
    }

    fun cancel(ctx: Context, id: Int) = NotificationManagerCompat.from(ctx).cancel(id)
}
