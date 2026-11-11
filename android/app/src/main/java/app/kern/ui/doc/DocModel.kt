package app.kern.ui.doc

import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateMapOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.setValue
import androidx.compose.ui.text.TextRange
import androidx.compose.ui.text.input.TextFieldValue
import androidx.lifecycle.ViewModel
import androidx.lifecycle.viewModelScope
import app.kern.data.ApiError
import app.kern.data.Block
import app.kern.data.DocPayload
import app.kern.data.Html
import app.kern.ui.Workspace
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import kotlinx.coroutines.sync.Mutex
import kotlinx.coroutines.sync.withLock
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.jsonPrimitive
import java.util.UUID

/** Zero-width sentinel at the start of every edit field, so a backspace at the very start can be seen. */
const val SENTINEL = "​"

val TEXT_TYPES = setOf("paragraph", "h1", "h2", "h3", "bullet", "numbered", "todo", "toggle", "quote", "callout", "code")
private val CONTINUING = setOf("bullet", "numbered", "todo", "toggle")

data class Row(val block: Block, val depth: Int, val number: Int)

class DocModel(private val ws: Workspace, val docId: String) : ViewModel() {
    var payload by mutableStateOf<DocPayload?>(null); private set
    var error by mutableStateOf<String?>(null); private set
    var status by mutableStateOf("") ; private set
    var title by mutableStateOf(""); private set
    var focused by mutableStateOf<String?>(null)
    /** Bumped to ask the focused field to (re)claim focus and apply [edits] selection. */
    var focusTick by mutableIntStateOf(0)
    var tick by mutableIntStateOf(0); private set

    val blocks = mutableStateMapOf<String, Block>()
    val edits = mutableStateMapOf<String, TextFieldValue>()
    private val refMaps = mutableMapOf<String, Html.RefMap>()
    private val dirty = mutableSetOf<String>()
    private val deleted = mutableSetOf<String>()
    private var version: String? = null
    private var saveJob: Job? = null
    private var titleJob: Job? = null
    private val mutex = Mutex()

    init { load() }

    fun load() = viewModelScope.launch {
        try {
            val p = ws.kern.doc(docId)
            payload = p
            title = p.document.title
            version = p.version
            blocks.clear(); edits.clear(); refMaps.clear(); dirty.clear(); deleted.clear()
            p.blocks.forEach { blocks[it.id] = it }
            if (p.blocks.isEmpty() && p.document.database == null) {
                val b = Block(UUID.randomUUID().toString(), null, 1.0, "paragraph", "")
                blocks[b.id] = b
                // Not saved until typed into, like the web editor.
            }
            error = null
            tick++
        } catch (e: Exception) {
            error = e.message
        }
    }

    // ------------------------------------------------------------------ structure

    fun children(parent: String?): List<Block> = blocks.values.filter { it.parent == parent }.sortedBy { it.position }

    fun rows(): List<Row> {
        val out = mutableListOf<Row>()
        fun walk(parent: String?, depth: Int) {
            var n = 0
            for (b in children(parent)) {
                n = if (b.type == "numbered") n + 1 else 0
                out += Row(b, depth, n)
                if (!b.collapsed) walk(b.id, depth + 1)
            }
        }
        walk(null, 0)
        return out
    }

    private fun visibleOrder(): List<String> = rows().map { it.block.id }

    private fun positionAfter(b: Block): Double {
        val sibs = children(b.parent)
        val i = sibs.indexOfFirst { it.id == b.id }
        val next = sibs.getOrNull(i + 1)
        return if (next == null) b.position + 1 else (b.position + next.position) / 2
    }

    private fun lastChildPosition(parent: String): Double = (children(parent).lastOrNull()?.position ?: 0.0) + 1

    private fun put(b: Block) { blocks[b.id] = b; dirty += b.id; tick++; scheduleSave() }

    // ------------------------------------------------------------------ text

    fun markupOf(b: Block): String {
        edits[b.id]?.let { return it.text.removePrefix(SENTINEL) }
        val refs = refMaps.getOrPut(b.id) { Html.RefMap() }
        return if (b.type == "code") Html.decode(b.html) else Html.toMarkup(b.html, refs)
    }

