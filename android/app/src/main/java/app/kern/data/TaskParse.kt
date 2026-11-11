package app.kern.data

import java.time.LocalDate

/** Quick-add syntax, the same as the web: "Pay rent tomorrow !2 #home every month". */
data class ParsedTask(
    val title: String,
    val due: String?,
    val priority: Int,
    val tags: List<String>,
    val recurrence: Recurrence?,
    val tokens: List<String>,
)

object TaskParse {
    private val DAYS = listOf("sun", "mon", "tue", "wed", "thu", "fri", "sat")

    fun parse(input: String, now: LocalDate = LocalDate.now()): ParsedTask {
        var text = " $input "
        var due: String? = null
        var priority = 0
        var recurrence: Recurrence? = null
        val tags = mutableListOf<String>()
        val tokens = mutableListOf<String>()

        fun take(re: Regex, fn: (MatchResult) -> Unit): Boolean {
            val m = re.find(text) ?: return false
            fn(m)
            tokens += m.value.trim()
            text = text.replaceFirst(m.value, " ")
            return true
        }

        take(Regex("\\s!(1|2|3|low|med|medium|high)(?=\\s)", RegexOption.IGNORE_CASE)) {
            val v = it.groupValues[1].lowercase()
            priority = when { v == "low" -> 1; v.startsWith("med") -> 2; v == "high" -> 3; else -> v.toInt() }
        }
        val tagRe = Regex("\\s#([\\p{L}\\d_-]+)(?=\\s)")
        while (true) {
            val m = tagRe.find(text) ?: break
            tags += m.groupValues[1]; tokens += "#" + m.groupValues[1]
            text = text.replaceFirst(m.value, " ")
        }
        take(Regex("\\s(?:every\\s+(\\d+)\\s+(day|week|month|year)s?|every\\s+(day|week|month|year)|(daily|weekly|monthly|yearly))(?=\\s)", RegexOption.IGNORE_CASE)) {
            val map = mapOf("daily" to "day", "weekly" to "week", "monthly" to "month", "yearly" to "year")
            val freq = (it.groupValues[2].ifEmpty { it.groupValues[3].ifEmpty { map[it.groupValues[4].lowercase()] ?: "day" } }).lowercase()
            recurrence = Recurrence(freq, it.groupValues[1].toIntOrNull() ?: 1)
        }
        take(Regex("\\s(\\d{4}-\\d{2}-\\d{2})(?=\\s)")) { due = it.groupValues[1] }
        if (due == null) take(Regex("\\s(today|tod)(?=\\s)", RegexOption.IGNORE_CASE)) { due = now.toString() }
        if (due == null) take(Regex("\\s(tomorrow|tmr|tmrw)(?=\\s)", RegexOption.IGNORE_CASE)) { due = now.plusDays(1).toString() }
        if (due == null) take(Regex("\\snext\\s+week(?=\\s)", RegexOption.IGNORE_CASE)) { due = now.plusDays(7).toString() }
        if (due == null) take(Regex("\\sin\\s+(\\d+)\\s+(day|week)s?(?=\\s)", RegexOption.IGNORE_CASE)) {
            due = now.plusDays(it.groupValues[1].toLong() * if (it.groupValues[2].lowercase() == "week") 7 else 1).toString()
        }
        if (due == null) take(Regex("\\s(?:on\\s+)?(sun|mon|tue|wed|thu|fri|sat)[a-z]*(?=\\s)", RegexOption.IGNORE_CASE)) {
            val target = DAYS.indexOf(it.groupValues[1].lowercase())
            val cur = now.dayOfWeek.value % 7 // Sunday = 0
            val diff = ((target - cur + 7) % 7).let { d -> if (d == 0) 7 else d }
            due = now.plusDays(diff.toLong()).toString()
        }
        if (recurrence != null && due == null) due = now.toString()
        return ParsedTask(text.replace(Regex("\\s+"), " ").trim(), due, priority, tags, recurrence, tokens)
    }
}
