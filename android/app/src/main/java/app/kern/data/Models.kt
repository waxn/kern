package app.kern.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.intOrNull

@Serializable
data class User(
    val id: Int,
    val username: String,
    val email: String = "",
    @SerialName("is_admin") val isAdmin: Boolean = false,
    @SerialName("is_active") val isActive: Boolean = true,
    @SerialName("date_joined") val dateJoined: String? = null,
    @SerialName("last_login") val lastLogin: String? = null,
    @SerialName("storage_bytes") val storageBytes: Long? = null,
    @SerialName("two_factor") val twoFactor: Boolean = false,
)

@Serializable
data class SiteInfo(
    @SerialName("needs_setup") val needsSetup: Boolean = false,
    @SerialName("site_name") val siteName: String = "Kern",
    @SerialName("landing_enabled") val landingEnabled: Boolean = false,
    @SerialName("signup_mode") val signupMode: String = "closed",
    @SerialName("allow_git") val allowGit: Boolean = true,
    @SerialName("allow_mail") val allowMail: Boolean = true,
    val user: User? = null,
    val pending: Boolean = false,
)

@Serializable
data class Doc(
    val id: String,
    val parent: String? = null,
    val title: String = "",
    val icon: String = "",
    val cover: String = "",
    val position: Double = 0.0,
    @SerialName("is_favorite") val isFavorite: Boolean = false,
    @SerialName("is_archived") val isArchived: Boolean = false,
    @SerialName("trashed_at") val trashedAt: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    @SerialName("last_opened_at") val lastOpenedAt: String? = null,
    @SerialName("entry_of") val entryOf: String? = null,
    val database: String? = null,
    @SerialName("is_template") val isTemplate: Boolean = false,
    val kind: String = "page",
    @SerialName("template_tag") val templateTag: String? = null,
    @SerialName("template_db") val templateDb: String? = null,
    val tags: List<String> = emptyList(),
    val empty: Boolean = false,
) {
    val displayTitle get() = title.ifBlank { "Untitled" }
}

@Serializable
data class Block(
    val id: String,
    val parent: String? = null,
    val position: Double = 0.0,
    val type: String = "paragraph",
    val html: String = "",
    val props: JsonObject = JsonObject(emptyMap()),
    val collapsed: Boolean = false,
)

@Serializable
data class Tag(
    val id: String,
    val name: String,
    val color: String = "",
    @SerialName("doc_count") val docCount: Int? = null,
)

@Serializable
data class PropOption(val id: String, val name: String, val color: String = "", val group: String? = null)

@Serializable
data class PropDef(
    val id: String,
    val tag: String? = null,
    val name: String,
    val type: String,
    val options: List<PropOption> = emptyList(),
    val config: JsonObject = JsonObject(emptyMap()),
    val database: String? = null,
    val position: Double = 0.0,
)

@Serializable
data class RefInfo(
    val title: String = "",
    val icon: String? = null,
    val color: String? = null,
    val doc: String? = null,
    @SerialName("doc_title") val docTitle: String? = null,
    val trashed: Boolean = false,
)

@Serializable
data class DocProps(val defs: List<PropDef> = emptyList(), val values: JsonObject = JsonObject(emptyMap()))

@Serializable
data class BlockTask(val id: String, val due: String? = null, val priority: Int = 0, val done: Boolean = false)

@Serializable
data class DocPayload(
    val document: Doc,
    val blocks: List<Block> = emptyList(),
    val refs: Map<String, RefInfo> = emptyMap(),
    val properties: DocProps = DocProps(),
    @SerialName("block_backlinks") val blockBacklinks: Map<String, Int> = emptyMap(),
    @SerialName("block_cards") val blockCards: Map<String, Int> = emptyMap(),
    @SerialName("block_tasks") val blockTasks: Map<String, BlockTask> = emptyMap(),
    @SerialName("card_count") val cardCount: Int = 0,
    val version: String? = null,
    @SerialName("backlink_count") val backlinkCount: Int = 0,
)