    /** Displayed HTML, including edits not saved yet. */
    fun htmlOf(b: Block): String {
        val e = edits[b.id] ?: return b.html
        return toHtml(b, e.text.removePrefix(SENTINEL))
    }

    private fun toHtml(b: Block, markup: String): String =
        if (b.type == "code") Html.esc(markup) else Html.fromMarkup(markup, refMaps.getOrPut(b.id) { Html.RefMap() })

    fun startEditing(id: String, cursor: Int? = null) {
        val b = blocks[id] ?: return
        if (b.type !in TEXT_TYPES) { focused = id; return }
        val text = markupOf(b)
        val c = (cursor ?: text.length).coerceIn(0, text.length)
        edits[id] = TextFieldValue(SENTINEL + text, TextRange(c + 1))
        focused = id
        focusTick++
    }

    fun stopEditing() {
        focused?.let { commitEdit(it) }
        focused = null
    }

    private fun commitEdit(id: String) {
        val e = edits[id] ?: return
        val b = blocks[id] ?: return
        val html = toHtml(b, e.text.removePrefix(SENTINEL))
        if (html != b.html) put(b.copy(html = html))
        // Keep the edit until it is saved (so refs resolve); drop it when not focused.
        if (focused != id) edits.remove(id)
    }

    fun onEdit(id: String, value: TextFieldValue) {
        // A field that just lost focus (after Enter split it) can still send a late update; ignore it.
        if (focused != id) return
        val b = blocks[id] ?: return
        var v = value
        if (!v.text.startsWith(SENTINEL)) {
            // The sentinel was deleted: backspace at the very start.
            backspaceAtStart(id, v.text)
            return
        }
        if (v.selection.start < 1 || v.selection.end < 1) v = v.copy(selection = TextRange(v.selection.start.coerceAtLeast(1), v.selection.end.coerceAtLeast(1)))
        val body = v.text.removePrefix(SENTINEL)

        // Markdown shortcuts at the start of a plain paragraph.
        if (b.type == "paragraph") {
            val shortcuts = listOf("- " to "bullet", "* " to "bullet", "1. " to "numbered", "[] " to "todo", "[ ] " to "todo",
                "# " to "h1", "## " to "h2", "### " to "h3", "> " to "quote", "\" " to "quote", "```" to "code")
            for ((prefix, type) in shortcuts) {
                if (body.startsWith(prefix) && !markupOf(b).startsWith(prefix)) {
                    val rest = body.removePrefix(prefix)
                    val props = if (type == "todo") JsonObject(b.props + ("checked" to JsonPrimitive(false))) else b.props
                    blocks[id] = b.copy(type = type, props = props); dirty += id; tick++
                    edits[id] = TextFieldValue(SENTINEL + rest, TextRange(1))
                    scheduleSave(); return
                }
            }
            if (body == "---") {
                blocks[id] = b.copy(type = "divider", html = ""); dirty += id; edits.remove(id)
                insertAfter(id, "paragraph"); return
            }
        }

        // Enter splits the block (code blocks keep their newlines).
        if (b.type != "code" && body.contains('\n')) {
            val nl = body.indexOf('\n')
            val before = body.substring(0, nl)
            val after = body.substring(nl + 1)
            enter(id, before, after)
            return
        }
        edits[id] = v
        dirty += id
        scheduleSave()
    }

    private fun enter(id: String, before: String, after: String) {
        val b = blocks[id] ?: return
        // Enter on an empty list item ends the list.
        if (before.isEmpty() && after.isEmpty() && b.type in CONTINUING) {
            if (b.parent != null) { outdent(id); return }
            blocks[id] = b.copy(type = "paragraph"); dirty += id; tick++; scheduleSave()
            edits[id] = TextFieldValue(SENTINEL, TextRange(1)); focusTick++
            return
        }
        edits[id] = TextFieldValue(SENTINEL + before, TextRange(before.length + 1))
        commitEditForce(id)
        val type = if (b.type in CONTINUING) b.type else "paragraph"
        val props = if (type == "todo") JsonObject(mapOf("checked" to JsonPrimitive(false))) else JsonObject(emptyMap())
        // A block with visible children gets its new sibling as the first child instead.
        val kids = children(id)
        val nb = if (kids.isNotEmpty() && !b.collapsed)
            Block(UUID.randomUUID().toString(), id, (kids.first().position) - 1, type, "", props)
        else Block(UUID.randomUUID().toString(), b.parent, positionAfter(b), type, "", props)
        put(nb)
        edits[nb.id] = TextFieldValue(SENTINEL + after, TextRange(1))
        edits.remove(id).also { if (it != null) commitHtml(id, it) }
        focused = nb.id
        focusTick++
    }

