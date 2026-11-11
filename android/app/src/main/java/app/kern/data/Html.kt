package app.kern.data

import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.AnnotatedString
import androidx.compose.ui.text.LinkAnnotation
import androidx.compose.ui.text.SpanStyle
import androidx.compose.ui.text.TextLinkStyles
import androidx.compose.ui.text.buildAnnotatedString
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontStyle
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.BaselineShift
import androidx.compose.ui.text.style.TextDecoration
import androidx.compose.ui.unit.em

/** A tiny tolerant parser for the inline HTML Kern stores in blocks (the server sanitizes it to a short tag list). */
object Html {
    data class Node(val tag: String?, val attrs: Map<String, String> = emptyMap(), val text: String = "", val children: MutableList<Node> = mutableListOf())

    private val TAG = Regex("<(/?)([a-zA-Z0-9]+)([^>]*)>")
    private val ATTR = Regex("([a-zA-Z_:][-a-zA-Z0-9_:.]*)\\s*=\\s*(\"([^\"]*)\"|'([^']*)'|([^\\s>]+))")
    private val VOID = setOf("br", "img", "hr", "wbr")

    /** String-annotation tag for links when the caller does its own hit-testing ([annotate] with tagOnly). */
    const val LINK = "kern-link"

    fun decode(s: String): String {
        if (!s.contains('&')) return s
        return Regex("&(#x?[0-9a-fA-F]+|[a-zA-Z]+);").replace(s) { m ->
            val e = m.groupValues[1]
            when {
                e.startsWith("#x") || e.startsWith("#X") -> e.substring(2).toIntOrNull(16)?.let { String(Character.toChars(it)) } ?: m.value
                e.startsWith("#") -> e.substring(1).toIntOrNull()?.let { String(Character.toChars(it)) } ?: m.value
                else -> when (e) {
                    "amp" -> "&"; "lt" -> "<"; "gt" -> ">"; "quot" -> "\""; "apos", "#39" -> "'"; "nbsp" -> "\u00a0"
                    "hellip" -> "…"; "mdash" -> "—"; "ndash" -> "–"; "rsquo" -> "’"; "lsquo" -> "‘"; "rdquo" -> "”"; "ldquo" -> "“"
                    else -> m.value
                }
            }
        }
    }

    fun esc(s: String) = s.replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")
    fun escAttr(s: String) = esc(s).replace("\"", "&quot;")

    fun parse(html: String): Node {
        val root = Node(null)
        val stack = ArrayDeque<Node>().apply { add(root) }
        var i = 0
        for (m in TAG.findAll(html)) {
            if (m.range.first > i) stack.last().children.add(Node(null, text = decode(html.substring(i, m.range.first))))
            i = m.range.last + 1
            val closing = m.groupValues[1] == "/"
            val tag = m.groupValues[2].lowercase()
            if (closing) {
                val idx = stack.indexOfLast { it.tag == tag }
                if (idx > 0) while (stack.size > idx) stack.removeLast()
            } else {
                val attrs = ATTR.findAll(m.groupValues[3]).associate { a ->
                    a.groupValues[1].lowercase() to decode(a.groupValues[3].ifEmpty { a.groupValues[4].ifEmpty { a.groupValues[5] } })
                }
                val node = Node(tag, attrs)
                stack.last().children.add(node)
                if (tag !in VOID && !m.groupValues[3].trimEnd().endsWith("/")) stack.add(node)
            }
        }
        if (i < html.length) stack.last().children.add(Node(null, text = decode(html.substring(i))))
        return root
    }

    fun text(html: String?): String {
        if (html.isNullOrEmpty()) return ""
        val sb = StringBuilder()
        fun walk(n: Node) {
            if (n.tag == null && n.children.isEmpty()) sb.append(n.text)
            if (n.tag == "br") sb.append('\n')
            n.children.forEach(::walk)
        }
        walk(parse(html))
        return sb.toString().replace("\u200b", "")
    }

    fun oneLine(html: String?, limit: Int = 200): String {
        val t = text(html).replace(Regex("\\s+"), " ").trim()
        return if (t.length <= limit) t else t.take(limit - 1) + "…"
    }

    data class Palette(val accent: Color, val link: Color, val code: Color, val codeBg: Color, val mark: Color, val tagColor: (String) -> Color, val muted: Color)

