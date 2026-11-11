package app.kern.ui.screens

import android.content.ClipData
import android.content.ClipboardManager
import androidx.compose.foundation.background
import androidx.compose.foundation.clickable
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.statusBarsPadding
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.lazy.LazyColumn
import androidx.compose.foundation.lazy.items
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.foundation.text.selection.SelectionContainer
import androidx.compose.foundation.verticalScroll
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.InsertDriveFile
import androidx.compose.material.icons.outlined.AccountTree
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material.icons.outlined.ContentCopy
import androidx.compose.material.icons.outlined.Folder
import androidx.compose.material.icons.outlined.History
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.LaunchedEffect
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.platform.LocalContext
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.data.Blob
import app.kern.data.Commit
import app.kern.data.KernJson
import app.kern.data.Repo
import app.kern.data.RepoTree
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.EmptyState
import app.kern.ui.components.ErrorState
import app.kern.ui.components.KButton
import app.kern.ui.components.KField
import app.kern.ui.components.KTopBar
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.ago
import app.kern.ui.components.bytes
import app.kern.ui.doc.KSheet
import app.kern.ui.theme.kern
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import java.net.URLEncoder

private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

@Composable
fun GitScreen(ws: Workspace, nav: Nav) {
    var repos by remember { mutableStateOf<List<Repo>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var creating by remember { mutableStateOf(false) }
    val scope = rememberCoroutineScope()
    suspend fun load() { try { repos = ws.kern.repos(); err = null } catch (e: Exception) { err = e.message } }
    LaunchedEffect(Unit) { load() }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar("Git", onBack = { nav.back() }) { IconButton(onClick = { creating = true }) { Icon(Icons.Outlined.Add, "New repository", tint = kern.accent) } }
        when {
            repos == null && err != null -> ErrorState(err!!) { scope.launch { load() } }
            repos == null -> Loading()
            repos!!.isEmpty() -> EmptyState(Icons.Outlined.AccountTree, "No repositories", "Create one, then push to it from any git client.", action = "New repository" to { creating = true })
            else -> LazyColumn {
                items(repos!!, key = { it.name }) { r ->
                    Column(Modifier.fillMaxWidth().clickable { nav.go("repo/${r.name}") }.padding(horizontal = 20.dp, vertical = 12.dp)) {
                        Row(verticalAlignment = Alignment.CenterVertically) {
                            Icon(Icons.Outlined.AccountTree, null, tint = kern.accent, modifier = Modifier.size(18.dp))
                            Spacer(Modifier.width(10.dp))
                            Text(r.name, style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
                            Text(bytes(r.size), style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        }
                        if (r.description.isNotBlank()) Text(r.description, style = MaterialTheme.typography.bodyMedium, color = kern.text2, modifier = Modifier.padding(start = 28.dp))
                        Text(
                            if (r.empty) "Empty — push to get started" else "${r.defaultBranch ?: ""} · ${r.lastCommit?.subject ?: ""} · ${ago(r.lastPush ?: r.lastCommit?.date)}",
                            style = MaterialTheme.typography.bodySmall, color = kern.text3, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(start = 28.dp, top = 2.dp),
                        )
                    }
                }
            }
        }
    }
    if (creating) {
        var name by remember { mutableStateOf("") }
        var desc by remember { mutableStateOf("") }
        val snack = LocalSnack.current
        KSheet({ creating = false }, "New repository") {
            Column(Modifier.padding(horizontal = 16.dp), verticalArrangement = Arrangement.spacedBy(10.dp)) {
                KField(name, { name = it }, "Name", placeholder = "my-project")
                KField(desc, { desc = it }, "Description (optional)")
                KButton("Create", Modifier.fillMaxWidth(), primary = true, enabled = name.isNotBlank()) {
                    scope.launch { runCatching { ws.kern.createRepo(name.trim(), desc) }.onSuccess { creating = false; load(); nav.go("repo/${it.name}") }.onFailure { snack.error(it) } }
                }
            }
        }
    }
}

@Composable
fun RepoScreen(ws: Workspace, nav: Nav, name: String, path: String, ref: String?) {
    var tree by remember { mutableStateOf<RepoTree?>(null) }
    var commits by remember { mutableStateOf<List<Commit>?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var tab by remember { mutableStateOf("files") }
    val ctx = LocalContext.current
    val snack = LocalSnack.current
    LaunchedEffect(name, path, ref) { try { tree = ws.kern.repoTree(name, ref, path) } catch (e: Exception) { err = e.message } }
    LaunchedEffect(tab) {
        if (tab == "log" && commits == null) commits = runCatching {
            (ws.kern.repoCommits(name, ref)["commits"] as JsonArray).map { KernJson.decodeFromJsonElement(Commit.serializer(), it) }
        }.getOrDefault(emptyList())
    }
    val clone = "${ws.kern.api.base}/git/$name.git"
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar(if (path.isEmpty()) name else path.substringAfterLast('/'), onBack = { nav.back() }, subtitle = if (path.isEmpty()) ref ?: "default branch" else "$name / $path")
        if (path.isEmpty()) {
            Row(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(kern.surface2).padding(start = 12.dp), verticalAlignment = Alignment.CenterVertically) {
                Text(clone, fontFamily = FontFamily.Monospace, fontSize = 12.sp, color = kern.text2, maxLines = 1, overflow = TextOverflow.Ellipsis, modifier = Modifier.weight(1f))
                IconButton(onClick = {
                    ctx.getSystemService(ClipboardManager::class.java).setPrimaryClip(ClipData.newPlainText("clone", clone)); snack.show("Clone URL copied")
                }) { Icon(Icons.Outlined.ContentCopy, "Copy clone URL", tint = kern.text2, modifier = Modifier.size(18.dp)) }
            }
            Row(Modifier.padding(horizontal = 12.dp, vertical = 8.dp)) {
                Box(Modifier.padding(4.dp)) { Choice("Files", tab == "files") { tab = "files" } }
                Box(Modifier.padding(4.dp)) { Choice("Commits", tab == "log") { tab = "log" } }
            }
        }
        val t = tree
        when {
            t == null && err != null -> ErrorState(err!!) {}
            t == null -> Loading()
            tab == "log" -> if (commits == null) Loading() else LazyColumn {
                items(commits!!, key = { it.sha }) { c ->
                    Row(Modifier.fillMaxWidth().padding(horizontal = 20.dp, vertical = 10.dp), verticalAlignment = Alignment.Top) {
                        Icon(Icons.Outlined.History, null, tint = kern.text3, modifier = Modifier.size(16.dp).padding(top = 2.dp))
                        Spacer(Modifier.width(12.dp))
                        Column(Modifier.weight(1f)) {
                            Text(c.subject, style = MaterialTheme.typography.bodyMedium, maxLines = 2, overflow = TextOverflow.Ellipsis)
                            Text("${c.author} · ${ago(c.date)} · ${c.sha.take(7)}", style = MaterialTheme.typography.bodySmall, color = kern.text3)
                        }
                    }
                }
            }
            t.sha == null -> EmptyState(Icons.Outlined.AccountTree, "Empty repository", "git remote add kern $clone\ngit push -u kern main")
            else -> LazyColumn {
                t.lastCommit?.let { c ->
                    item { Text("${c.subject} · ${ago(c.date)}", style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(horizontal = 20.dp, vertical = 6.dp), maxLines = 1, overflow = TextOverflow.Ellipsis) }
                }
                items(t.entries, key = { it.path }) { e ->
                    Row(Modifier.fillMaxWidth().clickable {
                        val r = ref?.let { "&ref=${enc(it)}" } ?: ""
                        if (e.type == "tree") nav.go("repo/$name?path=${enc(e.path)}$r") else if (e.type == "blob") nav.go("blob/$name?path=${enc(e.path)}$r")
                    }.padding(horizontal = 20.dp, vertical = 11.dp), verticalAlignment = Alignment.CenterVertically) {
                        Icon(if (e.type == "tree") Icons.Outlined.Folder else Icons.AutoMirrored.Outlined.InsertDriveFile, null, tint = if (e.type == "tree") kern.accent else kern.text3, modifier = Modifier.size(18.dp))
                        Spacer(Modifier.width(12.dp))
                        Text(e.name, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                        e.size?.let { Text(bytes(it), style = MaterialTheme.typography.bodySmall, color = kern.text3) }
                    }
                }
                t.readme?.let { rd ->
                    item {
                        Column(Modifier.padding(16.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).background(kern.surface).padding(16.dp)) {
                            Text(rd.name, style = MaterialTheme.typography.labelSmall, color = kern.text3)
                            Spacer(Modifier.height(8.dp))
                            Text(markdown(rd.text, kern), style = MaterialTheme.typography.bodyMedium)
                        }
                    }
                }
            }
        }
    }
}

@Composable
fun BlobScreen(ws: Workspace, nav: Nav, name: String, path: String, ref: String?) {
    var blob by remember { mutableStateOf<Blob?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    LaunchedEffect(path) { try { blob = ws.kern.repoBlob(name, ref, path) } catch (e: Exception) { err = e.message } }
    Column(Modifier.fillMaxSize().background(kern.bg).statusBarsPadding()) {
        KTopBar(path.substringAfterLast('/'), onBack = { nav.back() }, subtitle = blob?.let { "${bytes(it.size)}" + if (it.truncated) " · truncated" else "" })
        val b = blob
        when {
            b == null && err != null -> ErrorState(err!!) {}
            b == null -> Loading()
            b.binary || b.text == null -> EmptyState(Icons.AutoMirrored.Outlined.InsertDriveFile, "Binary file", "Open it in the web app to download.")
            path.endsWith(".md", true) -> Column(Modifier.verticalScroll(rememberScrollState()).padding(20.dp)) {
                SelectionContainer { Text(markdown(b.text, kern), style = MaterialTheme.typography.bodyMedium) }
            }
            else -> Box(Modifier.fillMaxSize().verticalScroll(rememberScrollState()).horizontalScroll(rememberScrollState()).padding(12.dp)) {
                SelectionContainer {
                    Text(
                        b.text.lines().mapIndexed { i, l -> "${(i + 1).toString().padStart(4)}  $l" }.joinToString("\n"),
                        fontFamily = FontFamily.Monospace, fontSize = 12.5.sp, lineHeight = 18.sp, color = kern.text,
                    )
                }
            }
        }
    }
}