    private fun commitEditForce(id: String) {
        val e = edits[id] ?: return
        commitHtml(id, e)
    }

    private fun commitHtml(id: String, e: TextFieldValue) {
        val b = blocks[id] ?: return
        val html = toHtml(b, e.text.removePrefix(SENTINEL))
        if (html != b.html) put(b.copy(html = html))
    }

    private fun backspaceAtStart(id: String, text: String) {
        val b = blocks[id] ?: return
        val body = text.removePrefix(SENTINEL)
        if (b.type != "paragraph" && b.type != "code") {
            // First backspace turns a heading or list item back into text.
            blocks[id] = b.copy(type = "paragraph"); dirty += id; tick++; scheduleSave()
            edits[id] = TextFieldValue(SENTINEL + body, TextRange(1)); focusTick++
            return
        }
        if (b.parent != null && children(b.parent).lastOrNull()?.id == b.id && body.isEmpty()) { outdent(id); return }
        val order = visibleOrder()
        val i = order.indexOf(id)
        val prevId = order.getOrNull(i - 1)
        val prev = prevId?.let { blocks[it] }
        if (prev == null) { edits[id] = TextFieldValue(SENTINEL + body, TextRange(1)); focusTick++; return }
        if (prev.type !in TEXT_TYPES) {
            if (body.isEmpty()) { removeBlock(id); focused = null } else { edits[id] = TextFieldValue(SENTINEL + body, TextRange(1)); focusTick++ }
            return
        }
        val prevText = markupOf(prev)
        // Merge into the previous block; its refs map gets this block's refs too.
        refMaps.getOrPut(prev.id) { Html.RefMap() }.byToken.putAll(refMaps[id]?.byToken ?: emptyMap())
        // Children move to the previous block.
        for (c in children(id)) put(c.copy(parent = prev.id, position = lastChildPosition(prev.id)))
        removeBlock(id)
        edits[prev.id] = TextFieldValue(SENTINEL + prevText + body, TextRange(prevText.length + 1))
        dirty += prev.id
        focused = prev.id
        focusTick++
        scheduleSave()
    }

    private fun removeBlock(id: String) {
        val all = mutableListOf(id)
        var i = 0
        while (i < all.size) { all += children(all[i]).map { it.id }; i++ }
        all.forEach { blocks.remove(it); edits.remove(it); dirty.remove(it) }
        deleted += id
        tick++
        scheduleSave()
    }

    // ------------------------------------------------------------------ block actions

    fun insertAfter(id: String?, type: String = "paragraph", props: JsonObject = JsonObject(emptyMap()), html: String = ""): String {
        val after = id?.let { blocks[it] }
        val nb = if (after != null) Block(UUID.randomUUID().toString(), after.parent, positionAfter(after), type, html, props)
        else Block(UUID.randomUUID().toString(), null, (children(null).lastOrNull()?.position ?: 0.0) + 1, type, html, props)
        put(nb)
        if (type in TEXT_TYPES) startEditing(nb.id, 0) else focused = null
        return nb.id
    }

    fun setType(id: String, type: String) {
        val b = blocks[id] ?: return
        val props = when (type) {
            "todo" -> JsonObject(b.props + ("checked" to (b.props["checked"] ?: JsonPrimitive(false))))
            "callout" -> JsonObject(b.props + ("icon" to (b.props["icon"] ?: JsonPrimitive("\uD83D\uDCA1"))))
            else -> b.props
        }
        val markup = markupOf(b)
        val html = when {
            type == "code" && b.type != "code" -> Html.esc(Html.text(toHtml(b, markup)))
            b.type == "code" && type != "code" -> Html.esc(markup).replace("\n", "<br>")
            else -> toHtml(b, markup)
        }
        val nb = b.copy(type = type, props = props, html = html)
        put(nb)
        if (edits.containsKey(id)) {
            val refs = refMaps.getOrPut(id) { Html.RefMap() }
            val text = if (type == "code") Html.decode(html) else Html.toMarkup(html, refs)
            edits[id] = TextFieldValue(SENTINEL + text, TextRange(text.length + 1))
            focusTick++
        }
    }

