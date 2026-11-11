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
 * Runs about every 30 minutes: refreshes what the widgets show and, once a day after the
 * chosen hour, reminds about tasks due today and flashcards that are due.
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
            val req = PeriodicWorkRequestBuilder<SyncWorker>(30, TimeUnit.MINUTES)
                .setConstraints(Constraints.Builder().setRequiredNetworkType(NetworkType.CONNECTED).build())
                .build()
            WorkManager.getInstance(ctx).enqueueUniquePeriodicWork("kern-sync", ExistingPeriodicWorkPolicy.KEEP, req)
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

        fun remind(ctx: Context) {
            val s = ctx.app.settings
            val day = LocalDate.now().toString()
            if (LocalTime.now().hour < s.notifyHour) return
            if (s.notifyTasks && !s.sentToday("tasks", day)) {
                val due = s.cachedTasks.filter { !it.done }
                if (due.isNotEmpty()) Notifications.showTasks(ctx, due)
                s.markSent("tasks", day)
            }
            if (s.notifyCards && !s.sentToday("cards", day)) {
                if (s.cachedDue + s.cachedNew > 0) {
                    Notifications.showCards(ctx, s.cachedDue, s.cachedNew)
                    s.markSent("cards", day)
                }
            }
        }
    }
}
