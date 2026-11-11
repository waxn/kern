package app.kern.data

import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonNull
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.buildJsonArray
import kotlinx.serialization.json.buildJsonObject
import kotlinx.serialization.json.encodeToJsonElement
import kotlinx.serialization.json.put
import java.net.URLEncoder
import java.time.LocalDate
import java.util.TimeZone

private fun enc(s: String) = URLEncoder.encode(s, "UTF-8")

fun qs(vararg pairs: Pair<String, Any?>): String {
    val parts = pairs.filter { it.second != null && it.second.toString().isNotEmpty() }.map { "${it.first}=${enc(it.second.toString())}" }
    return if (parts.isEmpty()) "" else "?" + parts.joinToString("&")
}

/** Minutes behind UTC, the same sign as JavaScript's getTimezoneOffset(). */
fun tzo(): Int = -TimeZone.getDefault().getOffset(System.currentTimeMillis()) / 60000

fun today(): String = LocalDate.now().toString()

fun jsonOf(vararg pairs: Pair<String, Any?>): JsonObject = buildJsonObject {
    for ((k, v) in pairs) put(k, toJson(v))
}

fun toJson(v: Any?): JsonElement = when (v) {
    null -> JsonNull
    is JsonElement -> v
    is String -> JsonPrimitive(v)
    is Number -> JsonPrimitive(v)
    is Boolean -> JsonPrimitive(v)
    is List<*> -> buildJsonArray { v.forEach { add(toJson(it)) } }
    is Map<*, *> -> buildJsonObject { v.forEach { (k, x) -> put(k.toString(), toJson(x)) } }
    is Recurrence -> KernJson.encodeToJsonElement(v)
    else -> JsonPrimitive(v.toString())
}

/** Every endpoint the app uses, mirroring the web client. */
class Kern(val api: Api) {
    // ---- accounts
    suspend fun site(): SiteInfo = api.get("/site")
    suspend fun login(username: String, password: String): SiteInfo = api.post("/auth/login", jsonOf("username" to username, "password" to password))
    suspend fun signup(username: String, email: String, password: String): SiteInfo =
        api.post("/auth/signup", jsonOf("username" to username, "email" to email, "password" to password))
    suspend fun logout() { runCatching { api.raw("POST", "/auth/logout") }; api.cookieJar.clear() }
    suspend fun changePassword(current: String, new: String) { api.post<JsonObject>("/auth/password", jsonOf("current" to current, "new" to new)) }
    suspend fun updateEmail(email: String): User = api.patch("/auth/profile", jsonOf("email" to email))
    suspend fun adminUsers(): List<User> = api.get("/admin/users")
    suspend fun adminUpdate(id: Int, body: JsonObject): User = api.patch("/admin/users/$id", body)
    suspend fun adminCreate(username: String, password: String, admin: Boolean): User =
        api.post("/admin/users", jsonOf("username" to username, "password" to password, "is_admin" to admin))
    suspend fun adminDelete(id: Int) = api.delete("/admin/users/$id")

    // ---- documents
    suspend fun tree(): List<Doc> = api.get("/tree")
    suspend fun doc(id: String): DocPayload = api.get("/documents/$id")
    suspend fun createDoc(title: String = "", parent: String? = null, kind: String = "page", template: String? = null, id: String? = null): Doc =
        api.post("/documents", jsonOf("title" to title, "parent" to parent, "kind" to kind, "template" to template, "id" to id))
    suspend fun updateDoc(id: String, vararg fields: Pair<String, Any?>): Doc = api.patch("/documents/$id", jsonOf(*fields))
    suspend fun moveDoc(id: String, parent: String?, index: Int? = null): JsonObject = api.post("/documents/$id/move", jsonOf("parent" to parent, "index" to index))
    suspend fun duplicateDoc(id: String): Doc = api.post("/documents/$id/duplicate")
    suspend fun trashDoc(id: String): JsonObject = api.post("/documents/$id/trash")
    suspend fun restoreDoc(id: String): Doc = api.post("/documents/$id/restore")
    suspend fun deleteDoc(id: String) = api.delete("/documents/$id")
    suspend fun discardDoc(id: String) { runCatching { api.raw("POST", "/documents/$id/discard") } }
    suspend fun trash(): List<Doc> = api.get("/trash")
    suspend fun backlinks(id: String): List<BacklinkGroup> = api.get("/documents/$id/backlinks")
    suspend fun setProperty(doc: String, prop: String, value: Any?): JsonObject = api.put("/documents/$doc/properties/$prop", jsonOf("value" to value))

    suspend fun syncBlocks(doc: String, upserts: List<Block>, deletes: List<String>, base: String?): SyncResult =
        api.post("/documents/$doc/blocks/sync", buildJsonObject {
            put("upserts", JsonArray(upserts.map { KernJson.encodeToJsonElement(it) }))
            put("deletes", JsonArray(deletes.map { JsonPrimitive(it) }))
            if (base != null) put("base", base)
        })

    suspend fun search(q: String, kind: String? = null, limit: Int = 40): SearchResponse = api.get("/search" + qs("q" to q, "kind" to kind, "limit" to limit))
    suspend fun suggest(q: String, kinds: String = "doc,tag"): List<Suggestion> = api.get("/suggest" + qs("q" to q, "kinds" to kinds, "limit" to 12))