    fun setProps(id: String, vararg p: Pair<String, Any?>) {
        val b = blocks[id] ?: return
        val m = b.props.toMutableMap()
        for ((k, v) in p) if (v == null) m.remove(k) else m[k] = app.kern.data.toJson(v)
        put(b.copy(props = JsonObject(m)))
    }

    fun toggleCheck(id: String) {
        val b = blocks[id] ?: return
        setProps(id, "checked" to !(b.props.bool("checked") ?: false))
    }

    fun toggleCollapse(id: String) {
        val b = blocks[id] ?: return
        put(b.copy(collapsed = !b.collapsed))
    }

    fun indent(id: String) {
        val b = blocks[id] ?: return
        val sibs = children(b.parent)
        val i = sibs.indexOfFirst { it.id == id }
        val prev = sibs.getOrNull(i - 1) ?: return
        commitEditForce(id)
        put(blocks[id]!!.copy(parent = prev.id, position = lastChildPosition(prev.id)))
        if (prev.collapsed) put(prev.copy(collapsed = false))
        focusTick++
    }

    fun outdent(id: String) {
        val b = blocks[id] ?: return
        val parent = b.parent?.let { blocks[it] } ?: return
        commitEditForce(id)
        // Following siblings become this block's children, like most outliners.
        val sibs = children(parent.id)
        val i = sibs.indexOfFirst { it.id == id }
        var pos = lastChildPosition(id)
        for (s in sibs.drop(i + 1)) { put(s.copy(parent = id, position = pos)); pos += 1 }
        put(blocks[id]!!.copy(parent = parent.parent, position = positionAfter(parent)))
        focusTick++
    }

    fun move(id: String, delta: Int) {
        val b = blocks[id] ?: return
        val sibs = children(b.parent)
        val i = sibs.indexOfFirst { it.id == id }
        val j = i + delta
        if (j !in sibs.indices) return
        val other = sibs[j]
        commitEditForce(id)
        put(blocks[id]!!.copy(position = other.position))
        put(other.copy(position = b.position))
        focusTick++
    }

    fun delete(id: String) {
        val order = visibleOrder()
        val prev = order.getOrNull(order.indexOf(id) - 1)
        removeBlock(id)
        if (prev != null && blocks[prev]?.type in TEXT_TYPES) startEditing(prev) else focused = null
    }

    fun duplicate(id: String) {
        val b = blocks[id] ?: return
        commitEditForce(id)
        val src = blocks[id]!!
        fun copy(src: Block, parent: String?, pos: Double) {
            val nb = src.copy(id = UUID.randomUUID().toString(), parent = parent, position = pos)
            put(nb)
            children(src.id).forEach { copy(it, nb.id, it.position) }
        }
        copy(src, b.parent, positionAfter(b))
    }

    /** Wraps the selection of the focused field with [left] and [right] (or inserts them around the cursor). */
    fun wrap(left: String, right: String = left) {
        val id = focused ?: return
        val v = edits[id] ?: return
        val s = v.selection.min; val e = v.selection.max
        val t = v.text
        val nt = t.substring(0, s) + left + t.substring(s, e) + right + t.substring(e)
        val sel = if (s == e) TextRange(s + left.length) else TextRange(s + left.length, e + left.length)
        edits[id] = TextFieldValue(nt, sel)
        dirty += id; scheduleSave(); focusTick++
    }

    /** Inserts a ref token at the cursor of the focused field. */
    fun insertRef(kind: String, refId: String, label: String, color: String = "") {
        val id = focused ?: return
        val v = edits[id] ?: return
        val token = when (kind) { "tag" -> "#" + label.replace(" ", "-"); "block" -> "(($label))"; else -> "[[$label]]" }
        refMaps.getOrPut(id) { Html.RefMap() }.byToken[token] = Html.refHtml(kind, refId, label, color)
        val s = v.selection.min; val e = v.selection.max
        // Drop a "[[" or "#" the person already typed before picking.
        var start = s
        val before = v.text.substring(0, s)
        if (kind == "doc" && before.endsWith("[[")) start -= 2
        if (kind == "tag" && before.endsWith("#")) start -= 1
        val nt = v.text.substring(0, start) + token + " " + v.text.substring(e)
        edits[id] = TextFieldValue(nt, TextRange(start + token.length + 1))
        dirty += id; scheduleSave(); focusTick++
    }

