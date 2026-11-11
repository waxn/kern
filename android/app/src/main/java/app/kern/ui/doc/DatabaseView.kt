package app.kern.ui.doc

import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.ExperimentalFoundationApi
import androidx.compose.foundation.horizontalScroll
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.ExperimentalLayoutApi
import androidx.compose.foundation.layout.FlowRow
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.aspectRatio
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.rememberScrollState
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowLeft
import androidx.compose.material.icons.automirrored.outlined.KeyboardArrowRight
import androidx.compose.material.icons.outlined.Add
import androidx.compose.material3.DropdownMenu
import androidx.compose.material3.DropdownMenuItem
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
import androidx.compose.runtime.saveable.rememberSaveable
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.layout.ContentScale
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import app.kern.data.DbPayload
import app.kern.data.DbRow
import app.kern.data.DbView
import app.kern.data.PropDef
import app.kern.ui.Nav
import app.kern.ui.Workspace
import app.kern.ui.components.DocIcon
import app.kern.ui.components.LocalSnack
import app.kern.ui.components.Loading
import app.kern.ui.components.Pill
import app.kern.ui.theme.kern
import coil.compose.AsyncImage
import kotlinx.coroutines.launch
import kotlinx.serialization.json.JsonArray
import kotlinx.serialization.json.JsonElement
import kotlinx.serialization.json.JsonObject
import kotlinx.serialization.json.JsonPrimitive
import kotlinx.serialization.json.booleanOrNull
import kotlinx.serialization.json.contentOrNull
import kotlinx.serialization.json.doubleOrNull
import kotlinx.serialization.json.jsonArray
import kotlinx.serialization.json.jsonObject
import kotlinx.serialization.json.jsonPrimitive
import java.time.LocalDate
import java.time.YearMonth
import java.time.format.TextStyle
import java.util.Locale

/** The web's view filters and sorts, applied to rows on the device. */
object DbQuery {
    private fun prim(e: JsonElement?): String? = runCatching { e?.jsonPrimitive?.contentOrNull }.getOrNull()
    private fun list(e: JsonElement?): List<String> = runCatching { e!!.jsonArray.map { it.jsonPrimitive.content } }.getOrDefault(emptyList())

    fun raw(row: DbRow, def: PropDef?): JsonElement? = if (def == null) JsonPrimitive(row.title) else row.values[def.id]

    fun plain(row: DbRow, def: PropDef?, titles: (String) -> String): Any? {
        if (def == null) return row.title
        val v = row.values[def.id] ?: return null
        if (v is JsonPrimitive && v.contentOrNull.isNullOrEmpty()) return null
        return when (def.type) {
            "select", "status" -> def.options.firstOrNull { it.id == prim(v) }?.name
            "multi_select" -> list(v).mapNotNull { id -> def.options.firstOrNull { it.id == id }?.name }
            "relation" -> list(v).map(titles)
            "formula" -> if (v is JsonObject && v.containsKey("error")) null else (v as? JsonPrimitive)?.let { it.doubleOrNull ?: it.booleanOrNull ?: it.contentOrNull }
            "number", "rating" -> (v as? JsonPrimitive)?.doubleOrNull
            "boolean" -> (v as? JsonPrimitive)?.booleanOrNull
            else -> if (v is JsonArray) list(v) else prim(v)
        }
    }

    private fun empty(v: Any?) = v == null || v == "" || (v is List<*> && v.isEmpty()) || v == false
    private fun today(o: Long = 0) = LocalDate.now().plusDays(o).toString()

    fun match(row: DbRow, group: JsonObject, defs: Map<String, PropDef>, titles: (String) -> String): Boolean {
        val rules = runCatching { group["rules"]!!.jsonArray }.getOrNull() ?: return true
        if (rules.isEmpty()) return true
        val or = prim(group["op"]) == "or"
        val test = { r: JsonElement ->
            val o = r.jsonObject
            if (o.containsKey("rules")) match(row, o, defs, titles) else rule(row, o, defs, titles)
        }
        return if (or) rules.any(test) else rules.all(test)
    }

