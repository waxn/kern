package app.kern.ui.screens

import android.os.Build
import android.view.HapticFeedbackConstants
import androidx.compose.animation.animateColorAsState
import androidx.compose.animation.core.FastOutLinearInEasing
import androidx.compose.animation.core.FastOutSlowInEasing
import androidx.compose.animation.core.Spring
import androidx.compose.animation.core.animate
import androidx.compose.animation.core.animateFloatAsState
import androidx.compose.animation.core.spring
import androidx.compose.animation.core.tween
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.Orientation
import androidx.compose.foundation.gestures.draggable
import androidx.compose.foundation.gestures.rememberDraggableState
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.navigationBarsPadding
import androidx.compose.foundation.layout.offset
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.outlined.Schedule
import androidx.compose.material3.Icon
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.ModalBottomSheet
import androidx.compose.material3.Text
import androidx.compose.material3.rememberModalBottomSheetState
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableFloatStateOf
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.rememberCoroutineScope
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.draw.clipToBounds
import androidx.compose.ui.draw.scale
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.graphicsLayer
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.layout.layout
import androidx.compose.ui.layout.onSizeChanged
import androidx.compose.ui.platform.LocalDensity
import androidx.compose.ui.platform.LocalView
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.IntOffset
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.data.MailAddr
import app.kern.data.MailPackage
import app.kern.ui.theme.KernColors
import app.kern.ui.theme.kern
import kotlinx.coroutines.Job
import kotlinx.coroutines.delay
import kotlinx.coroutines.launch
import java.time.LocalDate
import java.time.LocalDateTime
import java.time.ZoneId
import java.time.ZonedDateTime
import java.time.format.DateTimeFormatter
import java.time.format.TextStyle
import java.time.temporal.ChronoUnit
import java.util.Locale
import kotlin.math.abs
import kotlin.math.roundToInt
import kotlin.math.sign

// Pieces of Kern Mail that follow the web app's rules exactly (frontend/src/lib/mail/format.js,
// swipe.js, MessageCard.svelte), so a conversation reads the same on the phone and on the web.

private fun local(iso: String?): ZonedDateTime? =
    runCatching { ZonedDateTime.parse(iso).withZoneSameInstant(ZoneId.systemDefault()) }.getOrNull()

/** The web's shortDate: "09:41" today, "Yesterday", "Tue" this week, "Nov 3", "Nov 3, 2024". */
internal fun mailDate(iso: String?, h24: Boolean, now: LocalDateTime = LocalDateTime.now(), locale: Locale = Locale.getDefault()): String {
    val d = local(iso)?.toLocalDateTime() ?: return ""
    val today = now.toLocalDate()
    val day = d.toLocalDate()
    fun pattern(skeleton: String) = DateTimeFormatter.ofPattern(android.text.format.DateFormat.getBestDateTimePattern(locale, skeleton), locale)
    return when {
        day == today -> d.format(DateTimeFormatter.ofPattern(if (h24) "HH:mm" else "h:mm a", locale))
        day == today.minusDays(1) -> "Yesterday"
        d.isBefore(now) && ChronoUnit.HOURS.between(d, now) < 6 * 24 -> day.dayOfWeek.getDisplayName(TextStyle.SHORT, locale)
        day.year == today.year -> d.format(pattern("MMMd"))
        else -> d.format(pattern("yMMMd"))
    }
}

/** The web's timeGroup: the headings between rows of the list. */
internal fun timeGroup(iso: String?, today: LocalDate = LocalDate.now(), locale: Locale = Locale.getDefault()): String {
    val d = local(iso)?.toLocalDate() ?: return "Undated"
    val days = ChronoUnit.DAYS.between(d, today)
    return when {
        days <= 0 -> "Today"
        days == 1L -> "Yesterday"
        days < 7 -> "Earlier this week"
        days < 14 -> "Last week"
        d.year == today.year -> d.month.getDisplayName(TextStyle.FULL_STANDALONE, locale)
        else -> d.year.toString()
    }
}

