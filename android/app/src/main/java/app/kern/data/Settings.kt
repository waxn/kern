package app.kern.data

import android.content.Context
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.serialization.encodeToString

/** Local, per-device preferences (the server keeps everything else). */
class Settings(context: Context) {
    private val p = context.getSharedPreferences("kern", Context.MODE_PRIVATE)

    var serverUrl: String
        get() = p.getString("server", "") ?: ""
        set(v) = p.edit().putString("server", v.trim().trimEnd('/')).apply()

    private val _theme = MutableStateFlow(p.getString("theme", "system") ?: "system")
    val theme: StateFlow<String> = _theme
    fun setTheme(v: String) { p.edit().putString("theme", v).apply(); _theme.value = v }

    private val _editorSize = MutableStateFlow(p.getString("editor_size", "normal") ?: "normal")
    val editorSize: StateFlow<String> = _editorSize
    fun setEditorSize(v: String) { p.edit().putString("editor_size", v).apply(); _editorSize.value = v }

    var notifyTasks: Boolean
        get() = p.getBoolean("notify_tasks", true)
        set(v) = p.edit().putBoolean("notify_tasks", v).apply()
    var notifyCards: Boolean
        get() = p.getBoolean("notify_cards", true)
        set(v) = p.edit().putBoolean("notify_cards", v).apply()
    /** Hour of the day (local) after which the daily reminders are sent. */
    var notifyHour: Int
        get() = p.getInt("notify_hour", 8)
        set(v) = p.edit().putInt("notify_hour", v.coerceIn(0, 23)).apply()

    var user: User?
        get() = p.getString("user", null)?.let { runCatching { KernJson.decodeFromString<User>(it) }.getOrNull() }
        set(v) = p.edit().putString("user", v?.let { KernJson.encodeToString(it) }).apply()

    // Last-sent markers so each reminder is sent once per day.
    fun sentToday(key: String, day: String) = p.getString("sent_$key", "") == day
    fun markSent(key: String, day: String) = p.edit().putString("sent_$key", day).apply()

    // Cached data for widgets and offline glances.
    var cachedTasks: List<Task>
        get() = p.getString("cache_tasks", null)?.let { runCatching { KernJson.decodeFromString<List<Task>>(it) }.getOrNull() } ?: emptyList()
        set(v) = p.edit().putString("cache_tasks", KernJson.encodeToString(v)).apply()
    var cachedDue: Int
        get() = p.getInt("cache_due", 0)
        set(v) = p.edit().putInt("cache_due", v).apply()
    var cachedNew: Int
        get() = p.getInt("cache_new", 0)
        set(v) = p.edit().putInt("cache_new", v).apply()
    var cachedDocs: List<Doc>
        get() = p.getString("cache_docs", null)?.let { runCatching { KernJson.decodeFromString<List<Doc>>(it) }.getOrNull() } ?: emptyList()
        set(v) = p.edit().putString("cache_docs", KernJson.encodeToString(v)).apply()
    var cachedAt: Long
        get() = p.getLong("cache_at", 0)
        set(v) = p.edit().putLong("cache_at", v).apply()

    var recentSearches: List<String>
        get() = p.getString("recent_searches", "")!!.split("\n").filter { it.isNotBlank() }
        set(v) = p.edit().putString("recent_searches", v.take(8).joinToString("\n")).apply()

    fun clearAccount() {
        p.edit().remove("user").remove("cache_tasks").remove("cache_due").remove("cache_new")
            .remove("cache_docs").remove("cache_at").remove("recent_searches").apply()
    }
}