    // ------------------------------------------------------------------ saving

    fun editTitle(t: String) {
        title = t
        titleJob?.cancel()
        titleJob = viewModelScope.launch {
            delay(600)
            runCatching { ws.patchLocal(ws.kern.updateDoc(docId, "title" to t)) }
                .onFailure { status = "Title not saved" }
        }
    }

    fun scheduleSave() {
        status = "Editing…"
        saveJob?.cancel()
        saveJob = viewModelScope.launch { delay(800); flush() }
    }

    /** Resolves `[[New page]]` and `#newtag` tokens to real pages and tags before saving. */
    private suspend fun resolveRefs(id: String, markup: String) {
        val refs = refMaps.getOrPut(id) { Html.RefMap() }
        val (pages, tags) = Html.unknownRefs(markup, refs)
        for (title in pages) {
            val existing = ws.tree.value.firstOrNull { it.title.equals(title, true) && it.trashedAt == null }
            val d = existing ?: runCatching { ws.newPage(title = title) }.getOrNull() ?: continue
            refs.byToken["[[$title]]"] = Html.refHtml("doc", d.id, d.title)
        }
        for (name in tags) {
            val t = runCatching { ws.ensureTag(name) }.getOrNull() ?: continue
            refs.byToken["#$name"] = Html.refHtml("tag", t.id, t.name, t.color)
        }
    }

    suspend fun flush(): Unit = mutex.withLock {
        if (dirty.isEmpty() && deleted.isEmpty()) { status = ""; return@withLock }
        status = "Saving…"
        val ids = dirty.toList(); dirty.clear()
        val dels = deleted.toList(); deleted.clear()
        for (id in ids) {
            val e = edits[id] ?: continue
            val b = blocks[id] ?: continue
            val markup = e.text.removePrefix(SENTINEL)
            if (b.type != "code") resolveRefs(id, markup)
            blocks[id] = b.copy(html = toHtml(b, markup))
            if (focused != id) edits.remove(id)
        }
        val ups = ids.mapNotNull { blocks[it] }
        try {
            val r = ws.kern.syncBlocks(docId, ups, dels, version)
            version = r.version ?: version
            for (p in r.patched) if (focused != p.id) blocks[p.id] = p else blocks[p.id]?.let { blocks[p.id] = it.copy(props = p.props, type = p.type) }
            status = "Saved"
            tick++
            ws.doc(docId)?.let { ws.patchLocal(it.copy(updatedAt = java.time.Instant.now().toString())) }
        } catch (e: ApiError) {
            if (e.status == 409) {
                status = "Changed elsewhere — reloaded"
                load()
            } else {
                dirty += ids; deleted += dels
                status = if (e.status == 0) "Offline — will retry" else "Not saved: ${e.message}"
                saveJob = viewModelScope.launch { delay(5000); flush() }
            }
        }
    }

    override fun onCleared() {
        // Last-chance save when leaving the page.
        stopEditing()
        if (dirty.isNotEmpty() || deleted.isNotEmpty()) {
            val ids = dirty.toList(); val dels = deleted.toList()
            for (id in ids) { val e = edits[id]; val b = blocks[id]; if (e != null && b != null) blocks[id] = b.copy(html = toHtml(b, e.text.removePrefix(SENTINEL))) }
            val ups = ids.mapNotNull { blocks[it] }
            kotlinx.coroutines.CoroutineScope(kotlinx.coroutines.Dispatchers.IO).launch {
                runCatching { ws.kern.syncBlocks(docId, ups, dels, null) }
            }
        }
        super.onCleared()
    }

    fun isEmptyDoc() = title.isBlank() && blocks.values.all { it.html.isBlank() && it.type == "paragraph" } && edits.values.all { it.text.removePrefix(SENTINEL).isBlank() }
}

fun JsonObject.bool(k: String): Boolean? = runCatching { this[k]?.jsonPrimitive?.booleanOrNull }.getOrNull()
fun JsonObject.string(k: String): String? = runCatching { this[k]?.jsonPrimitive?.contentOrNull }.getOrNull()
