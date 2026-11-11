package app.kern.data

import app.kern.notify.SyncWorker
import org.junit.Assert.assertFalse
import org.junit.Assert.assertTrue
import org.junit.Test

class ReminderTest {
    private val min = 60_000L
    private val now = 1_000_000_000_000L

    @Test fun waitsForTheCooldown() {
        assertTrue(SyncWorker.cardsReminderDue(now, 0, 90, false))             // never reminded
        assertFalse(SyncWorker.cardsReminderDue(now, now - 89 * min, 90, true)) // 89 min ago: too soon
        assertTrue(SyncWorker.cardsReminderDue(now, now - 90 * min, 90, true))  // 90 min: again
        assertFalse(SyncWorker.cardsReminderDue(now, now - 30 * min, 60, true)) // studied 30 min ago
    }

    @Test fun onceADay() {
        assertTrue(SyncWorker.cardsReminderDue(now, now - 5 * min, 0, false))
        assertFalse(SyncWorker.cardsReminderDue(now, now - 600 * min, 0, true))
    }
}
