package app.kern

import android.content.Intent
import android.os.Bundle
import androidx.activity.ComponentActivity
import androidx.activity.SystemBarStyle
import androidx.activity.compose.setContent
import androidx.activity.enableEdgeToEdge
import androidx.activity.viewModels
import androidx.compose.runtime.collectAsState
import androidx.compose.runtime.getValue
import app.kern.ui.KernRoot
import app.kern.ui.Workspace
import app.kern.ui.theme.KernTheme
import kotlinx.coroutines.flow.MutableStateFlow

/** What the app was opened for: a route (from a widget, shortcut or notification) or shared text. */
sealed interface Launch {
    data class Route(val route: String) : Launch
    data class Share(val text: String, val subject: String?) : Launch
}

class MainActivity : ComponentActivity() {
    private val ws: Workspace by viewModels()
    private val launch = MutableStateFlow<Launch?>(null)

    override fun onCreate(savedInstanceState: Bundle?) {
        super.onCreate(savedInstanceState)
        enableEdgeToEdge(
            statusBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT),
            navigationBarStyle = SystemBarStyle.auto(android.graphics.Color.TRANSPARENT, android.graphics.Color.TRANSPARENT),
        )
        if (savedInstanceState == null) handle(intent)
        setContent {
            val theme by app.settings.theme.collectAsState()
            KernTheme(theme) { KernRoot(ws, launch) }
        }
    }

    override fun onNewIntent(intent: Intent) {
        super.onNewIntent(intent)
        handle(intent)
    }

    private fun handle(intent: Intent?) {
        intent ?: return
        launch.value = when {
            intent.action == Intent.ACTION_SEND -> intent.getStringExtra(Intent.EXTRA_TEXT)?.let {
                Launch.Share(it, intent.getStringExtra(Intent.EXTRA_SUBJECT))
            }
            intent.hasExtra(EXTRA_ROUTE) -> Launch.Route(intent.getStringExtra(EXTRA_ROUTE)!!)
            intent.action == "app.kern.NEW_PAGE" -> Launch.Route("new-page")
            intent.action == "app.kern.NEW_TASK" -> Launch.Route("new-task")
            intent.action == "app.kern.REVIEW" -> Launch.Route("review")
            intent.action == "app.kern.SEARCH" -> Launch.Route("search")
            else -> launch.value
        }
    }

    companion object {
        const val EXTRA_ROUTE = "route"
    }
}
