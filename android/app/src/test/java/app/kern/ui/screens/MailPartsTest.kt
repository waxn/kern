package app.kern.ui.screens

import app.kern.data.MailAddr
import app.kern.data.MailPackage
import org.junit.Assert.assertEquals
import org.junit.Assert.assertNull
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

    @Test fun addressesWithCommasInTheirNames() {
        val got = parseAddrs("\"Doe, Jane\" <jane@x.org>, bob@y.org; Ann Lee <ann@z.org>")
        assertEquals(listOf(MailAddr("Doe, Jane", "jane@x.org"), MailAddr("", "bob@y.org"), MailAddr("Ann Lee", "ann@z.org")), got)
        // Written back out and read again, the same three people.
        assertEquals(got, parseAddrs(addrsText(got)))
        assertEquals("\"Doe, Jane\" <jane@x.org>, bob@y.org, Ann Lee <ann@z.org>", addrsText(got))
        assertEquals(listOf(MailAddr("Say \"hi\"", "s@x.org")), parseAddrs(addrsText(listOf(MailAddr("Say \"hi\"", "s@x.org")))))
        assertEquals(emptyList<MailAddr>(), parseAddrs(" , ;"))
    }

    @Test fun addressesThatCannotBeSentTo() {
        assertNull(badAddr(parseAddrs("bob@y.org, Ann <ann@z.co.uk>")))
        assertEquals("bob", badAddr(parseAddrs("bob")))
        assertEquals("bob@y", badAddr(parseAddrs("ann@z.org, bob@y")))
        assertEquals("Ann", badAddr(parseAddrs("Ann <>")))
    }

    private val today = LocalDate.of(2026, 11, 26) // a Thursday
    private val utc = ZoneId.of("UTC")
    private fun pkg(status: String, statusAt: String? = null, expected: String? = null) =
        MailPackage(id = 1, status = status, statusAt = statusAt, expected = expected)
    private fun arrive(p: MailPackage) = arrival(p, today, utc) { d, skeleton -> "$skeleton $d" }

    @Test fun arrivalWordedLikeTheWeb() {
        assertEquals("Delivered today", arrive(pkg("delivered", "2026-11-26T09:00:00Z")))
        assertEquals("Delivered yesterday", arrive(pkg("delivered", "2026-11-25T09:00:00Z")))
        assertEquals("Delivered EEEMMMd 2026-11-20", arrive(pkg("delivered", "2026-11-20T09:00:00Z")))
        assertEquals("Delivered", arrive(pkg("delivered")))
        assertEquals("Waiting for you to pick it up", arrive(pkg("ready_for_pickup", "2026-11-24T09:00:00Z")))
        assertEquals("Arriving today", arrive(pkg("out_for_delivery", "2026-11-26T07:00:00Z")))
        assertEquals("Out for delivery since EEEMMMd 2026-11-24", arrive(pkg("out_for_delivery", "2026-11-24T07:00:00Z")))
        assertEquals("Expected yesterday", arrive(pkg("in_transit", expected = "2026-11-25")))
        assertEquals("Expected 3 days ago", arrive(pkg("in_transit", expected = "2026-11-23")))
        assertEquals("Arriving today", arrive(pkg("in_transit", expected = "2026-11-26")))
        assertEquals("Arriving tomorrow", arrive(pkg("in_transit", expected = "2026-11-27")))
        assertEquals("Arriving EEEE 2026-11-30", arrive(pkg("in_transit", expected = "2026-11-30")))
        assertEquals("Arriving MMMd 2026-12-10", arrive(pkg("in_transit", expected = "2026-12-10")))
        assertEquals("No delivery date yet", arrive(pkg("in_transit")))
        assertEquals("Check with the carrier", arrive(pkg("exception")))
    }

    @Test fun undoPutsThingsBackLikeTheWeb() {
        // The web's rules, frontend/src/lib/mail/undo.js.
        val roles = MailRoles(inbox = 1, archive = 2, trash = 3, junk = 4)
        assertEquals(MailAct("move", 2, 1), inverseOf(MailAct("archive", 1), roles))
        assertEquals(MailAct("move", 2, 9), inverseOf(MailAct("archive", 9), roles)) // from a folder of your own, back to it
        assertEquals(MailAct("move", 2, 1), inverseOf(MailAct("archive"), roles)) // from Starred: to the Inbox
        assertEquals(MailAct("move", 3, 9), inverseOf(MailAct("trash", 9), roles))
        assertEquals(MailAct("move", 1, 3), inverseOf(MailAct("inbox", 3), roles))
        assertNull(inverseOf(MailAct("inbox"), roles))
        assertEquals(MailAct("not_spam", 4), inverseOf(MailAct("spam", 1), roles))
        assertEquals(MailAct("unsnooze"), inverseOf(MailAct("snooze", 1), roles))
        assertNull(inverseOf(MailAct("star", 1), roles))
        assertEquals(listOf("context" to 2L, "dest" to 1L), MailAct("move", 2, 1).extras.toList())
        assertEquals(emptyList<Pair<String, Any?>>(), MailAct("unsnooze").extras.toList())
    }

    @Test fun viewsAsTheServerNamesThem() {
        assertEquals("inbox", apiView("inbox"))
        assertEquals("starred", apiView("starred"))
        assertEquals("folder:12", apiView("f12")) // known before the folder list has loaded
        assertEquals("all", apiView("fx"))
    }
}
