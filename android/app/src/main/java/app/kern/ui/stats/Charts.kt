package app.kern.ui.stats

import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.gestures.detectTapGestures
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
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Text
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.mutableIntStateOf
import androidx.compose.runtime.mutableStateOf
import androidx.compose.runtime.remember
import androidx.compose.runtime.setValue
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.CornerRadius
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.geometry.Size
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.Path
import androidx.compose.ui.input.pointer.pointerInput
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.ui.theme.kern
import java.text.NumberFormat
import java.time.LocalDate
import java.time.format.TextStyle
import java.util.Locale

/**
 * Categorical slots for chart segments, in fixed order (never cycled).
 * Validated for colour-blind separation on Kern's light and dark surfaces;
 * legends always show values, so the light-mode low-contrast slots are labelled.
 */
@Composable
fun series(i: Int): Color {
    val dark = kern.dark
    val light = listOf(0xFF2A78D6, 0xFFEB6834, 0xFF1BAF7A, 0xFFEDA100, 0xFFE87BA4)
    val night = listOf(0xFF3987E5, 0xFFD95926, 0xFF199E70, 0xFFC98500, 0xFFD55181)
    return Color((if (dark) night else light)[i.coerceIn(0, 4)])
}

private val nf = NumberFormat.getIntegerInstance(Locale.getDefault())
fun num(n: Number): String = nf.format(n)

