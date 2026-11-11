package app.kern.ui

import android.Manifest
import android.os.Build
import androidx.activity.compose.rememberLauncherForActivityResult
import androidx.activity.result.contract.ActivityResultContracts
import androidx.compose.animation.AnimatedVisibility
import androidx.compose.animation.fadeIn
import androidx.compose.animation.fadeOut
import androidx.compose.animation.slideInHorizontally
import androidx.compose.animation.slideOutHorizontally
import androidx.compose.animation.slideInVertically
import androidx.compose.animation.slideOutVertically
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.WindowInsets
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.padding
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.filled.CheckCircle
import androidx.compose.material.icons.filled.Description
import androidx.compose.material.icons.filled.Home
import androidx.compose.material.icons.filled.Style
import androidx.compose.material.icons.outlined.CheckCircle
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.Home
import androidx.compose.material.icons.outlined.Menu
import androidx.compose.material.icons.outlined.Style
import androidx.compose.material.icons.filled.Menu
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.NavigationBar
import androidx.compose.material3.NavigationBarItem
import androidx.compose.material3.NavigationBarItemDefaults
import androidx.compose.material3.Scaffold
import androidx.compose.material3.SnackbarHost
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Snackbar
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
import androidx.compose.ui.Modifier
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.platform.LocalContext
import androidx.navigation.NavGraph.Companion.findStartDestination
import androidx.navigation.NavHostController
import androidx.navigation.NavType
import androidx.navigation.compose.NavHost
import androidx.navigation.compose.composable
import androidx.navigation.compose.currentBackStackEntryAsState
import androidx.navigation.compose.rememberNavController
import androidx.navigation.navArgument
import app.kern.Launch
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Snack
import app.kern.ui.doc.DocScreen
import app.kern.ui.screens.ArchiveScreen
import app.kern.ui.screens.BlobScreen
import app.kern.ui.screens.BookmarkScreen
import app.kern.ui.screens.BookmarksScreen
import app.kern.ui.screens.CardsScreen
import app.kern.ui.screens.ChatScreen
import app.kern.ui.screens.FilesScreen
import app.kern.ui.screens.GitScreen
import app.kern.ui.screens.HomeScreen
import app.kern.ui.screens.IntelligenceScreen
import app.kern.ui.screens.LoginScreen
import app.kern.ui.screens.MoreScreen
import app.kern.ui.screens.PagesScreen
import app.kern.ui.screens.RepoScreen
import app.kern.ui.screens.ReviewScreen
import app.kern.ui.screens.SearchScreen
import app.kern.ui.screens.SettingsScreen
import app.kern.ui.screens.ShareSheet
import app.kern.ui.screens.TagScreen
import app.kern.ui.screens.TagsScreen
import app.kern.ui.screens.TasksScreen
import app.kern.ui.screens.TemplatesScreen
import app.kern.ui.screens.TrashScreen
import app.kern.ui.theme.kern
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.launch

private data class Tab(val route: String, val label: String, val icon: ImageVector, val selected: ImageVector)

private val TABS = listOf(
    Tab("home", "Home", Icons.Outlined.Home, Icons.Filled.Home),
    Tab("pages", "Pages", Icons.Outlined.Description, Icons.Filled.Description),
    Tab("tasks", "Tasks", Icons.Outlined.CheckCircle, Icons.Filled.CheckCircle),
    Tab("cards", "Cards", Icons.Outlined.Style, Icons.Filled.Style),
    Tab("more", "More", Icons.Outlined.Menu, Icons.Filled.Menu),
)

/** Navigation helpers shared by every screen. */
class Nav(val c: NavHostController) {
    /** Opens [route] unless it is exactly what is showing already (so doc/A → doc/B still stacks). */
    fun go(route: String) {
        if (c.currentBackStackEntry?.let { e -> e.destination.route?.let { fill(it, e.arguments) } } == route) return
        c.navigate(route)
    }
    private fun fill(pattern: String, args: android.os.Bundle?): String =
        Regex("\\{(\\w+)\\}").replace(pattern) { args?.getString(it.groupValues[1]) ?: "" }.replace(Regex("[?&]\\w+=(?=&|$)"), "")
    fun back() { if (!c.popBackStack()) tab("home") }
    fun doc(id: String) = go("doc/$id")
    fun tab(route: String) = c.navigate(route) {
        popUpTo(c.graph.findStartDestination().id) { saveState = true }
        launchSingleTop = true
        restoreState = true
    }