@Serializable
data class SyncResult(
    val ok: Boolean = false,
    val version: String? = null,
    val patched: List<Block> = emptyList(),
    val detail: String? = null,
)

@Serializable
data class BacklinkItem(val block: String, val type: String = "", val html: String = "", val context: String = "")

@Serializable
data class BacklinkDoc(val id: String, val title: String = "", val icon: String = "")

@Serializable
data class BacklinkGroup(val doc: BacklinkDoc, val items: List<BacklinkItem> = emptyList())

@Serializable
data class SearchResult(
    val kind: String,
    val id: String,
    val title: String = "",
    val snippet: String = "",
    val doc: String? = null,
    @SerialName("doc_title") val docTitle: String? = null,
    val icon: String? = null,
    val path: List<String> = emptyList(),
    val color: String? = null,
)

@Serializable
data class SearchResponse(val results: List<SearchResult> = emptyList(), val counts: Map<String, Int> = emptyMap())

@Serializable
data class Suggestion(
    val kind: String,
    val id: String,
    val title: String = "",
    val icon: String? = null,
    val color: String? = null,
    val path: List<String> = emptyList(),
    val doc: String? = null,
    @SerialName("doc_title") val docTitle: String? = null,
)

@Serializable
data class Recurrence(val freq: String, val interval: Int = 1)