    private fun rule(row: DbRow, r: JsonObject, defs: Map<String, PropDef>, titles: (String) -> String): Boolean {
        val propId = prim(r["prop"]) ?: return true
        val def = defs[propId]
        if (def == null && propId != "title") return true
        val t = def?.type ?: "title"
        val raw = raw(row, def)
        val v = plain(row, def, titles)
        val op = prim(r["op"]) ?: return true
        if (op == "empty") return empty(if (t == "boolean") null else v)
        if (op == "not_empty") return !empty(if (t == "boolean") null else v)
        val wantEl = r["value"]
        val want = if (wantEl is JsonArray) list(wantEl) else prim(wantEl)
        if ((want == null || want == "") && t != "boolean") return true
        when (t) {
            "boolean" -> return (prim(raw) == "true") == (want == "true")
            "select", "status" -> {
                val ids = if (want is List<*>) want else listOf(want)
                return if (op == "is_not") prim(raw) !in ids else prim(raw) in ids
            }
            "multi_select", "relation" -> {
                val l = list(raw)
                val ids = if (want is List<*>) want else listOf(want)
                val hit = ids.any { it in l }
                return if (op == "not_contains") !hit else hit
            }
            "date", "created_time", "last_edited_time" -> {
                val d = prim(raw)?.take(10) ?: return false
                val w = when (want) { "today" -> today(); "tomorrow" -> today(1); "yesterday" -> today(-1); else -> want.toString() }
                return when (op) {
                    "is" -> d == w; "before" -> d < w; "after" -> d > w; "on_or_before" -> d <= w; "on_or_after" -> d >= w
                    "past_week" -> d >= today(-7) && d <= today(); "next_week" -> d >= today() && d <= today(7)
                    else -> true
                }
            }
        }
        if (v is Double && op in setOf("=", "!=", ">", "<", ">=", "<=")) {
            val b = want.toString().toDoubleOrNull() ?: return false
            return when (op) { "=" -> v == b; "!=" -> v != b; ">" -> v > b; "<" -> v < b; ">=" -> v >= b; else -> v <= b }
        }
        val s = (if (v is List<*>) v.joinToString(", ") else v?.toString() ?: "").lowercase()
        val w = want.toString().lowercase()
        return when (op) {
            "contains" -> s.contains(w); "not_contains" -> !s.contains(w); "is" -> s == w; "is_not" -> s != w
            "starts_with" -> s.startsWith(w); "ends_with" -> s.endsWith(w); else -> true
        }
    }

    fun apply(p: DbPayload, view: DbView, titles: (String) -> String): List<DbRow> {
        val defs = p.properties.associateBy { it.id }
        var rows = p.rows
        view.config["filter"]?.let { f -> (f as? JsonObject)?.let { g -> rows = rows.filter { match(it, g, defs, titles) } } }
        val sorts = runCatching { view.config["sorts"]!!.jsonArray.map { it.jsonObject } }.getOrDefault(emptyList())
        if (sorts.isNotEmpty()) {
            rows = rows.sortedWith { a, b ->
                for (s in sorts) {
                    val id = prim(s["prop"]) ?: continue
                    val def = defs[id]
                    val x = plain(a, def, titles); val y = plain(b, def, titles)
                    val c = compare(x, y)
                    if (c != 0) return@sortedWith if (prim(s["dir"]) == "desc") -c else c
                }
                0
            }
        }
        return rows
    }

    private fun compare(x: Any?, y: Any?): Int {
        if (x == null && y == null) return 0
        if (x == null) return 1
        if (y == null) return -1
        if (x is Double && y is Double) return x.compareTo(y)
        if (x is Boolean && y is Boolean) return x.compareTo(y)
        val sx = if (x is List<*>) x.joinToString() else x.toString()
        val sy = if (y is List<*>) y.joinToString() else y.toString()
        return sx.lowercase().compareTo(sy.lowercase())
    }

    fun str(view: DbView, key: String) = prim(view.config[key])
    fun visible(p: DbPayload, view: DbView): List<PropDef> {
        val vis = runCatching { view.config["visible"]!!.jsonArray.map { it.jsonPrimitive.content } }.getOrNull()
        val hidden = runCatching { view.config["hidden"]!!.jsonArray.map { it.jsonPrimitive.content } }.getOrDefault(emptyList())
        return if (vis != null) vis.mapNotNull { id -> p.properties.firstOrNull { it.id == id } } else p.properties.filter { it.id !in hidden }
    }
}