    /** Opens what a ref or link in rich text points to. Returns false for plain URLs. */
    fun ref(target: String, openUrl: (String) -> Unit) {
        when {
            target.startsWith("doc:") -> doc(target.removePrefix("doc:"))
            target.startsWith("tag:") -> go("tag/${target.removePrefix("tag:")}")
            target.startsWith("block:") -> go("block/${target.removePrefix("block:")}")
            target.startsWith("/doc/") -> doc(target.removePrefix("/doc/").substringBefore('#'))
            target.startsWith("/tag/") -> go("tag/${target.removePrefix("/tag/")}")
            else -> openUrl(target)
        }
    }
}

@Composable
fun KernRoot(ws: Workspace, launch: MutableStateFlow<Launch?>) {
    val session by ws.session.collectAsState()
    val host = remember { SnackbarHostState() }
    val scope = rememberCoroutineScope()
    val snack = remember { Snack(host, scope) }
    CompositionLocalProvider(LocalSnack provides snack) {
        when (val s = session) {
            is Session.SignedIn -> SignedIn(ws, launch, host)
            else -> Scaffold(snackbarHost = { KSnackHost(host) }) { pad ->
                Box(Modifier.padding(pad)) { LoginScreen(ws) }
            }
        }
    }
}

@Composable
private fun KSnackHost(host: SnackbarHostState) = SnackbarHost(host) {
    Snackbar(it, containerColor = kern.surface2, contentColor = kern.text, actionColor = kern.accent)
}