/** The web's snoozeLabel: "Today 18:00", "Tomorrow 08:00", "Sat 09:00", "3 Dec 08:00". */
internal fun snoozeLabel(at: LocalDateTime, h24: Boolean, today: LocalDate = LocalDate.now(), locale: Locale = Locale.getDefault()): String {
    val time = at.format(DateTimeFormatter.ofPattern(if (h24) "HH:mm" else "h:mm a", locale))
    val days = ChronoUnit.DAYS.between(today, at.toLocalDate())
    return when {
        days == 0L -> "Today $time"
        days == 1L -> "Tomorrow $time"
        days in 2..6 -> at.dayOfWeek.getDisplayName(TextStyle.SHORT, locale) + " " + time
        else -> at.format(DateTimeFormatter.ofPattern(android.text.format.DateFormat.getBestDateTimePattern(locale, "dMMM"), locale)) + " " + time
    }
}

internal fun snoozeLabel(iso: String?, h24: Boolean): String = local(iso)?.let { snoozeLabel(it.toLocalDateTime(), h24) } ?: ""

internal data class SnoozePreset(val label: String, val at: LocalDateTime)

/** The web's snoozePresets, in the same order with the same names. */
internal fun snoozePresets(now: LocalDateTime = LocalDateTime.now()): List<SnoozePreset> {
    fun at(days: Long, hour: Int) = now.toLocalDate().plusDays(days).atTime(hour, 0)
    val out = mutableListOf<SnoozePreset>()
    val later = now.plusHours(3).withMinute(0).withSecond(0).withNano(0)
    if (later.toLocalDate() == now.toLocalDate() && later.hour < 21) out += SnoozePreset("Later today", later)
    if (now.hour < 17) out += SnoozePreset("This evening", at(0, 18))
    out += SnoozePreset("Tomorrow morning", at(1, 8))
    val dow = now.dayOfWeek.value % 7 // 0 = Sunday, like JavaScript
    if (dow in 1..4) out += SnoozePreset("This weekend", at((6 - dow).toLong(), 9))
    out += SnoozePreset("Next week", at(((8 - dow) % 7).let { if (it == 0) 7 else it }.toLong(), 8))
    out += SnoozePreset("In a month", at(30, 8))
    return out
}

internal fun LocalDateTime.isoOffset(): String = atZone(ZoneId.systemDefault()).toOffsetDateTime().toString()

/** A date in the phone's own order for a skeleton like "MMMd": "Nov 24" in the US, "24 Nov" in the UK. */
internal fun localDate(d: LocalDate, skeleton: String, locale: Locale = Locale.getDefault()): String =
    d.format(DateTimeFormatter.ofPattern(android.text.format.DateFormat.getBestDateTimePattern(locale, skeleton), locale))

/** One short line about when a package arrives (or arrived), worded like the web's packages.js arrivalLabel. */
internal fun arrival(
    p: MailPackage,
    today: LocalDate = LocalDate.now(),
    zone: ZoneId = ZoneId.systemDefault(),
    date: (LocalDate, String) -> String = { d, skeleton -> localDate(d, skeleton) },
): String {
    val at = runCatching { ZonedDateTime.parse(p.statusAt).withZoneSameInstant(zone).toLocalDate() }.getOrNull()
    when (p.status) {
        "delivered" -> return when (at) {
            null -> "Delivered"
            today -> "Delivered today"
            today.minusDays(1) -> "Delivered yesterday"
            else -> "Delivered " + date(at, "EEEMMMd")
        }
        "ready_for_pickup" -> return "Waiting for you to pick it up"
        "out_for_delivery" -> return if (at == null || at == today) "Arriving today" else "Out for delivery since " + date(at, "EEEMMMd")
    }
    val expected = p.expected?.let { runCatching { LocalDate.parse(it) }.getOrNull() }
        ?: return if (p.status == "exception") "Check with the carrier" else "No delivery date yet"
    val n = ChronoUnit.DAYS.between(today, expected)
    return when {
        n == -1L -> "Expected yesterday"
        n < 0 -> "Expected ${-n} days ago"
        n == 0L -> "Arriving today"
        n == 1L -> "Arriving tomorrow"
        n < 7 -> "Arriving " + date(expected, "EEEE")
        else -> "Arriving " + date(expected, "MMMd")
    }
}

/**
 * The To and Cc fields: `"Doe, Jane" <jane@x.org>, bob@y.org` is two people. Commas and semicolons
 * inside quotes or angle brackets don't split.
 */
