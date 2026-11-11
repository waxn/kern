package app.kern.notify

import android.content.Context
import androidx.work.Constraints
import androidx.work.CoroutineWorker
import androidx.work.ExistingPeriodicWorkPolicy
import androidx.work.ExistingWorkPolicy
import androidx.work.NetworkType
import androidx.work.OneTimeWorkRequestBuilder
import androidx.work.PeriodicWorkRequestBuilder
import androidx.work.WorkManager
import androidx.work.WorkerParameters
import androidx.work.workDataOf
import app.kern.app
import app.kern.data.ApiError
import app.kern.widget.Widgets
import java.time.LocalDate
import java.time.LocalTime
import java.util.concurrent.TimeUnit

/**
 * Runs about every 15 minutes: refreshes what the widgets show and reminds about tasks due today
 * (once a day after the chosen hour) and flashcards that are due (again after a cooldown, until
 * the quiet hour).
 */
class SyncWorker(ctx: Context, params: WorkerParameters) : CoroutineWorker(ctx, params) {
    override suspend fun doWork(): Result {
        val a = applicationContext.app
        if (a.settings.user == null) return Result.success()
        val notify = inputData.getBoolean(KEY_NOTIFY, true)
        try {
            refresh(applicationContext)
            if (notify) remind(applicationContext)
        } catch (e: ApiError) {
            return if (e.status == 0) Result.retry() else Result.success()
        }
        return Result.success()
    }

    companion object {
        private const val KEY_NOTIFY = "notify"

        fun schedule(ctx: Context) {
            val req = PeriodicWorkRequestBuilder<SyncWorker>(15, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("kern-sync", ExistingPeriodicWorkPolicy.UPDATE, req)
        }

        fun cancel(ctx: Context) = WorkManager.getInstance(ctx).cancelAllWork()

        /** Refresh widgets soon after something changed in the app (no reminders). */
        fun refreshSoon(ctx: Context) {
            val req = OneTimeWorkRequestBuilder<SyncWorker>()
                .setInputData(workDataOf(KEY_NOTIFY to false))
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniqueWork("kern-refresh", ExistingWorkPolicy.REPLACE, req)
        }

        suspend fun refresh(ctx: Context) {
            val a = ctx.app
            val k = a.kern
            val tasks = k.tasks("today")
            a.settings.cachedTasks = tasks
            runCatching { k.queue() }.getOrNull()?.let {
                a.settings.cachedDue = it.counts.review + it.counts.learning
                a.settings.cachedNew = it.counts.new
            }
            runCatching { k.tree() }.getOrNull()?.let { docs ->
                val live = docs.filter { !it.isArchived && it.entryOf == null && !it.empty }
                val fav = live.filter { it.isFavorite }
                val recent = live.filter { !it.isFavorite && it.lastOpenedAt != null }.sortedByDescending { it.lastOpenedAt }
                a.settings.cachedDocs = (fav + recent).take(12)
            }
            a.settings.cachedAt = System.currentTimeMillis()
            Widgets.updateAll(ctx)
        }

        /**
         * Whether to nudge about due flashcards now: once a day when [everyMin] is 0, otherwise
         * whenever [everyMin] minutes have passed since the last reminder or study session.
         */
        fun cardsReminderDue(now: Long, lastNudge: Long, everyMin: Int, sentToday: Boolean): Boolean =
            if (everyMin <= 0) !sentToday else now - lastNudge >= everyMin * 60_000L

        fun remind(ctx: Context) {
            val s = ctx.app.settings
            val today = LocalDate.now()
            val day = today.toString()
            val hour = LocalTime.now().hour
            if (hour < s.notifyHour || hour >= s.quietHour) return
            if (today.dayOfWeek.value !in s.reminderDays) return
            if (s.notifyTasks && !s.sentToday("tasks", day)) {
                val due = s.cachedTasks.filter { t ->
                    !t.done && t.priority >= s.tasksMinPriority && (s.tasksIncludeOverdue || (t.due ?: day) >= day)
                }
                if (due.isNotEmpty()) Notifications.showTasks(ctx, due)
                s.markSent("tasks", day)
            }
            val waiting = s.cachedDue + if (s.cardsIncludeNew) s.cachedNew else 0
            if (s.notifyCards && waiting >= s.cardsMin) {
                if (cardsReminderDue(System.currentTimeMillis(), s.cardsLastNudge, s.cardsEveryMin, s.sentToday("cards", day))) {
                    Notifications.showCards(ctx, s.cachedDue, if (s.cardsIncludeNew) s.cachedNew else 0)
                    s.markSent("cards", day)
                    s.cardsLastNudge = System.currentTimeMillis()
                }
            } else if (waiting == 0) {
                Notifications.cancel(ctx, Notifications.ID_CARDS) // nothing left to study
            }
        }
    }
}
