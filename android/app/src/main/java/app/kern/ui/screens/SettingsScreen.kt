package app.kern.ui.screens

import android.content.Intent
import android.provider.Settings as AndroidSettings
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.material3.AlertDialog
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Switch
import androidx.compose.material3.SwitchDefaults
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.runtime.Composable
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
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.unit.dp
import app.kern.data.User
import app.kern.notify.Notifications
import app.kern.notify.SyncWorker
import app.kern.ui.Nav
import app.kern.ui.Session
import app.kern.ui.Workspace
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.bytes
import app.kern.ui.doc.KSheet
import app.kern.ui.doc.openUrl
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive

@Composable
fun SettingsScreen(ws: Workspace, nav: Nav) {
    val s = ws.settings
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    val theme by s.theme.collectAsState()
    val size by s.editorSize.collectAsState()
    val session by ws.session.collectAsState()
    val user = (session as? Session.SignedIn)?.user
    var tasks by remember { mutableStateOf(s.notifyTasks) }
    var cards by remember { mutableStateOf(s.notifyCards) }
    var hour by remember { mutableStateOf(s.notifyHour) }
    var password by remember { mutableStateOf(false) }
    var users by remember { mutableStateOf(false) }
    var confirmOut by remember { mutableStateOf(false) }
    var storage by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(Unit) {
        storage = runCatching { ws.kern.storage()["total"]?.jsonPrimitive?.contentOrNull?.toLongOrNull()?.let { bytes(it) } }.getOrNull()
    }

    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Settings", onBack = { nav.back() })
        LazyColumn {
            item { Heading("Appearance") }
            item {
                Bordered {
                    Column(Modifier.padding(14.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                        Text("Theme", style = MaterialTheme.typography.bodyLarge)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf("system" to "System", "dark" to "Dark", "light" to "Light").forEach { (k, l) -> Choice(l, theme == k) { s.setTheme(k) } }
                        }
                        Text("Text size in pages", style = MaterialTheme.typography.bodyLarge)
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf("small" to "Small", "normal" to "Normal", "large" to "Large").forEach { (k, l) -> Choice(l, size == k) { s.setEditorSize(k) } }
                        }
                    }
                }
            }
            item { Heading("Reminders") }
            item {
                Bordered {
                    Toggle("Tasks due today", "Each task with Done and Tomorrow buttons", tasks) { tasks = it; s.notifyTasks = it }
                    app.kern.ui.components.Divider()
                    Toggle("Flashcards due", "A daily nudge when cards are waiting", cards) { cards = it; s.notifyCards = it }
                    app.kern.ui.components.Divider()
                    Column(Modifier.padding(14.dp)) {
                        Text("Send reminders after", style = MaterialTheme.typography.bodyLarge)
                        Spacer(Modifier.height(8.dp))
                        Row(horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                            listOf(6, 8, 9, 12, 18).forEach { h -> Choice("%02d:00".format(h), hour == h) { hour = h; s.notifyHour = h } }
                        }
                    }
                    app.kern.ui.components.Divider()
                    Row(Modifier.fillMaxWidth().padding(14.dp), horizontalArrangement = Arrangement.spacedBy(8.dp)) {
                        KButton("Send a test") {
                            scope.launch {
                                runCatching { SyncWorker.refresh(ctx) }
                                val t = s.cachedTasks.filter { !it.done }
                                if (t.isNotEmpty()) Notifications.showTasks(ctx, t) else Notifications.showGeneral(ctx, "Kern reminders work", "Nothing is due today.", "tasks")
                                if (s.cachedDue + s.cachedNew > 0) Notifications.showCards(ctx, s.cachedDue, s.cachedNew)
                                if (!Notifications.allowed(ctx)) snack.show("Notifications are turned off for Kern in Android settings.")
                            }
                        }
                        KButton("System settings") {
                            ctx.startActivity(Intent(AndroidSettings.ACTION_APP_NOTIFICATION_SETTINGS).putExtra(AndroidSettings.EXTRA_APP_PACKAGE, ctx.packageName))
                        }
                    }
                }
            }
            item { Heading("Home screen widgets") }
            item {
                Bordered {
                    val mgr = android.appwidget.AppWidgetManager.getInstance(ctx)
                    listOf(
                        Triple("Today's tasks", "Tick tasks off from the home screen", app.kern.widget.TasksWidgetReceiver::class.java),
                        Triple("Flashcards due", "Cards waiting, one tap to study", app.kern.widget.CardsWidgetReceiver::class.java),
                        Triple("Quick capture", "Search, new page, task or bookmark", app.kern.widget.CaptureWidgetReceiver::class.java),
                        Triple("Pages", "Favorites and recent pages", app.kern.widget.RecentWidgetReceiver::class.java),
                    ).forEachIndexed { i, (title, sub, cls) ->
                        if (i > 0) app.kern.ui.components.Divider()
                        Row(Modifier.fillMaxWidth().padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
                            Column(Modifier.weight(1f)) {
                                Text(title, style = MaterialTheme.typography.bodyLarge)
                                Text(sub, style = MaterialTheme.typography.bodySmall, color = kern.text3)
                            }
                            TextButton(onClick = {
                                scope.launch { runCatching { SyncWorker.refresh(ctx) } }
                                val ok = mgr.isRequestPinAppWidgetSupported &&
                                    mgr.requestPinAppWidget(android.content.ComponentName(ctx, cls), null, null)
                                if (!ok) snack.show("Long-press your home screen and choose Widgets → Kern.")
                            }) { Text("Add", color = kern.accent) }
                        }
                    }
                }
            }
            item { Heading("Account") }
            item {
                Bordered {
                    Column(Modifier.padding(14.dp)) {
                        Text(user?.username ?: "", style = MaterialTheme.typography.titleMedium)
                        Text(listOfNotNull(user?.email?.ifBlank { null }, if (user?.isAdmin == true) "Administrator" else null, storage?.let { "$it used" }).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        Spacer(Modifier.height(4.dp))
                        Text(s.serverUrl, style = MaterialTheme.typography.bodySmall, color = kern.text3)
                    }
                    app.kern.ui.components.Divider()
                    Item("Change password") { password = true }
                    if (user?.isAdmin == true) { app.kern.ui.components.Divider(); Item("Users") { users = true } }
                    app.kern.ui.components.Divider()
                    Item("Open web app") { openUrl(ctx, s.serverUrl) }
                    app.kern.ui.components.Divider()
                    Item("Server, AI, backups and import (web)") { openUrl(ctx, s.serverUrl + "/settings") }
                    app.kern.ui.components.Divider()
                    Item("Sign out", danger = true) { confirmOut = true }
                }
            }
            item {
                Text("Kern for Android 1.0", style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(20.dp))
            }
        }
    }

    if (confirmOut) AlertDialog(
        onDismissRequest = { confirmOut = false }, containerColor = kern.surface,
        title = { Text("Sign out?") },
        text = { Text("Widgets and reminders stop until you sign in again.") },
        confirmButton = { TextButton(onClick = { confirmOut = false; ws.logout() }) { Text("Sign out", color = kern.danger) } },
        dismissButton = { TextButton(onClick = { confirmOut = false }) { Text("Cancel", color = kern.text2) } },
    )
    if (password) PasswordSheet(ws) { password = false }
    if (users) UsersSheet(ws, user) { users = false }
}

