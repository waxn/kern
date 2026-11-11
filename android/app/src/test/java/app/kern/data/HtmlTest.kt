package app.kern.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test
import java.time.LocalDate

class HtmlTest {
    private fun roundTrip(html: String): String {
        val refs = Html.RefMap()
        return Html.fromMarkup(Html.toMarkup(html, refs), refs)
    }

    @Test fun formattingSurvivesEditing() {
        assertEquals("<strong>bold</strong> and <em>it</em>", roundTrip("<b>bold</b> and <i>it</i>"))
        assertEquals("a <code>x &lt; y</code> b", roundTrip("a <code>x &lt; y</code> b"))
        assertEquals("<s>gone</s> <u>under</u> <mark>hi</mark>", roundTrip("<s>gone</s> <u>under</u> <mark>hi</mark>"))
        assertEquals("line one<br>line two", roundTrip("line one<br>line two"))
        assertEquals("<a href=\"https://x.org/a?b=1&amp;c=2\">site</a>", roundTrip("<a href=\"https://x.org/a?b=1&amp;c=2\">site</a>"))
    }

    @Test fun refsAreKeptExactly() {
        val ref = "<a class=\"ref\" data-ref=\"doc:0b9e5f3a-1111-4222-8333-944455556666\" href=\"/doc/0b9e5f3a-1111-4222-8333-944455556666\" contenteditable=\"false\">My Page</a>"
        val tag = "<a class=\"ref tag\" data-ref=\"tag:0b9e5f3a-1111-4222-8333-944455556667\" href=\"/tag/x\" contenteditable=\"false\" data-c=\"blue\">#work</a>"
        val refs = Html.RefMap()
        val markup = Html.toMarkup("See $ref and $tag.", refs)
        assertEquals("See [[My Page]] and #work.", markup)
        assertEquals("See $ref and $tag.", Html.fromMarkup(markup, refs))
    }

    @Test fun unknownRefsAreReported() {
        val (pages, tags) = Html.unknownRefs("Link [[New idea]] with #fresh and C#", Html.RefMap())
        assertEquals(setOf("New idea"), pages)
        assertEquals(setOf("fresh"), tags)
    }

    @Test fun plainTextIsEscaped() {
        assertEquals("1 &lt; 2 &amp; 3 * 4", Html.fromMarkup("1 < 2 & 3 * 4", Html.RefMap()))
    }

    @Test fun mathRoundTrips() {
        val out = roundTrip("<span class=\"math\" data-math=\"x^2\" contenteditable=\"false\">x^2</span> ok")
        assertTrue(out, out.contains("data-math=\"x^2\""))
    }

    @Test fun textStripsTags() {
        assertEquals("a b\nc & d", Html.text("<b>a</b> b<br>c &amp; d"))
    }
}

class TaskParseTest {
    private val wed = LocalDate.of(2026, 11, 11) // a Wednesday

    @Test fun quickAdd() {
        val p = TaskParse.parse("Pay rent tomorrow !2 #home every month", wed)
        assertEquals("Pay rent", p.title)
        assertEquals("2026-11-12", p.due)
        assertEquals(2, p.priority)
        assertEquals(listOf("home"), p.tags)
        assertEquals(Recurrence("month", 1), p.recurrence)
    }

    @Test fun weekdaysAndDates() {
        assertEquals("2026-11-13", TaskParse.parse("Call on friday", wed).due)
        assertEquals("2026-11-18", TaskParse.parse("Standup wed", wed).due) // same weekday means next week
        assertEquals("2026-12-01", TaskParse.parse("Deadline 2026-12-01", wed).due)
        assertEquals("2026-11-25", TaskParse.parse("Check in 2 weeks", wed).due)
        assertEquals("Plain task", TaskParse.parse("Plain task", wed).title)
    }
}