@Serializable
data class Task(
    val id: String,
    val title: String = "",
    val description: String = "",
    val done: Boolean = false,
    @SerialName("completed_at") val completedAt: String? = null,
    val priority: Int = 0,
    val due: String? = null,
    val start: String? = null,
    val recurrence: Recurrence? = null,
    val document: String? = null,
    val project: String? = null,
    val block: String? = null,
    val tags: List<String> = emptyList(),
    /** Made from an email or a follow-up nudge (backend mail/taskbridge.py). */
    val source: TaskSource? = null,
    val position: Double = 0.0,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class TaskSource(val kind: String = "", val key: String = "", val subject: String = "", val from: String = "")

@Serializable
data class TaskSummary(
    val inbox: Int = 0,
    val today: Int = 0,
    val overdue: Int = 0,
    val upcoming: Int = 0,
    val open: Int = 0,
    @SerialName("completed_week") val completedWeek: Int = 0,
)

@Serializable
data class Region(val id: String = "", val n: Int = 1, val x: Double = 0.0, val y: Double = 0.0, val w: Double = 0.0, val h: Double = 0.0, val label: String = "")

@Serializable
data class Card(
    val id: String,
    val note: String = "",
    val kind: String = "basic",
    val ordinal: Int = 0,
    val state: String = "new",
    val due: String? = null,
    val reps: Int = 0,
    val lapses: Int = 0,
    val stability: Double = 0.0,
    val difficulty: Double = 0.0,
    @SerialName("last_review") val lastReview: String? = null,
    val suspended: Boolean = false,
    val deck: String? = null,
    val document: String? = null,
    @SerialName("doc_title") val docTitle: String? = null,
    val block: String? = null,
    val front: String = "",
    val back: String = "",
    val image: String? = null,
    val regions: List<Region>? = null,
    val intervals: Map<String, Double>? = null,
)

@Serializable
data class QueueCounts(val learning: Int = 0, val review: Int = 0, val new: Int = 0) {
    val total get() = learning + review + new
}

@Serializable
data class CardQueue(
    val card: Card? = null,
    val counts: QueueCounts = QueueCounts(),
    @SerialName("next_learning") val nextLearning: String? = null,
)

@Serializable
data class Deck(val id: String, val name: String, val total: Int = 0, val new: Int = 0, val due: Int = 0)

@Serializable
data class CardSettings(
    @SerialName("new_per_day") val newPerDay: Int = 20,
    @SerialName("reviews_per_day") val reviewsPerDay: Int = 200,
    val retention: Double = 0.9,
    @SerialName("show_intervals") val showIntervals: Boolean = true,
)

@Serializable
data class CardStats(
    @SerialName("due_today") val dueToday: Int = 0,
    @SerialName("due_total") val dueTotal: Int = 0,
    @SerialName("new_available") val newAvailable: Int = 0,
    @SerialName("reviewed_today") val reviewedToday: Int = 0,
    @SerialName("time_today_ms") val timeTodayMs: Long = 0,
    @SerialName("accuracy_today") val accuracyToday: Double? = null,
    @SerialName("accuracy_30d") val accuracy30d: Double? = null,
    val counts: Map<String, Int> = emptyMap(),
    val suspended: Int = 0,
    val forecast: List<Int> = emptyList(),
    val history: Map<String, Int> = emptyMap(),
    val settings: CardSettings = CardSettings(),
)

@Serializable
data class DbInfo(val id: String, val page: String, val title: String = "", val icon: String = "")

@Serializable
data class DbRow(
    val id: String,
    val title: String = "",
    val icon: String = "",
    val cover: String = "",
    val position: Double = 0.0,
    @SerialName("created_at") val createdAt: String? = null,
    @SerialName("updated_at") val updatedAt: String? = null,
    val values: JsonObject = JsonObject(emptyMap()),
)

@Serializable
data class DbView(val id: String, val name: String = "", val type: String = "table", val config: JsonObject = JsonObject(emptyMap()), val position: Double = 0.0)

@Serializable
data class TemplateRef(val id: String, val title: String = "", val icon: String = "")

@Serializable
data class DbPayload(
    val database: DbInfo,
    val properties: List<PropDef> = emptyList(),
    val views: List<DbView> = emptyList(),
    val rows: List<DbRow> = emptyList(),
    val templates: List<TemplateRef> = emptyList(),
)

@Serializable
data class ChatAction(val kind: String? = null, val label: String? = null, val title: String? = null, val doc: String? = null, val id: String? = null, val href: String? = null)

@Serializable
data class ChatMessage(
    val role: String,
    val text: String = "",
    val at: String? = null,
    val actions: List<JsonElement> = emptyList(),
    val sources: List<JsonElement> = emptyList(),
)

@Serializable
data class Chat(
    val id: String,
    val title: String = "New chat",
    @SerialName("updated_at") val updatedAt: String? = null,
    val messages: List<ChatMessage> = emptyList(),
)

@Serializable
data class WebItem(
    val id: Long,
    val url: String,
    val title: String = "",
    val kind: String = "web",
    val thumbnail: String = "",
    val duration: Double? = null,
    val author: String = "",
    val description: String = "",
    @SerialName("is_processed") val isProcessed: Boolean = false,
    @SerialName("error_message") val errorMessage: String = "",
    @SerialName("video_status") val videoStatus: String = "",
    @SerialName("video_progress") val videoProgress: Double? = null,
    @SerialName("video_url") val videoUrl: String? = null,
    @SerialName("created_at") val createdAt: String? = null,
    val notes: String = "",
    val todos: List<WebTodo> = emptyList(),
    @SerialName("has_snapshot") val hasSnapshot: Boolean = false,
    val tags: List<String> = emptyList(),
    /** Only set for watched bookmarks or ones with unseen changes (on list items). */
    val monitor: WebMonitor? = null,
    /** How many saved versions the history holds (detail only). */
    val versions: Int = 0,
) {
    val unseen get() = monitor?.unseen ?: 0
    val canWatch get() = kind == "web" || kind == "mixed"
}

@Serializable
data class WebTodo(val text: String, val done: Boolean = false)

/**
 * The bookmark's watch state. List items carry a short form (`price` a display string, `error`
 * a flag); the detail carries the full one (`price` an object, `error` the message), so those
 * two stay raw JSON and are read through [priceText] and [errorText].
 */
@Serializable
data class WebMonitor(
    val enabled: Boolean = false,
    val mode: String = "auto",
    @SerialName("resolved_mode") val resolvedMode: String = "",
    val interval: Int = 1440,
    val archive: Boolean = true,
    @SerialName("error") val errorRaw: JsonElement? = null,
    @SerialName("last_checked_at") val lastCheckedAt: String? = null,
    @SerialName("next_check_at") val nextCheckAt: String? = null,
    @SerialName("last_changed_at") val lastChangedAt: String? = null,
    val unseen: Int = 0,
    @SerialName("last_change") val lastChangeRaw: JsonElement? = null,
    @SerialName("price") val priceRaw: JsonElement? = null,
    val latest: List<WebPost> = emptyList(),
    @SerialName("feed_url") val feedUrl: String = "",
) {
    val priceText: String get() = WebChange.priceDisplay(priceRaw)
    /** The error message (detail), or "" — a summary only says whether there is one. */
    val errorText: String get() = (errorRaw as? JsonPrimitive)?.takeIf { it.isString }?.content.orEmpty()
    val hasError: Boolean get() = errorText.isNotBlank() || (errorRaw as? JsonPrimitive)?.booleanOrNull == true
    val lastChange: WebChange? get() = WebChange.parse(lastChangeRaw)
    /** What is actually being watched: the mode the server picked for "auto", else the chosen one. */
    val watching: String get() = resolvedMode.ifBlank { mode }
}

@Serializable
data class WebPost(val title: String = "", val url: String = "", val date: String = "")

@Serializable
data class WebChanges(val changed: Int = 0, val watched: Int = 0)

@Serializable
data class WebVersion(
    val id: Long,
    @SerialName("created_at") val createdAt: String? = null,
    val trigger: String = "",
    val url: String = "",
    val title: String = "",
    @SerialName("change") val changeRaw: JsonElement? = null,
    val price: String = "",
    val size: Long = 0,
    @SerialName("has_page") val hasPage: Boolean = false,
    val prev: Long? = null,
) {
    val change: WebChange? get() = WebChange.parse(changeRaw)
    val triggerLabel: String get() = when (trigger) {
        "saved" -> "Bookmarked"; "manual" -> "Snapshot"; "change" -> "Change found"; "refetch" -> "Re-fetched"
        else -> trigger.replaceFirstChar { it.uppercase() }
    }
}

/** A change the watcher found (`monitor.last_change`, or a version's `change`). */
sealed class WebChange {
    abstract val at: String?

    data class Posts(val count: Int, val added: List<WebPost>, override val at: String? = null) : WebChange()
    data class Price(val old: String, val new: String, val dropped: Boolean, override val at: String? = null) : WebChange()
    data class Content(val added: Int, val removed: Int, val snippets: List<String>, override val at: String? = null) : WebChange()

    /** One line, e.g. "2 new posts", "Price $20 → $17.50" or "Text changed (+3 / −1 lines)". */
    val text: String get() = when (this) {
        is Posts -> "$count new post${if (count == 1) "" else "s"}"
        is Price -> "Price $old → $new"
        is Content -> {
            val parts = listOfNotNull(if (added > 0) "+$added" else null, if (removed > 0) "−$removed" else null)
            "Text changed (${parts.joinToString(" / ")} ${if (added + removed == 1) "line" else "lines"})"
        }
    }

    companion object {
        private fun JsonObject.str(k: String) = (this[k] as? JsonPrimitive)?.contentOrNull.orEmpty()
        private fun JsonObject.int(k: String) = (this[k] as? JsonPrimitive)?.intOrNull ?: 0
        private fun JsonObject.amount(k: String) = ((this[k] as? JsonObject)?.get("amount") as? JsonPrimitive)?.doubleOrNull

        /** A price is `{"display": …}` in the detail and already a string on list items. */
        fun priceDisplay(e: JsonElement?): String = when (e) {
            is JsonPrimitive -> if (e.isString) e.content else ""
            is JsonObject -> e.str("display")
            else -> ""
        }

        fun parse(e: JsonElement?): WebChange? {
            val o = e as? JsonObject ?: return null
            val at = o.str("at").ifBlank { null }
            return when (o.str("type")) {
                "posts" -> Posts(
                    o.int("count"),
                    (o["added"] as? JsonArray).orEmpty().mapNotNull { runCatching { KernJson.decodeFromJsonElement(WebPost.serializer(), it) }.getOrNull() },
                    at,
                )
                "price" -> {
                    val old = o.amount("old"); val new = o.amount("new")
                    Price(priceDisplay(o["old"]), priceDisplay(o["new"]), old != null && new != null && new < old, at)
                }
                "content" -> Content(
                    o.int("added"), o.int("removed"),
                    (o["snippets"] as? JsonArray).orEmpty().mapNotNull { (it as? JsonPrimitive)?.contentOrNull },
                    at,
                )
                else -> null
            }
        }
    }
}

/** Options the server accepts for `monitor_mode` and `monitor_interval` (minutes). */
val WATCH_MODES = listOf("auto" to "Automatic", "posts" to "New posts", "price" to "Price", "content" to "Any change")
val WATCH_INTERVALS = listOf(60 to "Hourly", 180 to "3 hours", 360 to "6 hours", 720 to "Twice a day", 1440 to "Daily", 4320 to "3 days", 10080 to "Weekly")

@Serializable
data class LibraryFile(
    val id: String,
    val url: String,
    val name: String = "",
    val mime: String = "",
    val size: Long = 0,
    @SerialName("created_at") val createdAt: String? = null,
)

@Serializable
data class CommitInfo(val sha: String = "", val date: String? = null, val subject: String = "", val author: String = "")

@Serializable
data class Repo(
    val name: String,
    val description: String = "",
    val size: Long = 0,
    val empty: Boolean = false,
    @SerialName("default_branch") val defaultBranch: String? = null,
    val branches: Int = 0,
    @SerialName("last_push") val lastPush: String? = null,
    @SerialName("last_commit") val lastCommit: CommitInfo? = null,
)

@Serializable
data class TreeEntry(val name: String, val path: String, val type: String, val size: Long? = null)

@Serializable
data class Readme(val name: String = "", val path: String = "", val text: String = "")

@Serializable
data class RepoTree(
    val sha: String? = null,
    val path: String? = null,
    val entries: List<TreeEntry> = emptyList(),
    val readme: Readme? = null,
    @SerialName("last_commit") val lastCommit: CommitInfo? = null,
)

@Serializable
data class Blob(val path: String = "", val size: Long = 0, val binary: Boolean = false, val truncated: Boolean = false, val text: String? = null)

@Serializable
data class Commit(
    val sha: String = "",
    val subject: String = "",
    val author: String = "",
    val date: String? = null,
    @SerialName("author_date") val authorDate: String? = null,
)

@Serializable
data class Uploaded(val id: String, val url: String, val name: String = "", val mime: String = "", val size: Long = 0)

@Serializable
data class CardPage(val total: Int = 0, val cards: List<Card> = emptyList())

@Serializable
data class StorageCounts(
    val pages: Int = 0, val entries: Int = 0, val databases: Int = 0, val blocks: Int = 0,
    val cards: Int = 0, val tasks: Int = 0, val files: Int = 0, val versions: Int = 0, val trashed: Int = 0,
)

@Serializable
data class Storage(
    @SerialName("database_bytes") val databaseBytes: Long = 0,
    @SerialName("media_bytes") val mediaBytes: Long = 0,
    @SerialName("downloads_bytes") val downloadsBytes: Long = 0,
    @SerialName("git_bytes") val gitBytes: Long = 0,
    @SerialName("backups_bytes") val backupsBytes: Long = 0,
    val counts: StorageCounts = StorageCounts(),
)