@Composable
private fun Toggle(title: String, sub: String, on: Boolean, onChange: (Boolean) -> Unit) {
    Row(Modifier.fillMaxWidth().clickable { onChange(!on) }.padding(14.dp), verticalAlignment = Alignment.CenterVertically) {
        Column(Modifier.weight(1f)) {
            Text(title, style = MaterialTheme.typography.bodyLarge)
            Text(sub, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
        Switch(on, onChange, colors = SwitchDefaults.colors(checkedTrackColor = kern.accent, checkedThumbColor = kern.onAccent))
    }
}

@Composable
private fun Item(title: String, danger: Boolean = false, onClick: () -> Unit) {
    Text(title, style = MaterialTheme.typography.bodyLarge, color = if (danger) kern.danger else kern.text, modifier = Modifier.fillMaxWidth().clickable(onClick = onClick).padding(14.dp))
}

@Composable
private fun PasswordSheet(ws: Workspace, onDone: () -> Unit) {
    var cur by remember { mutableStateOf("") }
    var new by remember { mutableStateOf("") }
    var err by remember { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    KSheet(onDone, "Change password") {
        Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
            KField(cur, { cur = it }, "Current password", visual = PasswordVisualTransformation(), keyboard = KeyboardOptions(keyboardType = KeyboardType.Password))
            KField(new, { new = it }, "New password (10+ characters)", visual = PasswordVisualTransformation(), keyboard = KeyboardOptions(keyboardType = KeyboardType.Password))
            Text("Other devices will be signed out.", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            err?.let { Text(it, color = kern.danger) }
            KButton("Change password", Modifier.fillMaxWidth(), primary = true, enabled = cur.isNotEmpty() && new.length >= 10) {
                scope.launch { runCatching { ws.kern.changePassword(cur, new) }.onSuccess { snack.show("Password changed"); onDone() }.onFailure { err = it.message } }
            }
        }
    }
}

@Composable
private fun UsersSheet(ws: Workspace, me: User?, onDone: () -> Unit) {
    var list by remember { mutableStateOf<List<User>?>(null) }
    var name by remember { mutableStateOf("") }
    var pw by remember { mutableStateOf("") }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    suspend fun load() { list = runCatching { ws.kern.adminUsers() }.getOrDefault(emptyList()) }
    LaunchedEffect(Unit) { load() }
    KSheet(onDone, "Users") {
        LazyColumn(Modifier.fillMaxWidth().height(460.dp)) {
            items(list?.size ?: 0) { i ->
                val u = list!![i]
                Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 8.dp), verticalAlignment = Alignment.CenterVertically) {
                    Column(Modifier.weight(1f)) {
                        Text(u.username + if (u.id == me?.id) " (you)" else "", style = MaterialTheme.typography.bodyLarge)
                        Text(listOfNotNull(if (u.isAdmin) "Admin" else null, if (!u.isActive) "Waiting / disabled" else null, u.storageBytes?.let { bytes(it) }).joinToString(" · "), style = MaterialTheme.typography.bodySmall, color = kern.text3)
                    }
                    if (u.id != me?.id) TextButton(onClick = {
                        scope.launch { runCatching { ws.kern.adminUpdate(u.id, app.kern.data.jsonOf("is_active" to !u.isActive)) }.onSuccess { load() }.onFailure { snack.error(it) } }
                    }) { Text(if (u.isActive) "Disable" else "Approve", color = if (u.isActive) kern.danger else kern.accent) }
                }
            }
            item {
                Column(Modifier.padding(16.dp), verticalArrangement = Arrangement.spacedBy(8.dp)) {
                    Text("ADD A USER", style = MaterialTheme.typography.labelSmall, color = kern.text3)
                    KField(name, { name = it }, "Username")
                    KField(pw, { pw = it }, "Password", visual = PasswordVisualTransformation())
                    KButton("Add user", Modifier.fillMaxWidth(), enabled = name.length >= 3 && pw.length >= 10) {
                        scope.launch { runCatching { ws.kern.adminCreate(name.trim(), pw, false) }.onSuccess { name = ""; pw = ""; load(); snack.show("User added") }.onFailure { snack.error(it) } }
                    }
                }
            }
        }
    }
}