    // ---- tags
    suspend fun tags(): List<Tag> = api.get("/tags")
    suspend fun createTag(name: String): Tag = api.post("/tags", jsonOf("name" to name))
    suspend fun tag(id: String): JsonObject = api.get("/tags/$id")
    suspend fun deleteTag(id: String) = api.delete("/tags/$id")

    // ---- databases & templates
    suspend fun databases(): List<DbInfo> = api.get("/databases")
    suspend fun database(id: String): DbPayload = api.get("/databases/$id")
    suspend fun createDatabase(title: String, preset: String?): DbPayload = api.post("/databases", jsonOf("title" to title, "preset" to preset))
    suspend fun createEntry(db: String, title: String, values: Map<String, Any?> = emptyMap(), template: String? = null): Doc =
        api.post("/databases/$db/entries", jsonOf("title" to title, "values" to values, "template" to template))
    suspend fun templates(): List<Doc> = api.get("/templates")

    // ---- tasks
    suspend fun tasks(view: String, sort: String? = null, q: String? = null, project: String? = null, tag: String? = null): List<Task> =
        api.get("/tasks" + qs("view" to view, "today" to today(), "sort" to sort, "q" to q, "project" to project, "tag" to tag))
    suspend fun taskSummary(): TaskSummary = api.get("/tasks/summary" + qs("today" to today()))
    suspend fun createTask(title: String, due: String? = null, priority: Int = 0, tags: List<String> = emptyList(), recurrence: Recurrence? = null, project: String? = null, description: String = ""): Task =
        api.post("/tasks", jsonOf("title" to title, "due" to due, "priority" to priority, "tags" to tags, "recurrence" to recurrence, "project" to project, "description" to description))
    suspend fun updateTask(id: String, vararg fields: Pair<String, Any?>): Task = api.patch("/tasks/$id", jsonOf(*fields, "today" to today()))
    suspend fun deleteTask(id: String) = api.delete("/tasks/$id")

    // ---- flashcards
    suspend fun queue(deck: String? = null, doc: String? = null): CardQueue = api.get("/cards/queue" + qs("tzo" to tzo(), "deck" to deck, "doc" to doc))
    suspend fun review(card: String, rating: Int, ms: Long): Card = api.post("/cards/$card/review", jsonOf("rating" to rating, "duration_ms" to ms))
    suspend fun undoReview(): Card = api.post("/cards/undo")
    suspend fun cardStats(): CardStats = api.get("/cards/stats" + qs("tzo" to tzo()))
    suspend fun decks(): List<Deck> = api.get("/decks" + qs("tzo" to tzo()))
    suspend fun createNote(kind: String, front: String, back: String, deck: String?): JsonObject =
        api.post("/notes", jsonOf("kind" to kind, "front" to front, "back" to back, "deck" to deck))

    // ---- intelligence
    suspend fun chats(): List<Chat> = api.get("/chats")
    suspend fun chat(id: String): Chat = api.get("/chats/$id")
    suspend fun createChat(): Chat = api.post("/chats")
    suspend fun deleteChat(id: String) = api.delete("/chats/$id")
    suspend fun sendChat(id: String, text: String, page: String? = null): Chat = api.post("/chats/$id/message", jsonOf("text" to text, "page" to page))
    suspend fun aiConfig(): JsonObject = api.get("/ai/config")

    // ---- bookmarks
    suspend fun web(q: String? = null, kind: String? = null): List<WebItem> = api.get("/web/list" + qs("q" to q, "kind" to kind))
    suspend fun webItem(id: Long): WebItem = api.get("/web/$id")
    suspend fun addWeb(url: String, title: String = "", notes: String = ""): WebItem = api.post("/web/archive", jsonOf("url" to url, "title" to title, "notes" to notes))
    suspend fun updateWeb(id: Long, vararg fields: Pair<String, Any?>): WebItem = api.patch("/web/$id", jsonOf(*fields))
    suspend fun deleteWeb(id: Long) = api.delete("/web/$id")
    suspend fun refreshWeb(id: Long): WebItem = api.post("/web/$id/process")

    // ---- files & git
    suspend fun library(type: String? = null, q: String? = null): List<LibraryFile> = api.get("/library" + qs("type" to type, "q" to q, "usage" to "0"))
    suspend fun deleteFile(id: String) = api.delete("/library/$id")
    suspend fun repos(): List<Repo> = api.get("/git/repos")
    suspend fun repoTree(name: String, ref: String?, path: String): RepoTree = api.get("/git/repos/$name/tree" + qs("ref" to ref, "path" to path))
    suspend fun repoBlob(name: String, ref: String?, path: String): Blob = api.get("/git/repos/$name/blob" + qs("ref" to ref, "path" to path))
    suspend fun repoCommits(name: String, ref: String?): JsonObject = api.get("/git/repos/$name/commits" + qs("ref" to ref, "per" to 50))
    suspend fun createRepo(name: String, description: String): Repo = api.post("/git/repos", jsonOf("name" to name, "description" to description))

    // ---- misc
    suspend fun settings(): JsonObject = api.get("/settings")
    suspend fun storage(): JsonObject = api.get("/storage")
}
