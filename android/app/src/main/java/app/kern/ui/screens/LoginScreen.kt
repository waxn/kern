package app.kern.ui.screens

import android.content.Intent
import android.net.Uri
import androidx.compose.animation.AnimatedContent
import androidx.compose.foundation.background
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.imePadding
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.safeDrawingPadding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.text.KeyboardActions
import androidx.compose.foundation.text.KeyboardOptions
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Dns
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
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
import androidx.compose.ui.text.input.ImeAction
import androidx.compose.ui.text.input.KeyboardType
import androidx.compose.ui.text.input.PasswordVisualTransformation
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.unit.dp
import app.kern.data.SiteInfo
import app.kern.ui.Workspace
import app.kern.ui.components.Card
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.KernLogo
import app.kern.ui.components.TextAction
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch

@Composable
fun LoginScreen(ws: Workspace) {
    val ctx = LocalContext.current
    val scope = rememberCoroutineScope()
    var server by remember { mutableStateOf(ws.settings.serverUrl) }
    var site by remember { mutableStateOf<SiteInfo?>(null) }
    var mode by remember { mutableStateOf("signin") }
    var username by remember { mutableStateOf("") }
    var email by remember { mutableStateOf("") }
    var password by remember { mutableStateOf("") }
    var busy by remember { mutableStateOf(false) }
    var error by remember { mutableStateOf<String?>(null) }
    var info by remember { mutableStateOf<String?>(null) }

    fun connect() = scope.launch {
        var url = server.trim().trimEnd('/')
        if (url.isEmpty()) { error = "Enter the address you open Kern at in a browser."; return@launch }
        if (!url.startsWith("http://") && !url.startsWith("https://")) url = "http://$url"
        server = url
        busy = true; error = null
        ws.settings.serverUrl = url
        try {
            val s = ws.kern.site()
            if (s.user != null) { ws.signedIn(s.user); return@launch }
            site = s
        } catch (e: Exception) {
            error = (e.message ?: "Cannot reach the server.") + " Check the address and that this phone can reach it."
        } finally { busy = false }
    }

    fun submit() = scope.launch {
        busy = true; error = null; info = null
        try {
            val s = if (mode == "signin") ws.kern.login(username.trim(), password) else ws.kern.signup(username.trim(), email.trim(), password)
            when {
                s.user != null -> ws.signedIn(s.user)
                s.pending -> { info = "Account created. An administrator needs to approve it before you can sign in."; mode = "signin" }
            }
        } catch (e: Exception) {
            val d = (e as? app.kern.data.ApiError)?.data
            if (d.toString().contains("\"pending\"")) info = "Account created. An administrator needs to approve it before you can sign in."
            else error = e.message
        } finally { busy = false }
    }

    Column(
        Modifier.fillMaxSize().background(kern.bg).safeDrawingPadding().imePadding().verticalScroll(rememberScrollState()).padding(24.dp),
        horizontalAlignment = Alignment.CenterHorizontally,
    ) {
        Spacer(Modifier.height(48.dp))
        KernLogo(56.dp)
        Spacer(Modifier.height(16.dp))
        Text(site?.siteName ?: "Kern", style = MaterialTheme.typography.headlineMedium, color = kern.text)
        Spacer(Modifier.height(4.dp))
        Text(
            if (site == null) "Your knowledge base, in your pocket." else if (mode == "signin") "Sign in to continue" else "Create your account",
            style = MaterialTheme.typography.bodyMedium, color = kern.text2, textAlign = TextAlign.Center,
        )
        Spacer(Modifier.height(32.dp))

        Column(Modifier.widthIn(max = 420.dp).fillMaxWidth(), verticalArrangement = Arrangement.spacedBy(12.dp)) {
            AnimatedContent(site, label = "step") { s ->
                Column(verticalArrangement = Arrangement.spacedBy(12.dp)) {
                    if (s == null) {
                        KField(
                            server, { server = it }, "Server address", placeholder = "http://192.168.1.20:8420",
                            keyboard = KeyboardOptions(keyboardType = KeyboardType.Uri, imeAction = ImeAction.Go),
                            actions = KeyboardActions(onGo = { connect() }),
                        )
                        Text("The address you open Kern at in a browser.", style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        KButton(if (busy) "Connecting…" else "Continue", Modifier.fillMaxWidth(), primary = true, enabled = !busy) { connect() }
                    } else if (s.needsSetup) {
                        Card {
                            Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
                                Text("This server is not set up yet", style = MaterialTheme.typography.titleMedium)
                                Text("Open it in a browser to create the administrator account with the setup code from the server log, then come back here.", style = MaterialTheme.typography.bodyMedium, color = kern.text2)
                                KButton("Open in browser", Modifier.fillMaxWidth(), primary = true) {
                                    ctx.startActivity(Intent(Intent.ACTION_VIEW, Uri.parse(ws.settings.serverUrl)))
                                }
                                KButton("I've finished setup", Modifier.fillMaxWidth()) { connect() }
                            }
                        }
                    } else {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.Dns, null, tint = kern.text3, modifier = Modifier.size(16.dp))
                            Spacer(Modifier.width(6.dp))
                            Text(ws.settings.serverUrl.removePrefix("http://").removePrefix("https://"), style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.weight(1f))
                            TextAction("Change") { site = null; error = null }
                        }
                        KField(username, { username = it }, "Username", keyboard = KeyboardOptions(imeAction = ImeAction.Next, autoCorrectEnabled = false))
                        if (mode == "signup") KField(email, { email = it }, "Email (optional)", keyboard = KeyboardOptions(keyboardType = KeyboardType.Email, imeAction = ImeAction.Next))
                        KField(
                            password, { password = it }, "Password", visual = PasswordVisualTransformation(),
                            keyboard = KeyboardOptions(keyboardType = KeyboardType.Password, imeAction = ImeAction.Done),
                            actions = KeyboardActions(onDone = { submit() }),
                        )
                        if (mode == "signup") Text("At least 10 characters.", style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        KButton(
                            if (busy) "…" else if (mode == "signin") "Sign in" else "Create account",
                            Modifier.fillMaxWidth(), primary = true, enabled = !busy && username.isNotBlank() && password.isNotEmpty(),
                        ) { submit() }
                        if (s.signupMode != "closed") {
                            Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center, verticalAlignment = Alignment.CenterVertically) {
                                Text(if (mode == "signin") "No account yet?" else "Have an account?", style = MaterialTheme.typography.bodyMedium, color = kern.text2)
                                TextAction(if (mode == "signin") "Sign up" else "Sign in") { mode = if (mode == "signin") "signup" else "signin"; error = null }
                            }
                            if (mode == "signup" && s.signupMode == "approval")
                                Text("New accounts on this server wait for an administrator's approval.", style = MaterialTheme.typography.bodySmall, color = kern.text3, textAlign = TextAlign.Center, modifier = Modifier.fillMaxWidth())
                        }
                    }
                }
            }
            if (busy) Row(Modifier.fillMaxWidth(), horizontalArrangement = Arrangement.Center) { CircularProgressIndicator(Modifier.size(20.dp), strokeWidth = 2.dp, color = kern.accent) }
            error?.let { Text(it, color = kern.danger, style = MaterialTheme.typography.bodyMedium) }
            info?.let { Text(it, color = kern.green, style = MaterialTheme.typography.bodyMedium) }
        }
    }
}