@Composable
fun DatabaseView(ws: Workspace, nav: Nav, dbId: String) {
    var data by remember(dbId) { mutableStateOf<DbPayload?>(null) }
    var err by remember { mutableStateOf<String?>(null) }
    var viewId by rememberSaveable(dbId) { mutableStateOf<String?>(null) }
    val scope = rememberCoroutineScope()
    val snack = LocalSnack.current
    suspend fun load() { try { data = ws.kern.database(dbId); err = null } catch (e: Exception) { err = e.message } }
    LaunchedEffect(dbId) { load() }
    val p = data
    if (p == null) { if (err != null) Text(err!!, color = kern.danger, modifier = Modifier.padding(20.dp)) else Loading(Modifier.height(120.dp)); return }
    val views = p.views.sortedBy { it.position }.ifEmpty { listOf(DbView("default", "Table", "table")) }
    val view = views.firstOrNull { it.id == viewId } ?: views.first()
    val titles: (String) -> String = { id -> ws.doc(id)?.displayTitle ?: "Untitled" }
    val rows = remember(p, view) { DbQuery.apply(p, view, titles) }

    fun add(values: Map<String, Any?> = emptyMap()) = scope.launch {
        runCatching { ws.kern.createEntry(dbId, "", values) }.onSuccess { nav.doc(it.id) }.onFailure { snack.error(it) }
    }
    fun setValue(row: DbRow, prop: String, value: Any?) = scope.launch {
        runCatching { ws.kern.setProperty(row.id, prop, value) }.onSuccess { load() }.onFailure { snack.error(it) }
    }

    Column(Modifier.fillMaxWidth()) {
        Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically) {
            views.forEach { v ->
                val on = v.id == view.id
                Text(
                    v.name.ifBlank { v.type.replaceFirstChar { it.uppercase() } },
                    style = MaterialTheme.typography.labelLarge, color = if (on) kern.text else kern.text3,
                    fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                    modifier = Modifier.clip(RoundedCornerShape(8.dp)).background(if (on) kern.active else androidx.compose.ui.graphics.Color.Transparent)
                        .clickable { viewId = v.id }.padding(horizontal = 12.dp, vertical = 7.dp),
                )
            }
            Spacer(Modifier.width(8.dp))
            Text("${rows.size} ${if (rows.size == 1) "entry" else "entries"}", style = MaterialTheme.typography.bodySmall, color = kern.text3)
            Spacer(Modifier.width(8.dp))
            IconButton(onClick = { add() }) { Icon(Icons.Outlined.Add, "New entry", tint = kern.accent) }
        }
        Spacer(Modifier.height(8.dp))
        when (view.type) {
            "board" -> Board(p, view, rows, nav, ::setValue) { add(it) }
            "calendar" -> Calendar(p, view, rows, nav) { day -> DbQuery.str(view, "date_prop")?.let { add(mapOf(it to day)) } ?: add() }
            "gallery" -> Gallery(ws, p, view, rows, nav)
            else -> RowList(p, view, rows, nav, ws)
        }
    }
}

