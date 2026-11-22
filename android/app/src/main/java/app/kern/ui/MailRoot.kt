package app.kern.ui

import android.Manifest
import android.content.Context
import android.content.Intent
import android.net.Uri
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.verticalScroll
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Scaffold
import androidx.compose.material3.Snackbar
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.unit.dp
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.kern.BuildConfig
import app.kern.Launch
import app.kern.MainActivity
import app.kern.app
import app.kern.notify.MailPushService
import app.kern.notify.Notifications
import app.kern.ui.components.KButton
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Snack
import app.kern.ui.screens.ChatScreen
import app.kern.ui.screens.LoginScreen
import app.kern.ui.screens.MailComposeScreen
import app.kern.ui.screens.MailScreen
import app.kern.ui.screens.MailThreadScreen
import app.kern.ui.theme.kern
import kotlinx.coroutines.flow.MutableStateFlow

/** Routes Kern Mail has itself; everything else (pages, tasks, tags…) opens in Kern. */
private fun mailRoute(r: String) = r == "mail" || r.startsWith("mail?") || r.startsWith("mail/") || r.startsWith("chat/") || r == "mail-settings"

/** Map an in-app route to the web app's address, for when Kern isn't installed. */
private fun webPath(route: String): String = when {
    route.startsWith("doc/") -> "/doc/" + route.removePrefix("doc/")
    route.startsWith("tasks") -> "/tasks" + route.removePrefix("tasks").replaceFirst("?task=", "?view=all&task=")
    route.startsWith("tag/") -> "/tag/" + route.removePrefix("tag/")
    route.startsWith("bookmark/") -> "/web"
    route == "cards" || route.startsWith("review") -> "/cards"
    else -> "/"
}

/** Opens [route] in the Kern app (same server and sign-in there), or in the browser. */
fun openInKern(ctx: Context, route: String) {
    val kernApp = ctx.packageManager.getLaunchIntentForPackage(BuildConfig.OTHER_APP)
    if (kernApp != null) {
        kernApp.putExtra(MainActivity.EXTRA_ROUTE, route).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK)
        runCatching { ctx.startActivity(kernApp) }
        return
    }
    val base = ctx.app.api.base
    if (base.isNotBlank()) runCatching {
        ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(base + webPath(route))).addFlags(Intent.FLAG_ACTIVITY_NEW_TASK))
    }
}

@Composable
fun MailRoot(ws: Workspace, launch: MutableStateFlow<Launch?>) {
    val session by ws.session.collectAsState()
    val host = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val snack = remember { Snack(host, scope) }
    CompositionLocalProvider(LocalSnack provides snack) {
        when (session) {
            is Session.SignedIn -> MailSignedIn(ws, launch, host)
            else -> Scaffold(snackbarHost = { SnackbarHost(host) { Snackbar(it, containerColor = kern.surface2, contentColor = kern.text) } }) { pad ->
                Box(Modifier.padding(pad)) { LoginScreen(ws) }
            }
        }
    }
}

