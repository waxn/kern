package app.kern.data

/** A Markdown message split into text and the tables in it (GitHub-style pipe tables). */
sealed interface MdBlock {
    data class Text(val text: String) : MdBlock
    /** [align]: "", "center" or "right" per column; rows are padded to the header's width. */
    data class Table(val head: List<String>, val rows: List<List<String>>, val align: List<String>) : MdBlock
}

private val SEPARATOR = Regex("""^\s*\|?\s*:?-+:?\s*(\|\s*:?-+:?\s*)*\|?\s*$""")

/** Cells of a table row: split on | outside `code`; \| is a literal bar. */
fun tableCells(line: String): List<String> {
    var t = line.trim()
    if (t.startsWith("|")) t = t.drop(1)
    if (t.endsWith("|") && !t.endsWith("\\|")) t = t.dropLast(1)
    val cells = mutableListOf<String>()
    val cur = StringBuilder()
    var code = false
    var i = 0
    while (i < t.length) {
        val c = t[i]
        when {
            c == '\\' && i + 1 < t.length && t[i + 1] == '|' -> { cur.append('|'); i++ }
            c == '`' -> { code = !code; cur.append(c) }
            c == '|' && !code -> { cells += cur.toString().trim(); cur.clear() }
            else -> cur.append(c)
        }
        i++
    }
    cells += cur.toString().trim()
    return cells
}

fun markdownBlocks(text: String): List<MdBlock> {
    val lines = text.replace("\r", "").split("\n")
    val out = mutableListOf<MdBlock>()
    val buf = mutableListOf<String>()
    fun flush() { if (buf.isNotEmpty()) { out += MdBlock.Text(buf.joinToString("\n").trim('\n')); buf.clear() } }
    var inCode = false
    var i = 0
    while (i < lines.size) {
        val line = lines[i]
        if (line.trimStart().startsWith("```")) inCode = !inCode
        val tableStart = !inCode && line.contains('|') && i + 1 < lines.size && lines[i + 1].contains('-') &&
            SEPARATOR.matches(lines[i + 1]) && tableCells(line).size == tableCells(lines[i + 1]).size
        if (!tableStart) { buf += line; i++; continue }
        flush()
        val head = tableCells(line)
        val align = tableCells(lines[i + 1]).map { c ->
            when { c.startsWith(":") && c.endsWith(":") -> "center"; c.endsWith(":") -> "right"; else -> "" }
        }
        i += 2
        val rows = mutableListOf<List<String>>()
        while (i < lines.size && lines[i].isNotBlank() && lines[i].contains('|')) {
            val cells = tableCells(lines[i++])
            rows += head.indices.map { cells.getOrElse(it) { "" } }
        }
        out += MdBlock.Table(head, rows, head.indices.map { align.getOrElse(it) { "" } })
    }
    flush()
    return out.filter { it !is MdBlock.Text || it.text.isNotBlank() }
}