@OptIn(ExperimentalLayoutApi::class)
@Composable
private fun RowList(p: DbPayload, view: DbView, rows: List<DbRow>, nav: Nav, ws: Workspace) {
    val props = DbQuery.visible(p, view).take(4)
    val refs = remember(ws.tree.value) { ws.tree.value.associate { "doc:${it.id}" to app.kern.data.RefInfo(it.title, it.icon) } }
    Column(Modifier.padding(horizontal = 16.dp).fillMaxWidth().clip(RoundedCornerShape(12.dp)).border(1.dp, kern.border, RoundedCornerShape(12.dp))) {
        if (rows.isEmpty()) Text("No entries", color = kern.text3, modifier = Modifier.padding(14.dp))
        rows.forEachIndexed { i, r ->
            if (i > 0) app.kern.ui.components.Divider()
            Column(Modifier.fillMaxWidth().clickable { nav.doc(r.id) }.padding(horizontal = 12.dp, vertical = 10.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically) {
                    DocIcon(r.icon, size = 15.dp)
                    Spacer(Modifier.width(6.dp))
                    Text(r.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.bodyLarge, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
                }
                val shown = props.filter { d -> r.values[d.id]?.let { !(it is JsonPrimitive && it.contentOrNull.isNullOrEmpty()) && !(it is JsonArray && it.isEmpty()) } == true }
                if (shown.isNotEmpty()) FlowRow(Modifier.padding(top = 4.dp, start = 26.dp), horizontalArrangement = Arrangement.spacedBy(10.dp), verticalArrangement = Arrangement.spacedBy(4.dp)) {
                    shown.forEach { d -> PropertyValue(d, r.values[d.id], refs, nav, null) }
                }
            }
        }
    }
}

@OptIn(ExperimentalFoundationApi::class)
@Composable
private fun Board(p: DbPayload, view: DbView, rows: List<DbRow>, nav: Nav, setValue: (DbRow, String, Any?) -> Unit, add: (Map<String, Any?>) -> Unit) {
    val groupBy = DbQuery.str(view, "group_by")?.let { id -> p.properties.firstOrNull { it.id == id } }
        ?: p.properties.firstOrNull { it.type == "status" || it.type == "select" }
    if (groupBy == null) { Text("Pick a select or status property to group by in the web app.", color = kern.text3, modifier = Modifier.padding(20.dp)); return }
    val groups = listOf<Pair<String?, String>>(null to "No ${groupBy.name}") + groupBy.options.map { it.id to it.name }
    val hideEmpty = DbQuery.str(view, "hide_empty_groups") == "true"
    var moving by remember { mutableStateOf<DbRow?>(null) }
    Row(Modifier.fillMaxWidth().horizontalScroll(rememberScrollState()).padding(horizontal = 12.dp)) {
        for ((gid, name) in groups) {
            val items = rows.filter { (runCatching { it.values[groupBy.id]?.jsonPrimitive?.contentOrNull }.getOrNull()) == gid }
            if (items.isEmpty() && (gid == null || hideEmpty)) continue
            val opt = groupBy.options.firstOrNull { it.id == gid }
            val color = kern.named(opt?.color?.ifBlank { "gray" } ?: "gray")
            Column(Modifier.width(260.dp).padding(horizontal = 4.dp).clip(RoundedCornerShape(12.dp)).background(kern.side).padding(8.dp)) {
                Row(verticalAlignment = Alignment.CenterVertically, modifier = Modifier.padding(4.dp)) {
                    if (opt != null) Pill(name, color) else Text(name, style = MaterialTheme.typography.labelLarge, color = kern.text3)
                    Spacer(Modifier.width(6.dp))
                    Text("${items.size}", style = MaterialTheme.typography.labelMedium, color = kern.text3, modifier = Modifier.weight(1f))
                    Icon(Icons.Outlined.Add, "Add", tint = kern.text3, modifier = Modifier.size(20.dp).clickable { add(if (gid != null) mapOf(groupBy.id to gid) else emptyMap()) })
                }
                items.forEach { r ->
                    Box {
                        Column(
                            Modifier.padding(vertical = 4.dp).fillMaxWidth().clip(RoundedCornerShape(10.dp)).background(kern.surface).border(1.dp, kern.border, RoundedCornerShape(10.dp))
                                .combinedClickable(onClick = { nav.doc(r.id) }, onLongClick = { moving = r }).padding(12.dp)
                        ) {
                            Row(verticalAlignment = Alignment.CenterVertically) {
                                if (r.icon.isNotBlank()) { Text(r.icon); Spacer(Modifier.width(6.dp)) }
                                Text(r.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium)
                            }
                        }
                        DropdownMenu(moving?.id == r.id, { moving = null }, containerColor = kern.surface) {
                            Text("Move to", style = MaterialTheme.typography.labelSmall, color = kern.text3, modifier = Modifier.padding(horizontal = 12.dp, vertical = 4.dp))
                            groupBy.options.forEach { o ->
                                DropdownMenuItem(text = { Pill(o.name, kern.named(o.color.ifBlank { "gray" })) }, onClick = { moving = null; setValue(r, groupBy.id, o.id) })
                            }
                        }
                    }
                }
            }
        }
    }
    Text("Long-press a card to move it to another column.", style = MaterialTheme.typography.bodySmall, color = kern.text3, modifier = Modifier.padding(horizontal = 20.dp, vertical = 8.dp))
}

@Composable
private fun Calendar(p: DbPayload, view: DbView, rows: List<DbRow>, nav: Nav, add: (String) -> Unit) {
    val dateProp = DbQuery.str(view, "date_prop")?.let { id -> p.properties.firstOrNull { it.id == id } } ?: p.properties.firstOrNull { it.type == "date" }
    var month by remember { mutableStateOf(YearMonth.now()) }
    var selected by remember { mutableStateOf(LocalDate.now()) }
    if (dateProp == null) { Text("This calendar needs a date property.", color = kern.text3, modifier = Modifier.padding(20.dp)); return }
    val byDay = rows.groupBy { runCatching { it.values[dateProp.id]?.jsonPrimitive?.contentOrNull?.take(10) }.getOrNull() ?: "" }
    val k = kern
    Column(Modifier.padding(horizontal = 16.dp)) {
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text("${month.month.getDisplayName(TextStyle.FULL, Locale.getDefault())} ${month.year}", style = MaterialTheme.typography.titleMedium, modifier = Modifier.weight(1f))
            IconButton(onClick = { month = month.minusMonths(1) }) { Icon(Icons.AutoMirrored.Outlined.KeyboardArrowLeft, "Previous month") }
            IconButton(onClick = { month = YearMonth.now(); selected = LocalDate.now() }) { Text("Today", color = k.accent, style = MaterialTheme.typography.labelMedium) }
            IconButton(onClick = { month = month.plusMonths(1) }) { Icon(Icons.AutoMirrored.Outlined.KeyboardArrowRight, "Next month") }
        }
        Row { listOf("M", "T", "W", "T", "F", "S", "S").forEach { Text(it, Modifier.weight(1f), textAlign = TextAlign.Center, style = MaterialTheme.typography.labelSmall, color = k.text3) } }
        val first = month.atDay(1)
        val lead = first.dayOfWeek.value - 1
        val days = month.lengthOfMonth()
        val cells = (0 until ((lead + days + 6) / 7) * 7).map { i -> if (i < lead || i >= lead + days) null else month.atDay(i - lead + 1) }
        cells.chunked(7).forEach { week ->
            Row {
                week.forEach { d ->
                    Box(Modifier.weight(1f).aspectRatio(1f).padding(2.dp).clip(RoundedCornerShape(8.dp))
                        .background(if (d == selected) k.tint(k.accent) else androidx.compose.ui.graphics.Color.Transparent)
                        .clickable(enabled = d != null) { if (d != null) selected = d },
                        contentAlignment = Alignment.Center) {
                        if (d != null) {
                            Column(horizontalAlignment = Alignment.CenterHorizontally) {
                                Text("${d.dayOfMonth}", style = MaterialTheme.typography.bodyMedium, color = if (d == LocalDate.now()) k.accent else k.text, fontWeight = if (d == LocalDate.now()) FontWeight.Bold else null)
                                val n = byDay[d.toString()]?.size ?: 0
                                Row(horizontalArrangement = Arrangement.spacedBy(2.dp)) { repeat(n.coerceAtMost(3)) { Box(Modifier.size(4.dp).clip(CircleShape).background(k.accent)) } }
                            }
                        }
                    }
                }
            }
        }
        Spacer(Modifier.height(8.dp))
        Row(verticalAlignment = Alignment.CenterVertically) {
            Text(app.kern.ui.components.dueLabel(selected.toString()), style = MaterialTheme.typography.titleSmall, modifier = Modifier.weight(1f))
            Text("+ Add", color = k.accent, style = MaterialTheme.typography.labelLarge, modifier = Modifier.clickable { add(selected.toString()) }.padding(8.dp))
        }
        val today = byDay[selected.toString()].orEmpty()
        if (today.isEmpty()) Text("Nothing on this day", color = k.text3, style = MaterialTheme.typography.bodyMedium, modifier = Modifier.padding(vertical = 6.dp))
        today.forEach { r ->
            Row(Modifier.fillMaxWidth().padding(vertical = 3.dp).clip(RoundedCornerShape(8.dp)).background(k.surface).clickable { nav.doc(r.id) }.padding(12.dp)) {
                if (r.icon.isNotBlank()) { Text(r.icon); Spacer(Modifier.width(6.dp)) }
                Text(r.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.bodyMedium)
            }
        }
    }
}