internal fun parseAddrs(s: String): List<MailAddr> {
    val parts = mutableListOf<String>()
    val cur = StringBuilder()
    var quoted = false
    var angle = false
    for (c in s) {
        when {
            c == '"' && !angle -> { quoted = !quoted; cur.append(c) }
            c == '<' && !quoted -> { angle = true; cur.append(c) }
            c == '>' && !quoted -> { angle = false; cur.append(c) }
            (c == ',' || c == ';') && !quoted && !angle -> { parts += cur.toString(); cur.clear() }
            else -> cur.append(c)
        }
    }
    parts += cur.toString()
    return parts.map { it.trim() }.filter { it.isNotEmpty() }.map { part ->
        val m = Regex("^(.*)<([^>]*)>$").find(part)
        if (m == null) MailAddr("", part)
        else MailAddr(m.groupValues[1].trim().removeSurrounding("\"").replace("\\\"", "\"").trim(), m.groupValues[2].trim())
    }
}

/** The other way round, quoting a name that would otherwise be split ("Doe, Jane"). */
internal fun addrsText(l: List<MailAddr>): String = l.joinToString(", ") { a ->
    when {
        a.name.isBlank() -> a.addr
        a.name.any { it in ",;<>\"@" } -> "\"" + a.name.replace("\"", "\\\"") + "\" <${a.addr}>"
        else -> "${a.name} <${a.addr}>"
    }
}

/** A conversation action as /mail/threads/actions takes it. [context] is the folder it's taken in
 *  (null in Starred, All mail and search). */
internal data class MailAct(val action: String, val context: Long? = null, val dest: Long? = null) {
    val extras: Array<Pair<String, Any?>>
        get() = listOfNotNull(context?.let { "context" to it }, dest?.let { "dest" to it }).toTypedArray()
}

/** Folder ids by role, for putting things back. */
internal data class MailRoles(val inbox: Long? = null, val archive: Long? = null, val trash: Long? = null, val junk: Long? = null)

/** What puts an action back the way it was: the web's undo.js inverseOf. */
internal fun inverseOf(a: MailAct, roles: MailRoles): MailAct? {
    val back = a.context ?: roles.inbox
    return when (a.action) {
        "archive" -> MailAct("move", roles.archive, back)
        "trash" -> MailAct("move", roles.trash, back)
        "move" -> if (back != null) MailAct("move", a.dest, back) else null
        "spam" -> MailAct("not_spam", roles.junk)
        "inbox" -> if (a.context != null) MailAct("move", roles.inbox, a.context) else null
        "snooze" -> MailAct("unsnooze")
        else -> null
    }
}

/** Something that can't be an address ("bob", "bob@", "@x.org"), or null when they all look fine. */
internal fun badAddr(l: List<MailAddr>): String? =
    l.firstOrNull { !Regex("^[^@\\s<>]+@[^@\\s<>]+\\.[^@\\s<>]+$").matches(it.addr) }?.let { it.addr.ifBlank { it.name } }

/** The web's hue(): a calm, steady colour for each address. */
internal fun addrHue(addr: String): Int {
    var h = 0
    var i = 0
    while (i < addr.length) {
        val cp = addr.codePointAt(i)
        h = (h * 31 + cp) % 360
        i += Character.charCount(cp)
    }
    return h
}

/** The web's initials(): "Ada Lovelace" → "AL", "ada@x.org" → "A". */
internal fun initials(p: MailAddr): String {
    val n = p.display.replace(Regex("[^\\p{L}\\p{N}\\s]"), "").trim()
    if (n.isEmpty()) return "?"
    val parts = n.split(Regex("\\s+"))
    val a = parts.first().take(1)
    val b = if (parts.size > 1) parts.last().take(1) else ""
    return (a + b).uppercase()
}

private fun avatarColor(k: KernColors, addr: String): Color = when (addrHue(addr) % 6) {
    0 -> k.orange; 1 -> k.green; 2 -> k.blue; 3 -> k.red; 4 -> k.purple; else -> k.yellow
}

@Composable
internal fun MailAvatar(p: MailAddr, size: Dp = 38.dp) {
    val k = kern
    Box(
        Modifier.size(size).clip(CircleShape).background(avatarColor(k, p.addr).copy(alpha = if (k.dark) 0.26f else 0.22f))
            .border(1.dp, k.text.copy(alpha = 0.08f), CircleShape),
        contentAlignment = Alignment.Center,
    ) {
        Text(initials(p), color = k.text, fontSize = (size.value * 0.38f).sp, fontWeight = FontWeight.Medium, maxLines = 1)
    }
}

