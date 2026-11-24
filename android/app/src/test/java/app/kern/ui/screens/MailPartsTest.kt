package app.kern.ui.screens

import app.kern.data.MailAddr
import org.junit.Assert.assertEquals
import org.junit.Test
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.util.Locale

/** The phone has to name, group and colour mail exactly like the web (frontend/src/lib/mail/format.js). */
class MailPartsTest {
    @Test fun hueMatchesTheWeb() {
        // Values from format.js hue().
        assertEquals(310, addrHue("ada@example.org"))
        assertEquals(352, addrHue("Grüße@x.de"))
        assertEquals(40, addrHue("bob.smith@mail.com"))
    }

    @Test fun initialsMatchTheWeb() {
        assertEquals("AL", initials(MailAddr("Ada Lovelace", "a@x")))
        assertEquals("A", initials(MailAddr("", "ada@x.org")))
        assertEquals("JT", initials(MailAddr("J. R. R. Tolkien", "")))
        assertEquals("?", initials(MailAddr("", "")))
    }

    @Test fun snoozeChoicesOnAMondayMorning() {
        val now = LocalDateTime.of(2026, 11, 23, 10, 0) // a Monday
        val got = snoozePresets(now).map { it.label to it.at }
        assertEquals(listOf(
            "Later today" to LocalDateTime.of(2026, 11, 23, 13, 0),
            "This evening" to LocalDateTime.of(2026, 11, 23, 18, 0),
            "Tomorrow morning" to LocalDateTime.of(2026, 11, 24, 8, 0),
            "This weekend" to LocalDateTime.of(2026, 11, 28, 9, 0),
            "Next week" to LocalDateTime.of(2026, 11, 30, 8, 0),
            "In a month" to LocalDateTime.of(2026, 12, 23, 8, 0),
        ), got)
    }

    @Test fun snoozeChoicesOnASaturdayEvening() {
        val now = LocalDateTime.of(2026, 11, 28, 19, 30)
        assertEquals(listOf("Tomorrow morning", "Next week", "In a month"), snoozePresets(now).map { it.label })
        assertEquals(LocalDateTime.of(2026, 11, 30, 8, 0), snoozePresets(now)[1].at)
    }

    @Test fun groupsLikeTheWeb() {
        val today = LocalDate.of(2026, 11, 23)
        fun at(d: LocalDate) = d.atTime(12, 0).atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()
        assertEquals("Today", timeGroup(at(today), today, Locale.US))
        assertEquals("Yesterday", timeGroup(at(today.minusDays(1)), today, Locale.US))
        assertEquals("Earlier this week", timeGroup(at(today.minusDays(4)), today, Locale.US))
        assertEquals("Last week", timeGroup(at(today.minusDays(10)), today, Locale.US))
        assertEquals("September", timeGroup(at(LocalDate.of(2026, 9, 2)), today, Locale.US))
        assertEquals("2025", timeGroup(at(LocalDate.of(2025, 12, 30)), today, Locale.US))
        assertEquals("Undated", timeGroup(null, today, Locale.US))
    }
}