@Composable
private fun SignedIn(ws: Workspace, launch: MutableStateFlow<Launch?>, host: SnackbarHostState) {
    val nav = rememberNavController()
    val n = remember(nav) { Nav(nav) }
    val entry by nav.currentBackStackEntryAsState()
    val route = entry?.destination?.route ?: "home"
    val showBar = TABS.any { route.substringBefore('?') == it.route }
    val pending by launch.collectAsState()
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    var share by remember { mutableStateOf<Launch.Share?>(null) }
    val ctx = LocalContext.current

    // Ask once for notification permission (Android 13+), so reminders can be shown.
    val permission = rememberLauncherForActivityResult(ActivityResultContracts.RequestPermission()) {}
    LaunchedEffect(Unit) {
        if (Build.VERSION.SDK_INT >= 33 && !app.kern.notify.Notifications.allowed(ctx)) permission.launch(Manifest.permission.POST_NOTIFICATIONS)
    }

    LaunchedEffect(pending) {
        val l = pending ?: return@LaunchedEffect
        launch.value = null
        when (l) {
            is Launch.Share -> share = l
            is Launch.Route -> when (val r = l.route) {
                "home" -> n.tab("home")
                "new-page" -> scope.launch {
                    try { n.doc(ws.newPage().id) } catch (e: Exception) { snack.error(e) }
                }
                "new-task" -> n.go("tasks?add=1")
                "new-bookmark" -> n.go("bookmarks?add=1")
                "tasks" -> n.tab("tasks")
                else -> if (r.startsWith("tasks?task=")) n.go(r) else n.go(r)
            }
        }
    }

    Scaffold(
        contentWindowInsets = WindowInsets(0, 0, 0, 0),
        snackbarHost = { KSnackHost(host) },
        bottomBar = {
            AnimatedVisibility(showBar, enter = slideInVertically { it } + fadeIn(), exit = slideOutVertically { it } + fadeOut()) {
                NavigationBar(containerColor = kern.side, tonalElevation = androidx.compose.ui.unit.Dp(0f)) {
                    for (t in TABS) {
                        val sel = route.substringBefore('?') == t.route
                        NavigationBarItem(
                            selected = sel,
                            onClick = { n.tab(t.route) },
                            icon = { Icon(if (sel) t.selected else t.icon, t.label) },
                            label = { Text(t.label, style = MaterialTheme.typography.labelMedium) },
                            colors = NavigationBarItemDefaults.colors(
                                selectedIconColor = kern.accent, selectedTextColor = kern.text,
                                indicatorColor = kern.tint(kern.accent), unselectedIconColor = kern.text3, unselectedTextColor = kern.text3,
                            ),
                        )
                    }
                }
            }
        },
    ) { pad ->
        NavHost(
            nav, startDestination = "home",
            modifier = Modifier.fillMaxSize().padding(bottom = pad.calculateBottomPadding()),
            enterTransition = { fadeIn() + slideInHorizontally { it / 12 } },
            exitTransition = { fadeOut() },
            popEnterTransition = { fadeIn() },
            popExitTransition = { fadeOut() + slideOutHorizontally { it / 12 } },
        ) {
            composable("home") { HomeScreen(ws, n) }
            composable("pages") { PagesScreen(ws, n) }
            composable("tasks?add={add}&task={task}", arguments = listOf(
                navArgument("add") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("task") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { TasksScreen(ws, n, it.arguments?.getString("add") != null, it.arguments?.getString("task")) }
            composable("cards") { CardsScreen(ws, n) }
            composable("more") { MoreScreen(ws, n) }
            composable("doc/{id}") { DocScreen(ws, n, it.arguments!!.getString("id")!!) }
            composable("block/{id}") { app.kern.ui.doc.BlockRedirect(ws, n, it.arguments!!.getString("id")!!) }
            composable("search") { SearchScreen(ws, n) }
            composable("review?deck={deck}&doc={doc}", arguments = listOf(
                navArgument("deck") { type = NavType.StringType; nullable = true; defaultValue = null },
                navArgument("doc") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { ReviewScreen(ws, n, it.arguments?.getString("deck"), it.arguments?.getString("doc")) }
            composable("intelligence") { IntelligenceScreen(ws, n) }
            composable("chat/{id}?page={page}", arguments = listOf(
                navArgument("page") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { ChatScreen(ws, n, it.arguments!!.getString("id")!!, it.arguments?.getString("page")) }
            composable("bookmarks?add={add}", arguments = listOf(
                navArgument("add") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { BookmarksScreen(ws, n, it.arguments?.getString("add") != null) }
            composable("bookmark/{id}") { BookmarkScreen(ws, n, it.arguments!!.getString("id")!!.toLong()) }
            composable("tags") { TagsScreen(ws, n) }
            composable("tag/{id}") { TagScreen(ws, n, it.arguments!!.getString("id")!!) }
            composable("files") { FilesScreen(ws, n) }
            composable("git") { GitScreen(ws, n) }
            composable("repo/{name}?path={path}&ref={ref}", arguments = listOf(
                navArgument("path") { type = NavType.StringType; defaultValue = "" },
                navArgument("ref") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { RepoScreen(ws, n, it.arguments!!.getString("name")!!, it.arguments?.getString("path") ?: "", it.arguments?.getString("ref")) }
            composable("blob/{name}?path={path}&ref={ref}", arguments = listOf(
                navArgument("path") { type = NavType.StringType; defaultValue = "" },
                navArgument("ref") { type = NavType.StringType; nullable = true; defaultValue = null },
            )) { BlobScreen(ws, n, it.arguments!!.getString("name")!!, it.arguments?.getString("path") ?: "", it.arguments?.getString("ref")) }
            composable("trash") { TrashScreen(ws, n) }
            composable("archive") { ArchiveScreen(ws, n) }
            composable("templates") { TemplatesScreen(ws, n) }
            composable("settings") { SettingsScreen(ws, n) }
        }
    }

    share?.let { s -> ShareSheet(ws, n, s.text, s.subject) { share = null } }
}