/** What a swipe does: shown under the row while it moves, run once it's let go past the line. */
internal class SwipeAction(val label: String, val icon: ImageVector, val color: Color, val leaves: Boolean, val run: () -> Unit)

/**
 * A list row that follows the finger (swipe.js on the web): right and left reveal their action,
 * a tick of haptics when it's far enough to count, then the row flies off with the finger's speed.
 * Not far enough springs it back. A row whose action keeps it ([SwipeAction.leaves] false, like
 * Snooze opening its choices) slides back in.
 */
@Composable
internal fun SwipeRow(right: SwipeAction?, left: SwipeAction?, modifier: Modifier = Modifier, content: @Composable () -> Unit) {
    val k = kern
    val view = LocalView.current
    val scope = rememberCoroutineScope()
    val threshold = with(LocalDensity.current) { 92.dp.toPx() }
    var dx by remember { mutableFloatStateOf(0f) }
    var width by remember { mutableIntStateOf(1) }
    var height by remember { mutableFloatStateOf(1f) } // 1 = full; folds to 0 before a leaving action runs
    val job = remember { arrayOfNulls<Job>(1) }

    fun tick(on: Boolean) {
        val c = when {
            Build.VERSION.SDK_INT >= 34 -> if (on) HapticFeedbackConstants.GESTURE_THRESHOLD_ACTIVATE else HapticFeedbackConstants.GESTURE_THRESHOLD_DEACTIVATE
            Build.VERSION.SDK_INT >= 30 -> if (on) HapticFeedbackConstants.CONFIRM else HapticFeedbackConstants.CLOCK_TICK
            else -> HapticFeedbackConstants.CLOCK_TICK
        }
        view.performHapticFeedback(c)
    }

    val drag = rememberDraggableState { d ->
        val next = dx + d
        val allowed = (next > 0 && right != null) || (next < 0 && left != null)
        val was = abs(dx) > threshold
        dx = if (allowed) next else 0f
        val now = abs(dx) > threshold
        if (was != now) tick(now)
    }

    fun settle(velocity: Float) {
        val action = if (dx > 0) right else if (dx < 0) left else null
        val flung = abs(velocity) > 1800f && sign(velocity) == sign(dx) && abs(dx) > threshold / 3
        val go = action != null && (abs(dx) > threshold || flung)
        job[0] = scope.launch {
            if (go) {
                if (flung && abs(dx) <= threshold) tick(true)
                animate(dx, sign(dx) * width, initialVelocity = velocity, animationSpec = tween(170, easing = FastOutLinearInEasing)) { v, _ -> dx = v }
                if (action.leaves) {
                    // The gap closes smoothly, then the list takes the row away.
                    animate(1f, 0f, animationSpec = tween(200, easing = FastOutSlowInEasing)) { v, _ -> height = v }
                    action.run()
                    delay(700) // still here (the action failed): bring it back
                    launch { animate(height, 1f, animationSpec = tween(200, easing = FastOutSlowInEasing)) { v, _ -> height = v } }
                } else {
                    action.run()
                    delay(120)
                }
                animate(dx, 0f, animationSpec = spring(dampingRatio = 0.82f, stiffness = Spring.StiffnessMediumLow)) { v, _ -> dx = v }
            } else {
                animate(dx, 0f, initialVelocity = velocity, animationSpec = spring(dampingRatio = 0.72f, stiffness = Spring.StiffnessMedium)) { v, _ -> dx = v }
            }
        }
    }

    Box(
        modifier.fillMaxWidth().onSizeChanged { width = maxOf(1, it.width) }
            .clipToBounds()
            .layout { m, c ->
                val p = m.measure(c)
                layout(p.width, (p.height * height).roundToInt()) { p.place(0, 0) }
            },
    ) {
        val action = if (dx > 0) right else if (dx < 0) left else null
        if (action != null) {
            val armed = abs(dx) > threshold
            val progress = (abs(dx) / threshold).coerceIn(0f, 1f)
            val bg by animateColorAsState(action.color.copy(alpha = if (armed) (if (k.dark) 0.34f else 0.26f) else (if (k.dark) 0.16f else 0.12f)), label = "swipe-bg")
            val pop by animateFloatAsState(if (armed) 1.12f else 1f, spring(dampingRatio = 0.45f, stiffness = Spring.StiffnessMedium), label = "swipe-pop")
            val toRight = dx > 0
            Row(
                Modifier.matchParentSize().background(bg).padding(horizontal = 24.dp),
                horizontalArrangement = if (toRight) Arrangement.Start else Arrangement.End,
                verticalAlignment = Alignment.CenterVertically,
            ) {
                Row(
                    Modifier.graphicsLayer { alpha = 0.35f + 0.65f * progress }.scale(pop),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    if (toRight) {
                        Icon(action.icon, null, tint = action.color, modifier = Modifier.size(20.dp))
                        Spacer(Modifier.width(8.dp))
                    }
                    Text(action.label.uppercase(), color = action.color, fontSize = 11.5.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 1.1.sp)
                    if (!toRight) {
                        Spacer(Modifier.width(8.dp))
                        Icon(action.icon, null, tint = action.color, modifier = Modifier.size(20.dp))
                    }
                }
            }
        }
        Box(
            Modifier.offset { IntOffset(dx.roundToInt(), 0) }
                .background(k.bg)
                .draggable(
                    drag, Orientation.Horizontal,
                    enabled = right != null || left != null,
                    onDragStarted = { job[0]?.cancel() },
                    onDragStopped = { v -> settle(v) },
                ),
        ) { content() }
    }
}

