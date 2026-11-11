package app.kern.notify

import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import app.kern.app
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.launch
import java.time.LocalDate

/** "Done" and "Tomorrow" buttons on task notifications. */
class ActionReceiver : BroadcastReceiver() {
    override fun onReceive(context: Context, intent: Intent) {
        val id = intent.getStringExtra(EXTRA_TASK) ?: return
        val nid = intent.getIntExtra(EXTRA_NOTIFICATION, 0)
        val pending = goAsync()
        val ctx = context.applicationContext
        scope.launch {
            try {
                val k = ctx.app.kern
                when (intent.action) {
                    ACTION_DONE -> k.updateTask(id, "done" to true)
                    ACTION_TOMORROW -> k.updateTask(id, "due" to LocalDate.now().plusDays(1).toString())
                }
                Notifications.cancel(ctx, nid)
                SyncWorker.refresh(ctx)
            } catch (_: Exception) {
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val ACTION_DONE = "app.kern.TASK_DONE"
        const val ACTION_TOMORROW = "app.kern.TASK_TOMORROW"
        const val EXTRA_TASK = "task"
        const val EXTRA_NOTIFICATION = "nid"
        private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    }
}