    /**
     * Styled text for display. Refs (`data-ref="doc:…"`) and links become clickable; [onLink] gets
     * either `doc:<id>`, `block:<id>`, `tag:<id>` or a URL.
     */
    fun annotate(html: String, p: Palette, tagOnly: Boolean = false, onLink: ((String) -> Unit)? = null): AnnotatedString = buildAnnotatedString {
        fun walk(n: Node) {
            val start = length
            when (n.tag) {
                null -> {
                    if (n.children.isEmpty()) {
                        // Search highlights arrive as \u0001…\u0002.
                        if (n.text.contains('\u0001')) {
                            var hl = false
                            for (part in n.text.split(Regex("(?=[\u0001\u0002])|(?<=[\u0001\u0002])"))) {
                                when (part) {
                                    "\u0001" -> hl = true
                                    "\u0002" -> hl = false
                                    else -> if (hl) {
                                        val s = length; append(part)
                                        addStyle(SpanStyle(background = p.mark, fontWeight = FontWeight.SemiBold), s, length)
                                    } else append(part)
                                }
                            }
                        } else append(n.text.replace("\u200b", ""))
                    }
                    n.children.forEach(::walk)
                    return
                }
                "br" -> { append('\n'); return }
                "span" -> if (n.attrs["class"]?.contains("math") == true) {
                    append(n.attrs["data-math"] ?: "")
                    addStyle(SpanStyle(fontStyle = FontStyle.Italic, fontFamily = FontFamily.Serif), start, length)
                    return
                }
            }
            n.children.forEach(::walk)
            val end = length
            if (end <= start) return
            when (n.tag) {
                "b", "strong" -> addStyle(SpanStyle(fontWeight = FontWeight.SemiBold), start, end)
                "i", "em" -> addStyle(SpanStyle(fontStyle = FontStyle.Italic), start, end)
                "u" -> addStyle(SpanStyle(textDecoration = TextDecoration.Underline), start, end)
                "s", "strike", "del" -> addStyle(SpanStyle(textDecoration = TextDecoration.LineThrough), start, end)
                "code" -> addStyle(SpanStyle(fontFamily = FontFamily.Monospace, background = p.codeBg, color = p.code, fontSize = 0.88.em), start, end)
                "sub" -> addStyle(SpanStyle(baselineShift = BaselineShift.Subscript, fontSize = 0.8.em), start, end)
                "sup" -> addStyle(SpanStyle(baselineShift = BaselineShift.Superscript, fontSize = 0.8.em), start, end)
                "mark" -> addStyle(SpanStyle(background = p.mark), start, end)
                "span" -> when {
                    n.attrs["class"]?.contains("cloze") == true ->
                        addStyle(SpanStyle(color = p.accent, fontWeight = FontWeight.SemiBold, background = p.mark), start, end)
                    n.attrs["data-color"] != null -> addStyle(SpanStyle(color = p.tagColor(n.attrs["data-color"]!!)), start, end)
                }
                "a" -> {
                    val ref = n.attrs["data-ref"]
                    val cls = n.attrs["class"] ?: ""
                    val style = when {
                        ref != null && cls.contains("tag") -> SpanStyle(color = p.tagColor(n.attrs["data-c"] ?: ""), fontWeight = FontWeight.Medium)
                        ref != null -> SpanStyle(color = p.accent, fontWeight = FontWeight.Medium, textDecoration = TextDecoration.None)
                        else -> SpanStyle(color = p.link, textDecoration = TextDecoration.Underline)
                    }
                    val target = ref ?: n.attrs["href"]
                    if (target != null && tagOnly) {
                        addStyle(style, start, end)
                        addStringAnnotation(LINK, target, start, end)
                    } else if (target != null && onLink != null) {
                        addLink(LinkAnnotation.Clickable(target, TextLinkStyles(style)) { onLink(target) }, start, end)
                    } else addStyle(style, start, end)
                }
            }
        }
        walk(parse(html))
    }

    // ------------------------------------------------------------------ editable markup

    /** A ref the markup shows as `[[Title]]`, `((Block))` or `#tag`, mapped back to its original HTML. */
    class RefMap {
        val byToken = mutableMapOf<String, String>()
    }

    /**
     * Inline HTML → markup a person can edit in a plain text field:
     * `**bold**`, `*italic*`, `++underline++`, `~~strike~~`, `` `code` ``, `==highlight==`,
     * `[text](url)`, `[[Page]]`, `((block))`, `#tag`, `$tex$`.
     */
    fun toMarkup(html: String, refs: RefMap): String {
        fun render(n: Node): String {
            val inner = { n.children.joinToString("") { render(it) } }
            return when (n.tag) {
                null -> if (n.children.isEmpty()) n.text.replace("\u200b", "") else inner()
                "br" -> "\n"
                "b", "strong" -> "**${inner()}**"
                "i", "em" -> "*${inner()}*"
                "u" -> "++${inner()}++"
                "s", "strike", "del" -> "~~${inner()}~~"
                "code" -> "`${inner()}`"
                "mark" -> "==${inner()}=="
                "span" -> if (n.attrs["class"]?.contains("math") == true) "$" + (n.attrs["data-math"] ?: "") + "$" else inner()
                "a" -> {
                    val ref = n.attrs["data-ref"]
                    if (ref != null) {
                        val label = text(serialize(n.children))
                        val token = when {
                            ref.startsWith("tag:") -> "#" + label.removePrefix("#").replace(" ", "-")
                            ref.startsWith("block:") -> "(($label))"
                            else -> "[[$label]]"
                        }
                        refs.byToken[token] = serializeNode(n)
                        token
                    } else "[${inner()}](${n.attrs["href"] ?: ""})"
                }
                else -> inner()
            }
        }
        return render(parse(html))
    }

