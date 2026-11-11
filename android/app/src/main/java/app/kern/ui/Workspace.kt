package app.kern.ui

import android.app.Application
import androidx.lifecycle.AndroidViewModel
import androidx.lifecycle.viewModelScope
import app.kern.app
import app.kern.data.Doc
import app.kern.data.SiteInfo
import app.kern.data.Tag
import app.kern.data.User
import app.kern.notify.SyncWorker
import kotlinx.coroutines.flow.MutableStateFlow
import kotlinx.coroutines.flow.StateFlow
import kotlinx.coroutines.launch

sealed interface Session {
    data object Loading : Session
    data object SignedOut : Session
    data class SignedIn(val user: User) : Session
}

/** App-wide state: who is signed in, the page tree and tags. Screens read from it and ask it to refresh. */
class Workspace(application: Application) : AndroidViewModel(application) {
    private val a = application.app
    val kern = a.kern
    val settings = a.settings

    private val _session = MutableStateFlow<Session>(settings.user?.let { Session.SignedIn(it) } ?: Session.SignedOut)
    val session: StateFlow<Session> = _session

    private val _site = MutableStateFlow<SiteInfo?>(null)
    val site: StateFlow<SiteInfo?> = _site

    private val _tree = MutableStateFlow<List<Doc>>(emptyList())
    val tree: StateFlow<List<Doc>> = _tree
    private val _treeLoaded = MutableStateFlow(false)
    val treeLoaded: StateFlow<Boolean> = _treeLoaded
    private val _treeError = MutableStateFlow<String?>(null)
    val treeError: StateFlow<String?> = _treeError

    private val _tags = MutableStateFlow<List<Tag>>(emptyList())
    val tags: StateFlow<List<Tag>> = _tags

    init {
        viewModelScope.launch { a.api.signedOut.collect { onSignedOut() } }
        if (settings.user != null) {
            refresh()
            verify()
        }
    }

    private fun verify() = viewModelScope.launch {
        try {
            val s = kern.site()
            _site.value = s
            if (s.user == null) onSignedOut() else signedIn(s.user)
        } catch (_: Exception) { /* offline: keep the cached user */ }
    }

    fun signedIn(user: User) {
        settings.user = user
        _session.value = Session.SignedIn(user)
        SyncWorker.schedule(getApplication())
        refresh()
    }

    private fun onSignedOut() {
        if (_session.value is Session.SignedOut) return
        settings.clearAccount()
        _session.value = Session.SignedOut
        _tree.value = emptyList()
        _treeLoaded.value = false
    }

    fun logout() = viewModelScope.launch {
        kern.logout()
        SyncWorker.cancel(getApplication())
        onSignedOut()
        app.kern.widget.Widgets.updateAll(getApplication())
    }

    fun refresh() = viewModelScope.launch {
        try {
            _tree.value = kern.tree()
            _treeError.value = null
            _treeLoaded.value = true
        } catch (e: Exception) {
            _treeError.value = e.message
        }
        runCatching { _tags.value = kern.tags() }
        runCatching { _site.value = kern.site() }
    }

    fun refreshTags() = viewModelScope.launch { runCatching { _tags.value = kern.tags() } }

    fun doc(id: String): Doc? = _tree.value.firstOrNull { it.id == id }

    fun children(parent: String?): List<Doc> =
        _tree.value.filter { it.parent == parent && it.entryOf == null && !it.isArchived }.sortedBy { it.position }

    fun path(id: String): List<Doc> {
        val out = mutableListOf<Doc>()
        var cur = doc(id)?.parent
        val seen = mutableSetOf<String>()
        while (cur != null && seen.add(cur)) {
            val d = doc(cur) ?: break
            out.add(0, d)
            cur = d.parent
        }
        return out
    }

    fun patchLocal(doc: Doc) {
        _tree.value = _tree.value.map { if (it.id == doc.id) doc.copy(empty = false) else it }.let { list ->
            if (list.none { it.id == doc.id }) list + doc else list
        }
    }

    fun removeLocal(ids: Collection<String>) {
        val set = ids.toSet()
        _tree.value = _tree.value.filter { it.id !in set }
    }

    suspend fun newPage(parent: String? = null, title: String = "", template: String? = null, kind: String = "page"): Doc {
        val d = kern.createDoc(title = title, parent = parent, template = template, kind = kind)
        patchLocal(d)
        return d
    }

    suspend fun setFavorite(d: Doc, fav: Boolean) = patchLocal(kern.updateDoc(d.id, "is_favorite" to fav))
    suspend fun setArchived(d: Doc, archived: Boolean) = patchLocal(kern.updateDoc(d.id, "is_archived" to archived))
    suspend fun rename(d: Doc, title: String) = patchLocal(kern.updateDoc(d.id, "title" to title))
    suspend fun setIcon(d: Doc, icon: String) = patchLocal(kern.updateDoc(d.id, "icon" to icon))
    suspend fun duplicate(d: Doc): Doc { val n = kern.duplicateDoc(d.id); refresh(); return n }
    suspend fun trash(d: Doc) {
        val r = kern.trashDoc(d.id)
        removeLocal((r["trashed"] as? kotlinx.serialization.json.JsonArray)?.map { it.toString().trim('"') } ?: listOf(d.id))
    }
    suspend fun move(d: Doc, parent: String?) { kern.moveDoc(d.id, parent); refresh() }

    suspend fun ensureTag(name: String): Tag {
        _tags.value.firstOrNull { it.name.equals(name, true) }?.let { return it }
        val t = kern.createTag(name)
        _tags.value = _tags.value + t
        return t
    }
}
