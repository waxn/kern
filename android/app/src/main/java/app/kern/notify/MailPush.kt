package app.kern.notify

import android.app.Service
import android.content.BroadcastReceiver
import android.content.Context
import android.content.Intent
import android.content.pm.ServiceInfo
import android.net.ConnectivityManager
import android.net.Network
import android.os.Build
import android.os.IBinder
import androidx.core.content.ContextCompat
import app.kern.BuildConfig
import app.kern.app
import app.kern.data.ApiError
import app.kern.data.KernJson
import kotlinx.serialization.encodeToString
import app.kern.data.MailChanges
import app.kern.data.MailThread
import kotlinx.coroutines.CancellationException
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.Dispatchers
import kotlinx.coroutines.Job
import kotlinx.coroutines.SupervisorJob
import kotlinx.coroutines.cancel
import kotlinx.coroutines.channels.Channel
import kotlinx.coroutines.delay
import kotlinx.coroutines.isActive
import kotlinx.coroutines.launch
import kotlinx.coroutines.suspendCancellableCoroutine
import kotlinx.coroutines.withTimeoutOrNull
import okhttp3.Call
import okhttp3.Callback
import okhttp3.Request
import okhttp3.Response
import java.io.IOException
import java.util.concurrent.TimeUnit
import kotlin.coroutines.resume
import kotlin.coroutines.resumeWithException

/**
 * Kern Mail's instant notifications, without Google's push service: one long-poll request to
 * your own Kern server (`/api/mail/changes?wait=…`), which answers the moment the sync worker
 * stores new mail (it watches the mailbox with IMAP IDLE). Runs as a foreground service with a
 * silent, minimised notification, the way self-hosted mail apps do push.
 *
 * Battery: the server holds each request until something happens, starting at 50 s and growing
 * to a few minutes when nothing between the phone and the server cuts long requests short.
 * Every failure backs off (up to 5 minutes) and a returning network wakes it at once.
 */
class MailPushService : Service() {
    private val scope = CoroutineScope(SupervisorJob() + Dispatchers.IO)
    private var job: Job? = null
    private val kick = Channel<Unit>(Channel.CONFLATED)
    private var netCallback: ConnectivityManager.NetworkCallback? = null

    override fun onBind(intent: Intent?): IBinder? = null

    override fun onCreate() {
        super.onCreate()
        val n = Notifications.pushStatus(this)
        if (Build.VERSION.SDK_INT >= 34) {
            startForeground(Notifications.ID_PUSH, n, ServiceInfo.FOREGROUND_SERVICE_TYPE_SPECIAL_USE)
        } else {
            startForeground(Notifications.ID_PUSH, n)
        }
        val cm = getSystemService(ConnectivityManager::class.java)
        netCallback = object : ConnectivityManager.NetworkCallback() {
            override fun onAvailable(network: Network) { kick.trySend(Unit) }
        }.also { runCatching { cm.registerDefaultNetworkCallback(it) } }
    }

    override fun onStartCommand(intent: Intent?, flags: Int, startId: Int): Int {
        val a = app
        if (!BuildConfig.MAIL_APP || a.settings.user == null || !a.settings.mailPush) {
            stopSelf()
            return START_NOT_STICKY
        }
        if (job?.isActive != true) job = scope.launch { loop() }
        return START_STICKY
    }

    override fun onDestroy() {
        netCallback?.let { runCatching { getSystemService(ConnectivityManager::class.java).unregisterNetworkCallback(it) } }
        scope.cancel()
        super.onDestroy()
    }

    private suspend fun loop() {
        val s = app.settings
        var backoff = 5_000L
        while (scope.isActive) {
            val wait = s.mailWait.coerceIn(MIN_WAIT, MAX_WAIT)
            val started = System.currentTimeMillis()
            try {
                val since = s.mailSince
                val r = changes(since, if (since == null) null else wait)
                backoff = 5_000L
                if (since == null || r.reset) {
                    s.mailSince = r.last // first run: only note where the feed is
                    continue
                }
                handle(r)
                s.mailSince = r.last
                // A held request that ran its full time: the path allows long requests, so hold longer.
                if (r.events.isEmpty() && System.currentTimeMillis() - started >= wait * 1000L - 2_000) {
                    s.mailWait = (wait * 2).coerceAtMost(MAX_WAIT)
                }
                if (r.more) continue
            } catch (e: CancellationException) {
                throw e
            } catch (e: ApiError) {
                if (e.status == 401 || e.status == 403) {
                    stopSelf() // signed out, or this session can't read mail: nothing to wait for
                    return
                }
                fail(wait, started)
                pause(backoff)
                backoff = (backoff * 2).coerceAtMost(300_000L)
            } catch (e: IOException) {
                fail(wait, started)
                pause(backoff)
                backoff = (backoff * 2).coerceAtMost(300_000L)
            }
        }
    }

    /** A request cut off early (a proxy's timeout, a NAT dropping idle connections): ask for shorter holds. */
    private fun fail(wait: Int, started: Long) {
        val ran = (System.currentTimeMillis() - started) / 1000
        if (ran in 15 until wait) app.settings.mailWait = (wait / 2).coerceAtLeast(MIN_WAIT)
    }

    private suspend fun pause(ms: Long) {
        withTimeoutOrNull(ms) { kick.receive() } // a returning network ends the wait early
    }