    private fun serialize(nodes: List<Node>): String = nodes.joinToString("") { serializeNode(it) }
    private fun serializeNode(n: Node): String {
        if (n.tag == null) return if (n.children.isEmpty()) esc(n.text) else serialize(n.children)
        val attrs = n.attrs.entries.joinToString("") { " ${it.key}=\"${escAttr(it.value)}\"" }
        if (n.tag == "br") return "<br>"
        return "<${n.tag}$attrs>${serialize(n.children)}</${n.tag}>"
    }

    private val INLINE = Regex(
        "\\*\\*(.+?)\\*\\*" +                       // 1 bold
            "|(?<![\\w*])\\*(?=\\S)(.+?)(?<=\\S)\\*(?!\\*)" + // 2 italic
            "|\\+\\+(.+?)\\+\\+" +                  // 3 underline
            "|~~(.+?)~~" +                           // 4 strike
            "|`([^`]+)`" +                           // 5 code
            "|==(.+?)==" +                           // 6 mark
            "|\\[\\[(.+?)]]" +                       // 7 page ref
            "|\\(\\((.+?)\\)\\)" +                   // 8 block ref
            "|\\[([^\\]]+)]\\(((?:https?|mailto|tel):[^)\\s]+)\\)" + // 9,10 link
            "|(?<![\\w&])#([\\p{L}\\d_-]+)" +         // 11 tag
            "|(?<![\\w$])\\$(?=\\S)([^$\\n]+?)(?<=\\S)\\$(?![\\w$])" + // 12 math
            "|\\n"
    )

    /** Tokens like `[[Title]]` or `#tag` the text uses but [refs] does not know yet. */
    fun unknownRefs(markup: String, refs: RefMap): Pair<Set<String>, Set<String>> {
        val pages = mutableSetOf<String>(); val tags = mutableSetOf<String>()
        for (m in INLINE.findAll(markup)) {
            if (m.groups[7] != null && "[[${m.groupValues[7]}]]" !in refs.byToken) pages += m.groupValues[7]
            if (m.groups[11] != null && "#${m.groupValues[11]}" !in refs.byToken) tags += m.groupValues[11]
        }
        return pages to tags
    }

    /** Markup → sanitized-compatible inline HTML. */
    fun fromMarkup(markup: String, refs: RefMap): String {
        val sb = StringBuilder()
        var i = 0
        for (m in INLINE.findAll(markup)) {
            sb.append(esc(markup.substring(i, m.range.first)))
            i = m.range.last + 1
            val g = m.groups
            when {
                m.value == "\n" -> sb.append("<br>")
                g[1] != null -> sb.append("<strong>").append(fromMarkup(g[1]!!.value, refs)).append("</strong>")
                g[2] != null -> sb.append("<em>").append(fromMarkup(g[2]!!.value, refs)).append("</em>")
                g[3] != null -> sb.append("<u>").append(fromMarkup(g[3]!!.value, refs)).append("</u>")
                g[4] != null -> sb.append("<s>").append(fromMarkup(g[4]!!.value, refs)).append("</s>")
                g[5] != null -> sb.append("<code>").append(esc(g[5]!!.value)).append("</code>")
                g[6] != null -> sb.append("<mark>").append(fromMarkup(g[6]!!.value, refs)).append("</mark>")
                g[7] != null || g[8] != null || g[11] != null -> sb.append(refs.byToken[m.value] ?: esc(m.value))
                g[9] != null -> sb.append("<a href=\"").append(escAttr(g[10]!!.value)).append("\">").append(fromMarkup(g[9]!!.value, refs)).append("</a>")
                g[12] != null -> {
                    val tex = g[12]!!.value
                    sb.append("<span class=\"math\" data-math=\"").append(escAttr(tex)).append("\" contenteditable=\"false\">").append(esc(tex)).append("</span>")
                }
            }
        }
        sb.append(esc(markup.substring(i)))
        return sb.toString()
    }

    fun refHtml(kind: String, id: String, title: String, color: String = ""): String {
        val cls = when (kind) { "tag" -> "ref tag"; "block" -> "ref blockref"; else -> "ref" }
        val text = if (kind == "tag") "#$title" else title.ifBlank { "Untitled" }
        val href = when (kind) { "tag" -> "/tag/$id"; else -> "/doc/$id" }
        val c = if (color.isNotEmpty()) " data-c=\"${escAttr(color)}\"" else ""
        return "<a class=\"$cls\" data-ref=\"$kind:$id\" href=\"${escAttr(href)}\" contenteditable=\"false\"$c>${esc(text)}</a>"
    }
}
