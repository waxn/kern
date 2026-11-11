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

    /** Minutes between flashcard reminders while cards are due; 0 = once a day. */
    var cardsEveryMin: Int
        get() = p.getInt("cards_every", 90)
        set(v) = p.edit().putInt("cards_every", v).apply()
    /** Hour of the day (local) after which no more reminders are sent. */
    var quietHour: Int
        get() = p.getInt("quiet_hour", 22)
        set(v) = p.edit().putInt("quiet_hour", v.coerceIn(1, 24)).apply()
    /** Last flashcard reminder or review, so reminders keep their cooldown. */
    var cardsLastNudge: Long
        get() = p.getLong("cards_last_nudge", 0)
        set(v) = p.edit().putLong("cards_last_nudge", v).apply()

    /** Only remind once at least this many cards are waiting. */
    var cardsMin: Int
        get() = p.getInt("cards_min", 1)
        set(v) = p.edit().putInt("cards_min", v.coerceAtLeast(1)).apply()
    /** Count new cards as "waiting", not just reviews that are due. */
    var cardsIncludeNew: Boolean
        get() = p.getBoolean("cards_include_new", true)
        set(v) = p.edit().putBoolean("cards_include_new", v).apply()
    /** "Later" on a card reminder holds the next one off for this many minutes. */
    var cardsSnoozeMin: Int
        get() = p.getInt("cards_snooze", 60)
        set(v) = p.edit().putInt("cards_snooze", v).apply()
    /** Remind about overdue tasks too, not only those due today. */
    var tasksIncludeOverdue: Boolean
        get() = p.getBoolean("tasks_overdue", true)
        set(v) = p.edit().putBoolean("tasks_overdue", v).apply()
    /** Only tasks at or above this priority (0 = all). */
    var tasksMinPriority: Int
        get() = p.getInt("tasks_min_priority", 0)
        set(v) = p.edit().putInt("tasks_min_priority", v.coerceIn(0, 3)).apply()
    /** Days of the week reminders are sent on, 1 = Monday … 7 = Sunday. */
    var reminderDays: Set<Int>
        get() = (p.getString("reminder_days", "1234567") ?: "1234567").mapNotNull { it.digitToIntOrNull() }.toSet()
        set(v) = p.edit().putString("reminder_days", v.sorted().joinToString("")).apply()

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