@Composable
private fun MailSignedIn(ws: Workspace, launch: MutableStateFlow<Launch?>, host: SnackbarHostState) {
    val ctx = LocalContext.current
    val nav = rememberNavController()
    val n = remember(nav) { Nav(nav) { r -> if (mailRoute(r)) false else { openInKern(ctx, r); true } } }
    val pending by launch.collectAsState()

    // Notifications need permission on Android 13+; instant push starts once it's granted.
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) { MailPushService.sync(ctx) }
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 && !Notifications.allowed(ctx)) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
        else MailPushService.sync(ctx)
    }

    LaunchedEffect(pending) {
        val l = pending ?: return@LaunchedEffect
        launch.value = null
        if (l is Launch.Route) {
            val r = l.route
            when {
                r == "mail" -> n.tab("mail")
                mailRoute(r) -> n.go(r)
            }
        }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        snackbarHost = { SnackbarHost(host) { Snackbar(it, containerColor = kern.surface2, contentColor = kern.text, actionColor = kern.accent) } },
    ) { pad ->
        NavHost(
            nav, startDestination = "mail?view={view}",
            modifier = Modifier.fillMaxSize().padding(bottom = pad.calculateBottomPadding()),
            enterTransition = { fadeIn() + slideInHorizontally { it / 12 } },
            exitTransition = { fadeOut() },
            popEnterTransition = { fadeIn() },
            popExitTransition = { fadeOut() + slideOutHorizontally { it / 12 } },
        ) {
            composable("mail?view={view}", arguments = listOf(
                navArgument("view") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { MailScreen(ws, n, it.arguments?.getString("view"), standalone = true) }
            composable("mail") { MailScreen(ws, n, null, standalone = true) }
            composable("mail/thread/{id}") { MailThreadScreen(ws, n, it.arguments!!.getString("id")!!.toLong()) }
            composable("mail/compose?msg={msg}&mode={mode}", arguments = listOf(
                navArgument("msg") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("mode") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { MailComposeScreen(ws, n, it.arguments?.getString("msg")?.toLongOrNull(), it.arguments?.getString("mode")) }
            composable("chat/{id}?page={page}&mail={mail}", arguments = listOf(
                navArgument("page") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("mail") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { ChatScreen(ws, n, it.arguments!!.getString("id")!!, it.arguments?.getString("page"), it.arguments?.getString("mail")?.toLongOrNull()) }
            composable("mail-settings") { MailSettingsScreen(ws, n) }
        }
    }
}

/** Kern Mail's own settings: notifications, looks, the account. Mail rules live in Kern's web settings. */
@Composable
fun MailSettingsScreen(ws: Workspace, nav: Nav) {
    val ctx = LocalContext.current
    val s = ctx.app.settings
    var push by remember { mutableStateOf(s.mailPush) }
    var details by remember { mutableStateOf(s.mailShowDetails) }
    var dark by remember { mutableStateOf(s.mailDarkEmails) }
    val theme by s.theme.collectAsState()
    val user by ws.session.collectAsState()
    val k = kern

    @Composable
    fun row(title: String, sub: String, on: Boolean, set: (Boolean) -> Unit) {
        Row(Modifier.fillMaxWidth().clickable { set(!on) }.padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
            Column(Modifier.weight(1f)) {
                Text(title, style = MaterialTheme.typography.bodyLarge)
                Text(sub, style = MaterialTheme.typography.bodySmall, color = k.text3)
            }
            Switch(on, set, colors = SwitchDefaults.colors(checkedTrackColor = k.accent, checkedThumbColor = k.onAccent))
        }
    }

    Column(Modifier.fillMaxSize().background(k.bg).statusBarsPadding().navigationBarsPadding()) {
        KTopBar("Settings", onBack = { nav.back() })
        Column(Modifier.verticalScroll(rememberScrollState())) {
            Text("NOTIFICATIONS", style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.padding(start = 20.dp, top = 12.dp, bottom = 4.dp))
            row("Instant notifications", "New mail shows up within seconds. Keeps one connection to your Kern server open; Android shows a quiet notice for it, which you can hide.", push) {
                push = it; s.mailPush = it; MailPushService.sync(ctx)
            }
            row("Show sender and subject", "On the lock screen notifications only ever say “New mail”.", details) { details = it; s.mailShowDetails = it }
            Text("READING", style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.padding(start = 20.dp, top = 20.dp, bottom = 4.dp))
            row("Dark emails", "In the dark theme, show emails as light text on dark. Each email can switch back to its original colors.", dark) { dark = it; s.mailDarkEmails = it }
            Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 14.dp), verticalAlignment = Alignment.CenterVertically) {
                Column(Modifier.weight(1f)) {
                    Text("Theme", style = MaterialTheme.typography.bodyLarge)
                    Text(when (theme) { "dark" -> "Dark"; "light" -> "Light"; else -> "System" }, style = MaterialTheme.typography.bodySmall, color = k.text3)
                }
                Row(horizontalArrangement = Arrangement.spacedBy(6.dp)) {
                    listOf("system" to "Auto", "light" to "Light", "dark" to "Dark").forEach { (v, label) ->
                        app.kern.ui.components.Pill(label, if (theme == v) k.accent else k.text2, onClick = { s.setTheme(v) })
                    }
                }
            }
            Text("ACCOUNT", style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.padding(start = 20.dp, top = 20.dp, bottom = 4.dp))
            Column(Modifier.padding(horizontal = 20.dp, vertical = 8.dp)) {
                Text((user as? Session.SignedIn)?.user?.username ?: "", style = MaterialTheme.typography.bodyLarge)
                Text(ws.kern.api.base, style = MaterialTheme.typography.bodySmall, color = k.text3)
                Spacer(Modifier.height(4.dp))
                Text("Folders, filters, signatures, templates and blocked senders are in Kern's web settings (Settings → Mail).",
                    style = MaterialTheme.typography.bodySmall, color = k.text3)
                Spacer(Modifier.height(12.dp))
                Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                    KButton("Open Kern") { openInKern(ctx, "home") }
                    KButton("Sign out") { ws.logout() }
                }
            }
            Spacer(Modifier.height(40.dp))
        }
    }
}