    private suspend fun handle(r: MailChanges) {
        val ctx = this
        val k = app.kern
        // The web app's other notifications, in its words.
        for (e in r.events) when (e.kind) {
            "package" -> Notifications.PACKAGE_NEWS[e.status]?.let { text ->
                Notifications.showMailNews(ctx, e.kind, e.id, "Package update", text, e.thread?.let { "mail/thread/$it" } ?: "mail/packages")
            }
            "snooze_wake" -> e.thread?.let { t ->
                Notifications.showMailNews(ctx, e.kind, t, "Snoozed mail is back", "A conversation you snoozed is back in your Inbox.", "mail/thread/$t")
            }
            "nudge" -> e.thread?.let { t ->
                Notifications.showMailNews(ctx, e.kind, t, "No reply yet", "A conversation you were waiting on has had no reply.", "mail/thread/$t")
            }
        }
        val fresh = r.events.filter { it.kind == "message" && it.new }.mapNotNull { it.thread }.distinct()
        val touched = r.events.flatMap { it.threads + listOfNotNull(it.thread) }.toSet()
        val notified = app.settings.mailNotified
        val generic = touched.isNotEmpty() && Notifications.genericMailShown(ctx)
        if (fresh.isEmpty() && notified.none { it in touched } && !generic) return
        // One request for the Inbox's newest conversations covers both: what to show, and what was read elsewhere.
        val inbox = runCatching { k.mailThreads("inbox").threads }.getOrNull() ?: return
        val byId = inbox.associateBy { it.id }
        val show = fresh.mapNotNull { byId[it] }.filter { it.unread > 0 && !it.muted }
        if (show.isNotEmpty()) Notifications.showMailThreads(ctx, show)
        // Read, archived or deleted somewhere else: take its notification away.
        val gone = notified.filter { id -> id in touched && (byId[id]?.unread ?: 0) == 0 }
        gone.forEach { Notifications.cancelMailThread(ctx, it) }
        // Everything read elsewhere: the plain "New mail" from the periodic check goes too.
        if (generic && inbox.none { it.unread > 0 }) Notifications.cancel(ctx, Notifications.ID_MAIL)
        cacheInbox(inbox)
    }

    private fun cacheInbox(list: List<MailThread>) {
        runCatching { app.settings.mailInboxCache = KernJson.encodeToString(list) }
    }

    /** GET /api/mail/changes, cancellable (stopping the service aborts the held request). */
    private suspend fun changes(since: Long?, wait: Int?): MailChanges {
        val api = app.api
        if (api.base.isBlank()) throw ApiError(401, "No server")
        val q = buildString {
            if (since != null) append("?since=").append(since)
            if (wait != null) append("&wait=").append(wait)
        }
        val req = Request.Builder().url(api.base + "/api/mail/changes" + q).header("X-Kern", "1").header("Accept", "application/json").build()
        val client = api.http.newBuilder().readTimeout((wait ?: 0) + 30L, TimeUnit.SECONDS).build()
        val call = client.newCall(req)
        val text = suspendCancellableCoroutine { cont ->
            cont.invokeOnCancellation { call.cancel() }
            call.enqueue(object : Callback {
                override fun onFailure(call: Call, e: IOException) { if (cont.isActive) cont.resumeWithException(e) }
                override fun onResponse(call: Call, response: Response) {
                    response.use {
                        val body = it.body?.string().orEmpty()
                        if (!it.isSuccessful) cont.resumeWithException(ApiError(it.code, "HTTP ${it.code}"))
                        else cont.resume(body)
                    }
                }
            })
        }
        return KernJson.decodeFromString<MailChanges>(text)
    }

    companion object {
        const val MIN_WAIT = 50
        const val MAX_WAIT = 280

        /** Start (or keep) instant notifications when they're wanted; stop them otherwise. */
        fun sync(ctx: Context) {
            val s = ctx.app.settings
            val want = BuildConfig.MAIL_APP && s.user != null && s.mailPush && Notifications.allowed(ctx)
            val i = Intent(ctx, MailPushService::class.java)
            if (want) runCatching { ContextCompat.startForegroundService(ctx, i) }
            else ctx.stopService(i)
        }
    }
}

/** Starts instant notifications again after a reboot or an app update. */
class MailBootReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        if (intent.action == Intent.ACTION_BOOT_COMPLETED || intent.action == Intent.ACTION_MY_PACKAGE_REPLACED) {
            MailPushService.sync(ctx)
            SyncWorker.schedule(ctx)
        }
    }
}

/** "Archive" and "Mark read" on a new-mail notification. */
class MailActionReceiver : BroadcastReceiver() {
    override fun onReceive(ctx: Context, intent: Intent) {
        val thread = intent.getLongExtra(EXTRA_THREAD, -1L).takeIf { it > 0 } ?: return
        val action = when (intent.action) {
            ACTION_ARCHIVE -> "archive"
            ACTION_READ -> "read"
            else -> return
        }
        Notifications.cancelMailThread(ctx, thread)
        val pending = goAsync()
        CoroutineScope(Dispatchers.IO).launch {
            try {
                val k = ctx.app.kern
                val ctxFolder = if (action == "archive") runCatching { k.mailFolders().folders.firstOrNull { it.role == "inbox" }?.id }.getOrNull() else null
                k.mailAction(listOf(thread), action, *(if (ctxFolder != null) arrayOf("context" to ctxFolder) else emptyArray()))
            } catch (_: Exception) {
                // Offline or signed out: the conversation stays as it was; the app shows it next time.
            } finally {
                pending.finish()
            }
        }
    }

    companion object {
        const val ACTION_ARCHIVE = "app.kern.mail.ARCHIVE"
        const val ACTION_READ = "app.kern.mail.READ"
        const val EXTRA_THREAD = "thread"
    }
}