@Composable
fun Panel(title: String, subtitle: String? = null, content: @Composable () -> Unit) {
    val shape = RoundedCornerShape(14.dp)
    Column(
        Modifier.padding(horizontal = 16.dp, vertical = 6.dp).fillMaxWidth().clip(shape)
            .background(kern.surface).border(1.dp, kern.border, shape).padding(16.dp)
    ) {
        Text(title, style = MaterialTheme.typography.titleSmall, color = kern.text)
        if (subtitle != null) Text(subtitle, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        Spacer(Modifier.height(12.dp))
        content()
    }
}

data class Tile(val value: String, val label: String, val sub: String? = null)

/** Headline numbers in a two-column grid. */
@Composable
fun Tiles(tiles: List<Tile>) {
    Column(Modifier.padding(horizontal = 12.dp)) {
        tiles.chunked(2).forEach { row ->
            Row {
                row.forEach { t ->
                    val shape = RoundedCornerShape(14.dp)
                    Column(
                        Modifier.weight(1f).padding(4.dp).clip(shape).background(kern.surface)
                            .border(1.dp, kern.border, shape).padding(14.dp)
                    ) {
                        Text(t.value, style = MaterialTheme.typography.headlineSmall.copy(fontSize = 26.sp), color = kern.text, maxLines = 1)
                        Text(t.label, style = MaterialTheme.typography.bodyMedium, color = kern.text2, maxLines = 1, overflow = TextOverflow.Ellipsis)
                        if (t.sub != null) Text(t.sub, style = MaterialTheme.typography.bodySmall, color = kern.text3, maxLines = 1, overflow = TextOverflow.Ellipsis)
                    }
                }
                if (row.size == 1) Spacer(Modifier.weight(1f))
            }
        }
    }
}

/**
 * One series of bars from a shared baseline. Tap a bar to read its exact value;
 * the hit target is the whole column, wider than the bar.
 */
@Composable
fun Bars(
    values: List<Int>,
    labels: List<String>,
    detail: (Int) -> String,
    height: Int = 120,
    axis: Pair<String, String>? = null,
    highlight: Int? = null,
) {
    val k = kern
    val color = k.accent
    val muted = k.accent.copy(alpha = 0.45f)
    val grid = k.border
    var sel by remember(values) { mutableIntStateOf(-1) }
    val max = (values.maxOrNull() ?: 0).coerceAtLeast(1)
    if (values.none { it > 0 }) {
        Text("Nothing here yet.", style = MaterialTheme.typography.bodyMedium, color = k.text3)
        return
    }
    Column {
        Text(
            if (sel in values.indices) detail(sel) else "Tap a bar for its value",
            style = MaterialTheme.typography.bodySmall,
            color = if (sel in values.indices) k.text else k.text3,
            fontWeight = if (sel in values.indices) FontWeight.Medium else null,
        )
        Spacer(Modifier.height(6.dp))
        Canvas(
            Modifier.fillMaxWidth().height(height.dp).pointerInput(values) {
                detectTapGestures { p ->
                    val i = (p.x / (size.width / values.size.coerceAtLeast(1))).toInt()
                    sel = if (sel == i) -1 else i.coerceIn(0, values.lastIndex)
                }
            }
        ) {
            val n = values.size.coerceAtLeast(1)
            val slot = size.width / n
            val gap = (slot * 0.25f).coerceIn(2.dp.toPx(), 8.dp.toPx())
            val w = slot - gap
            // Recessive gridlines at half and full scale.
            for (f in listOf(0.5f, 1f)) drawLine(grid, Offset(0f, size.height * (1 - f)), Offset(size.width, size.height * (1 - f)), 1f)
            drawLine(grid, Offset(0f, size.height), Offset(size.width, size.height), 2f)
            values.forEachIndexed { i, v ->
                if (v <= 0) return@forEachIndexed
                val h = (size.height * v / max).coerceAtLeast(2.dp.toPx())
                val x = i * slot + gap / 2
                val r = minOf(4.dp.toPx(), w / 2)
                val c = when { i == sel -> k.text; highlight != null && i != highlight -> muted; else -> color }
                // Rounded data end, square at the baseline.
                val path = Path().apply {
                    moveTo(x, size.height)
                    lineTo(x, size.height - h + r)
                    quadraticTo(x, size.height - h, x + r, size.height - h)
                    lineTo(x + w - r, size.height - h)
                    quadraticTo(x + w, size.height - h, x + w, size.height - h + r)
                    lineTo(x + w, size.height)
                    close()
                }
                drawPath(path, c)
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 4.dp)) {
            if (axis != null) {
                Text(axis.first, style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.weight(1f))
                Text(axis.second, style = MaterialTheme.typography.labelSmall, color = k.text3)
            } else labels.forEach {
                Text(it, style = MaterialTheme.typography.labelSmall, color = k.text3, modifier = Modifier.weight(1f), maxLines = 1,
                    textAlign = androidx.compose.ui.text.style.TextAlign.Center)
            }
        }
        Text("max ${num(max)}", style = MaterialTheme.typography.labelSmall, color = k.text3)
    }
}

data class Segment(val label: String, val value: Long, val shown: String = num(value))

/** Parts of a whole: one bar split into categorical segments, with a legend that carries the values. */
@OptIn(ExperimentalLayoutApi::class)
@Composable
fun Stacked(segments: List<Segment>) {
    val parts = segments.filter { it.value > 0 }
    val total = parts.sumOf { it.value }.coerceAtLeast(1)
    val colors = segments.indices.map { series(it) }
    val surface = kern.surface
    Column {
        Canvas(Modifier.fillMaxWidth().height(18.dp)) {
            var x = 0f
            val gap = 2.dp.toPx()
            parts.forEachIndexed { _, s ->
                val i = segments.indexOf(s)
                val w = size.width * s.value / total
                drawRoundRect(colors[i], Offset(x, 0f), Size((w - gap).coerceAtLeast(1f), size.height), CornerRadius(4.dp.toPx()))
                x += w
            }
            if (parts.isEmpty()) drawRoundRect(surface, size = size, cornerRadius = CornerRadius(4.dp.toPx()))
        }
        Spacer(Modifier.height(10.dp))
        FlowRow(horizontalArrangement = Arrangement.spacedBy(14.dp), verticalArrangement = Arrangement.spacedBy(6.dp)) {
            segments.forEachIndexed { i, s ->
                Row(verticalAlignment = Alignment.CenterVertically) {
                    Box(Modifier.size(10.dp).clip(RoundedCornerShape(3.dp)).background(colors[i]))
                    Spacer(Modifier.width(6.dp))
                    Text(s.label, style = MaterialTheme.typography.bodySmall, color = kern.text2)
                    Spacer(Modifier.width(4.dp))
                    Text(s.shown, style = MaterialTheme.typography.bodySmall, color = kern.text, fontWeight = FontWeight.Medium)
                    Text(" · ${(100 * s.value / total)}%", style = MaterialTheme.typography.bodySmall, color = kern.text3)
                }
            }
        }
    }
}

/** A ranked list: label, a thin magnitude bar, the exact value. */
@Composable
fun Ranked(items: List<Pair<String, Int>>, onClick: ((Int) -> Unit)? = null) {
    val max = (items.maxOfOrNull { it.second } ?: 1).coerceAtLeast(1)
    Column(verticalArrangement = Arrangement.spacedBy(8.dp)) {
        items.forEachIndexed { i, (label, v) ->
            Column(Modifier.fillMaxWidth().then(if (onClick != null) Modifier.clickable { onClick(i) } else Modifier)) {
                Row {
                    Text(label, style = MaterialTheme.typography.bodyMedium, color = kern.text, modifier = Modifier.weight(1f), maxLines = 1, overflow = TextOverflow.Ellipsis)
                    Text(num(v), style = MaterialTheme.typography.bodyMedium, color = kern.text, fontWeight = FontWeight.Medium)
                }
                Spacer(Modifier.height(4.dp))
                Box(Modifier.fillMaxWidth().height(6.dp).clip(RoundedCornerShape(3.dp)).background(kern.surface2)) {
                    Box(Modifier.fillMaxWidth(v.toFloat() / max).height(6.dp).clip(RoundedCornerShape(3.dp)).background(kern.accent))
                }
            }
        }
    }
}

/** Calendar heatmap, weeks as columns; one hue, darker = more. Tap a day to read it. */
@Composable
fun Heatmap(counts: Map<String, Int>, weeks: Int = 26, unit: String = "reviews") {
    val k = kern
    val today = LocalDate.now()
    val start = today.minusDays(((weeks - 1) * 7 + (today.dayOfWeek.value - 1)).toLong())
    val max = (counts.values.maxOrNull() ?: 1).coerceAtLeast(1)
    var sel by remember { mutableStateOf<LocalDate?>(null) }
    Column {
        Text(
            sel?.let { "${it.dayOfWeek.getDisplayName(TextStyle.SHORT, Locale.getDefault())} $it · ${num(counts[it.toString()] ?: 0)} $unit" } ?: "Tap a day",
            style = MaterialTheme.typography.bodySmall, color = if (sel != null) k.text else k.text3,
        )
        Spacer(Modifier.height(6.dp))
        Canvas(
            Modifier.fillMaxWidth().aspectRatio(weeks / 7f).pointerInput(Unit) {
                detectTapGestures { p ->
                    val cell = size.width / weeks.toFloat()
                    val w = (p.x / cell).toInt(); val d = (p.y / cell).toInt().coerceIn(0, 6)
                    val day = start.plusDays((w * 7 + d).toLong())
                    sel = if (day.isAfter(today)) null else day
                }
            }
        ) {
            val cell = size.width / weeks
            val gap = 2.dp.toPx()
            for (w in 0 until weeks) for (d in 0 until 7) {
                val day = start.plusDays((w * 7 + d).toLong())
                if (day.isAfter(today)) continue
                val n = counts[day.toString()] ?: 0
                val c = if (n == 0) k.surface2 else k.accent.copy(alpha = 0.3f + 0.7f * n / max)
                drawRoundRect(c, Offset(w * cell, d * cell), Size(cell - gap, cell - gap), CornerRadius(cell * 0.2f))
                if (day == sel) drawRoundRect(k.text, Offset(w * cell, d * cell), Size(cell - gap, cell - gap), CornerRadius(cell * 0.2f),
                    style = androidx.compose.ui.graphics.drawscope.Stroke(2.dp.toPx()))
            }
        }
        Row(Modifier.fillMaxWidth().padding(top = 6.dp), verticalAlignment = Alignment.CenterVertically) {
            Text("Less", style = MaterialTheme.typography.labelSmall, color = k.text3)
            Spacer(Modifier.width(6.dp))
            listOf(0f, 0.3f, 0.55f, 0.8f, 1f).forEach { a ->
                Box(Modifier.padding(horizontal = 1.dp).size(10.dp).clip(RoundedCornerShape(2.dp)).background(if (a == 0f) k.surface2 else k.accent.copy(alpha = a)))
            }
            Spacer(Modifier.width(6.dp))
            Text("More", style = MaterialTheme.typography.labelSmall, color = k.text3)
        }
    }
}

/** Label + value rows for the long tail of facts. */
@Composable
fun Facts(rows: List<Pair<String, String>>) {
    Column {
        rows.forEachIndexed { i, (l, v) ->
            if (i > 0) app.kern.ui.components.Divider()
            Row(Modifier.fillMaxWidth().padding(vertical = 9.dp)) {
                Text(l, style = MaterialTheme.typography.bodyMedium, color = kern.text2, modifier = Modifier.weight(1f))
                Text(v, style = MaterialTheme.typography.bodyMedium, color = kern.text, fontWeight = FontWeight.Medium, maxLines = 1, overflow = TextOverflow.Ellipsis)
            }
        }
    }
}
