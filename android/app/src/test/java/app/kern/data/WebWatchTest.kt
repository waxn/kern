package app.kern.data

import app.kern.notify.SyncWorker
import org.junit.Assert.assertEquals
import org.junit.Assert.assertFalse
import org.junit.Assert.assertNull
import org.junit.Assert.assertTrue
import org.junit.Test

/** Bookmark watching: the JSON shapes from backend/notes/views_web.py and the change notices. */
class WebWatchTest {
    private fun item(json: String) = KernJson.decodeFromString(WebItem.serializer(), json)

    // A list item: `monitor` is the short summary (price a string, error a flag).
    private val listItem = """
        {"id": "12", "url": "https://shop.example/kettle", "title": "Kettle", "kind": "web",
         "tags": ["0b9e5f3a-1111-4222-8333-944455556666"],
         "monitor": {"enabled": true, "mode": "price", "unseen": 2, "last_changed_at": "2026-11-18T09:00:00+00:00",
                     "price": "€39.99", "error": false}}
    """

    @Test fun readsTheListSummary() {
        val w = item(listItem)
        assertEquals(12L, w.id)
        assertEquals(listOf("0b9e5f3a-1111-4222-8333-944455556666"), w.tags)
        assertEquals(2, w.unseen)
        assertEquals("€39.99", w.monitor!!.priceText)
        assertFalse(w.monitor!!.hasError)
        assertEquals("price", w.monitor!!.watching)
        assertTrue(w.canWatch)
    }

    @Test fun unwatchedItemsHaveNoMonitor() {
        val w = item("""{"id": "3", "url": "https://x.org", "kind": "video", "monitor": null}""")
        assertNull(w.monitor)
        assertEquals(0, w.unseen)
        assertFalse(w.canWatch)
        assertTrue(item("""{"id": "4", "url": "https://x.org", "monitor": {"error": true}}""").monitor!!.hasError)
    }

    @Test fun readsTheDetailWithAPriceChange() {
        val w = item("""
            {"id": "12", "url": "https://shop.example/kettle", "versions": 4,
             "monitor": {"enabled": true, "mode": "auto", "resolved_mode": "price", "interval": 720, "archive": true,
                         "error": "", "unseen": 1, "feed_url": "",
                         "price": {"amount": 39.99, "currency": "EUR", "display": "€39.99", "source": "structured"},
                         "last_change": {"type": "price", "old": {"amount": 49.0, "display": "€49.00"},
                                         "new": {"amount": 39.99, "display": "€39.99"}, "at": "2026-11-18T09:00:00+00:00"},
                         "price_history": [], "latest": []}}
        """)
        val m = w.monitor!!
        assertEquals(4, w.versions)
        assertEquals(720, m.interval)
        assertEquals("price", m.watching)
        assertEquals("€39.99", m.priceText)
        assertEquals("", m.errorText)
        assertFalse(m.hasError)
        val c = m.lastChange as WebChange.Price
        assertTrue(c.dropped)
        assertEquals("Price €49.00 → €39.99", c.text)
        assertEquals("2026-11-18T09:00:00+00:00", c.at)
    }

    @Test fun readsTheDetailError() {
        val m = item("""{"id": "1", "url": "u", "monitor": {"enabled": true, "error": "Couldn't find a price on this page.", "last_change": null, "price": null}}""").monitor!!
        assertEquals("Couldn't find a price on this page.", m.errorText)
        assertTrue(m.hasError)
        assertEquals("", m.priceText)
        assertNull(m.lastChange)
    }

    @Test fun parsesPostAndContentChanges() {
        val posts = WebChange.parse(KernJson.parseToJsonElement("""
            {"type": "posts", "count": 2, "added": [{"title": "Hello", "url": "https://b.log/1", "date": ""}, {"title": "", "url": "https://b.log/2"}]}
        """)) as WebChange.Posts
        assertEquals(2, posts.added.size)
        assertEquals("https://b.log/2", posts.added[1].url)
        assertEquals("2 new posts", posts.text)
        assertEquals("1 new post", posts.copy(count = 1).text)

        val content = WebChange.parse(KernJson.parseToJsonElement("""
            {"type": "content", "added": 3, "removed": 1, "snippets": ["New paragraph here"]}
        """)) as WebChange.Content
        assertEquals(listOf("New paragraph here"), content.snippets)
        assertEquals("Text changed (+3 / −1 lines)", content.text)
        assertEquals("Text changed (+1 line)", content.copy(added = 1, removed = 0).text)
    }

    @Test fun readsVersions() {
        val vs = KernJson.decodeFromString(kotlinx.serialization.builtins.ListSerializer(WebVersion.serializer()), """
            [{"id": 9, "created_at": "2026-11-18T09:00:00+00:00", "trigger": "change", "url": "u", "title": "t",
              "change": {"type": "posts", "count": 1, "added": [{"title": "A", "url": "", "date": ""}]},
              "price": "", "size": 1200, "has_page": true, "prev": 8},
             {"id": 8, "created_at": "2026-11-17T09:00:00+00:00", "trigger": "saved", "change": {}, "price": "€49.00",
              "size": 1100, "has_page": false, "prev": null}]
        """)
        assertEquals("Change found", vs[0].triggerLabel)
        assertEquals("1 new post", vs[0].change!!.text)
        assertEquals(8L, vs[0].prev)
        assertNull(vs[1].change) // {} = no change recorded
        assertEquals("Bookmarked", vs[1].triggerLabel)
        assertFalse(vs[1].hasPage)
    }

    @Test fun readsTheChangeCounts() {
        val c = KernJson.decodeFromString(WebChanges.serializer(), """{"changed": 3, "watched": 7}""")
        assertEquals(3, c.changed)
        assertEquals(7, c.watched)
    }

    private fun changed(id: Long, title: String, mode: String, unseen: Int, price: String = "") = item("""
        {"id": "$id", "url": "https://www.example.org/x", "title": "$title",
         "monitor": {"enabled": true, "mode": "$mode", "unseen": $unseen, "price": "$price", "error": false}}
    """)

    @Test fun notifiesOnlyAboutNewChanges() {
        val list = listOf(
            changed(1, "Simon Willison's Weblog", "posts", 1),
            changed(2, "Kettle", "price", 2, "€39.99"),
            changed(3, "", "content", 1),
        )
        val all = SyncWorker.webNotices(emptyMap(), list)
        assertEquals(listOf("New post on Simon Willison's Weblog", "Price changed on Kettle", "example.org changed"), all.map { it.title })
        assertEquals("Now €39.99", all[1].text)
        // Already notified about 1 and 3; 2 has one more change than last time.
        val next = SyncWorker.webNotices(mapOf(1L to 1, 2L to 1, 3L to 1), list)
        assertEquals(listOf(2L), next.map { it.id })
        assertTrue(SyncWorker.webNotices(mapOf(1L to 1, 2L to 2, 3L to 1), list).isEmpty())
    }
}