@Composable
private fun Gallery(ws: Workspace, p: DbPayload, view: DbView, rows: List<DbRow>, nav: Nav) {
    val cols = when (DbQuery.str(view, "card_size")) { "small" -> 3; "large" -> 1; else -> 2 }
    Column(Modifier.padding(horizontal = 12.dp)) {
        rows.chunked(cols).forEach { line ->
            Row {
                line.forEach { r ->
                    Column(Modifier.weight(1f).padding(4.dp).clip(RoundedCornerShape(12.dp)).background(kern.surface).border(1.dp, kern.border, RoundedCornerShape(12.dp)).clickable { nav.doc(r.id) }) {
                        Box(Modifier.fillMaxWidth().aspectRatio(1.6f).background(kern.surface2), contentAlignment = Alignment.Center) {
                            if (r.cover.isNotBlank() && DbQuery.str(view, "cover") != "none") AsyncImage(ws.kern.api.abs(r.cover), null, contentScale = ContentScale.Crop, modifier = Modifier.fillMaxWidth().aspectRatio(1.6f))
                            else Text(r.icon.ifBlank { "📄" }, style = MaterialTheme.typography.headlineMedium)
                        }
                        Text(r.title.ifBlank { "Untitled" }, style = MaterialTheme.typography.bodyMedium, fontWeight = FontWeight.Medium, maxLines = 2, overflow = TextOverflow.Ellipsis, modifier = Modifier.padding(10.dp))
                    }
                }
                repeat(cols - line.size) { Spacer(Modifier.weight(1f)) }
            }
        }
    }
}