/** Snooze choices, the same ones as the web's snooze dialog. */
@Composable
internal fun SnoozeSheet(h24: Boolean, onDismiss: () -> Unit, onPick: (LocalDateTime) -> Unit) {
    val sheet = rememberModalBottomSheetState(skipPartiallyExpanded = true)
    val k = kern
    ModalBottomSheet(onDismissRequest = onDismiss, sheetState = sheet, containerColor = k.surface, contentColor = k.text) {
        Column(Modifier.fillMaxWidth().navigationBarsPadding().padding(bottom = 12.dp)) {
            Text("Snooze until", style = MaterialTheme.typography.titleMedium, modifier = Modifier.padding(start = 24.dp, end = 24.dp, bottom = 8.dp))
            snoozePresets().forEach { p ->
                Row(
                    Modifier.fillMaxWidth().clickable { onPick(p.at) }.padding(horizontal = 24.dp, vertical = 14.dp),
                    verticalAlignment = Alignment.CenterVertically,
                ) {
                    Icon(Icons.Outlined.Schedule, null, tint = k.text3, modifier = Modifier.size(18.dp))
                    Spacer(Modifier.width(14.dp))
                    Text(p.label, style = MaterialTheme.typography.bodyLarge, modifier = Modifier.weight(1f))
                    Text(snoozeLabel(p.at, h24), style = MaterialTheme.typography.bodySmall, color = k.text3)
                }
            }
        }
    }
}

/** Uppercase small heading between list rows (the web's `.ledger`). */
@Composable
internal fun Ledger(text: String, modifier: Modifier = Modifier, color: Color = kern.text3) {
    Text(text.uppercase(), modifier = modifier, color = color, fontSize = 10.5.sp, fontWeight = FontWeight.SemiBold, letterSpacing = 0.5.sp, maxLines = 1)
}

/** The web's `.seg`: a small two-way switch on a sunken track. */
@Composable
internal fun Segmented(options: List<String>, selected: Int, modifier: Modifier = Modifier, onSelect: (Int) -> Unit) {
    val k = kern
    val shape = androidx.compose.foundation.shape.RoundedCornerShape(8.dp)
    Row(modifier.clip(shape).background(k.surface2).padding(2.dp)) {
        options.forEachIndexed { i, label ->
            val on = i == selected
            val inner = androidx.compose.foundation.shape.RoundedCornerShape(6.dp)
            Text(
                label, fontSize = 12.5.sp, maxLines = 1,
                color = if (on) k.text else k.text2, fontWeight = if (on) FontWeight.SemiBold else FontWeight.Normal,
                modifier = Modifier.clip(inner)
                    .background(if (on) k.surface else Color.Transparent)
                    .then(if (on) Modifier.border(1.dp, k.border, inner) else Modifier)
                    .clickable { if (!on) onSelect(i) }
                    .padding(horizontal = 10.dp, vertical = 4.dp),
            )
        }
    }
}
