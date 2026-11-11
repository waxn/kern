package app.kern.data

import kotlinx.serialization.SerialName
import kotlinx.serialization.Serializable
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject

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
)

@Serializable
data class SiteInfo(
    @SerialName("needs_setup") val needsSetup: Boolean = false,
    @SerialName("site_name") val siteName: String = "Kern",
    @SerialName("landing_enabled") val landingEnabled: Boolean = false,
    @SerialName("signup_mode") val signupMode: String = "closed",
    @SerialName("allow_git") val allowGit: Boolean = true,
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
    val position: Double = 0.0,
    @SerialName("created_at") val createdAt: String? = null,
)

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
)

@Serializable
data class WebTodo(val text: String, val done: Boolean = false)

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
