package app.kern.ui.components

import androidx.compose.animation.core.RepeatMode
import androidx.compose.animation.core.animateFloat
import androidx.compose.animation.core.infiniteRepeatable
import androidx.compose.animation.core.rememberInfiniteTransition
import androidx.compose.animation.core.tween
import androidx.compose.foundation.Canvas
import androidx.compose.foundation.background
import androidx.compose.foundation.border
import androidx.compose.foundation.clickable
import androidx.compose.foundation.combinedClickable
import androidx.compose.foundation.layout.Arrangement
import androidx.compose.foundation.layout.Box
import androidx.compose.foundation.layout.Column
import androidx.compose.foundation.layout.PaddingValues
import androidx.compose.foundation.layout.Row
import androidx.compose.foundation.layout.RowScope
import androidx.compose.foundation.layout.Spacer
import androidx.compose.foundation.layout.fillMaxSize
import androidx.compose.foundation.layout.fillMaxWidth
import androidx.compose.foundation.layout.height
import androidx.compose.foundation.layout.heightIn
import androidx.compose.foundation.layout.padding
import androidx.compose.foundation.layout.size
import androidx.compose.foundation.layout.width
import androidx.compose.foundation.layout.widthIn
import androidx.compose.foundation.shape.CircleShape
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.material.icons.Icons
import androidx.compose.material.icons.automirrored.outlined.ArrowBack
import androidx.compose.material.icons.outlined.Description
import androidx.compose.material.icons.outlined.ErrorOutline
import androidx.compose.material.icons.outlined.Storage
import androidx.compose.material.icons.outlined.Dashboard
import androidx.compose.material3.CircularProgressIndicator
import androidx.compose.material3.ExperimentalMaterial3Api
import androidx.compose.material3.HorizontalDivider
import androidx.compose.material3.Icon
import androidx.compose.material3.IconButton
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.OutlinedTextField
import androidx.compose.material3.OutlinedTextFieldDefaults
import androidx.compose.material3.SnackbarHostState
import androidx.compose.material3.Surface
import androidx.compose.material3.Text
import androidx.compose.material3.TextButton
import androidx.compose.material3.TopAppBar
import androidx.compose.material3.TopAppBarDefaults
import androidx.compose.material3.TopAppBarScrollBehavior
import androidx.compose.runtime.Composable
import androidx.compose.runtime.getValue
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.ui.Alignment
import androidx.compose.ui.Modifier
import androidx.compose.ui.draw.clip
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.StrokeCap
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.text.style.TextAlign
import androidx.compose.ui.text.style.TextOverflow
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.data.Doc
import app.kern.ui.theme.kern
import kotlinx.coroutines.CoroutineScope
import kotlinx.coroutines.launch
import java.time.Instant
import java.time.LocalDate
import java.time.OffsetDateTime
import java.time.ZoneId
import java.time.format.DateTimeFormatter
import java.time.temporal.ChronoUnit
import java.util.Locale

class Snack(val host: SnackbarHostState, val scope: CoroutineScope) {
    fun show(msg: String) { scope.launch { host.currentSnackbarData?.dismiss(); host.showSnackbar(msg) } }
    fun error(e: Throwable) = show(e.message ?: "Something went wrong.")
}

val LocalSnack = staticCompositionLocalOf<Snack> { error("no snack") }

/** The Kern mark: a K drawn as a tiny knowledge graph with the kernel glowing at its joint. */
@Composable
fun KernLogo(size: Dp = 28.dp, animated: Boolean = true) {
    val k = kern
    val pulse = if (animated) {
        val t = rememberInfiniteTransition(label = "logo")
        t.animateFloat(0.35f, 0.6f, infiniteRepeatable(tween(2250), RepeatMode.Reverse), label = "halo").value
    } else 0.45f
    Canvas(Modifier.size(size)) {
        val u = this.size.width / 24f
        fun p(x: Float, y: Float) = Offset((x - 4) * u, (y - 4) * u)
        drawLine(k.text, p(10.5f, 7.5f), p(10.5f, 24.5f), 2.6f * u, StrokeCap.Round)
        drawLine(k.text.copy(alpha = 0.7f), p(10.5f, 16f), p(21.6f, 8.3f), 2.2f * u, StrokeCap.Round)
        drawLine(k.text.copy(alpha = 0.7f), p(10.5f, 16f), p(21.6f, 23.7f), 2.2f * u, StrokeCap.Round)
        drawCircle(
            Brush.radialGradient(listOf(k.accent.copy(alpha = pulse + 0.3f), k.accent.copy(alpha = pulse), Color.Transparent), center = p(10.5f, 16f), radius = 6.5f * u),
            radius = 6.5f * u, center = p(10.5f, 16f),
        )
        drawCircle(k.side, radius = 3.9f * u, center = p(10.5f, 16f))
        drawCircle(k.accent, radius = 3.2f * u, center = p(10.5f, 16f))
        drawCircle(k.text, radius = 2.1f * u, center = p(22.2f, 7.8f))
        drawCircle(k.text, radius = 2.1f * u, center = p(22.2f, 24.2f))
    }
}

@OptIn(ExperimentalMaterial3Api::class)
@Composable
fun KTopBar(
    title: String,
    onBack: (() -> Unit)? = null,
    subtitle: String? = null,
    scroll: TopAppBarScrollBehavior? = null,
    actions: @Composable RowScope.() -> Unit = {},
) {
    TopAppBar(
        title = {
            Column {
                Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.titleMedium)
                if (subtitle != null) Text(subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
            }
        },
        navigationIcon = { if (onBack != null) IconButton(onClick = onBack) { Icon(Icons.AutoMirrored.Outlined.ArrowBack, "Back") } },
        actions = actions,
        scrollBehavior = scroll,
        colors = TopAppBarDefaults.topAppBarColors(containerColor = kern.bg, scrolledContainerColor = kern.side),
    )
}

@Composable
fun SectionLabel(text: String, modifier: Modifier = Modifier, trailing: @Composable (() -> Unit)? = null) {
    Row(modifier.fillMaxWidth().padding(start = 20.dp, end = 12.dp, top = 18.dp, bottom = 6.dp), verticalAlignment = Alignment.CenterVertically) {
        Text(text.uppercase(), style = MaterialTheme.typography.labelSmall, color = kern.text3, modifier = Modifier.weight(1f))
        trailing?.invoke()
    }
}

@Composable
fun DocIcon(doc: Doc, size: Dp = 18.dp) = DocIcon(doc.icon, if (doc.database != null) "database" else doc.kind, size)

@Composable
fun DocIcon(icon: String?, kind: String = "page", size: Dp = 18.dp) {
    Box(Modifier.size(size + 4.dp), contentAlignment = Alignment.Center) {
        if (!icon.isNullOrBlank()) Text(icon, fontSize = (size.value * 0.9f).sp, maxLines = 1)
        else Icon(
            when (kind) { "database" -> Icons.Outlined.Storage; "group" -> Icons.Outlined.Dashboard; else -> Icons.Outlined.Description },
            null, Modifier.size(size), tint = kern.text3,
        )
    }
}

@Composable
fun ListRow(
    title: String,
    modifier: Modifier = Modifier,
    subtitle: String? = null,
    leading: @Composable (() -> Unit)? = null,
    trailing: @Composable (() -> Unit)? = null,
    onLongClick: (() -> Unit)? = null,
    onClick: (() -> Unit)? = null,
) {
    Row(
        modifier.fillMaxWidth()
            .then(if (onClick != null || onLongClick != null) Modifier.combinedClickable(onClick = { onClick?.invoke() }, onLongClick = onLongClick) else Modifier)
            .heightIn(min = 48.dp)
            .padding(horizontal = 16.dp, vertical = 8.dp),
        verticalAlignment = Alignment.CenterVertically,
    ) {
        if (leading != null) { leading(); Spacer(Modifier.width(12.dp)) }
        Column(Modifier.weight(1f)) {
            Text(title, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodyLarge, color = kern.text)
            if (!subtitle.isNullOrBlank()) Text(subtitle, maxLines = 1, overflow = TextOverflow.Ellipsis, style = MaterialTheme.typography.bodySmall, color = kern.text3)
        }
        if (trailing != null) { Spacer(Modifier.width(8.dp)); trailing() }
    }
}

@Composable
fun DocRow(doc: Doc, subtitle: String? = null, onLongClick: (() -> Unit)? = null, trailing: @Composable (() -> Unit)? = null, onClick: () -> Unit) =
    ListRow(doc.displayTitle, subtitle = subtitle, leading = { DocIcon(doc) }, trailing = trailing, onLongClick = onLongClick, onClick = onClick)

@Composable
fun Loading(modifier: Modifier = Modifier) {
    Box(modifier.fillMaxSize(), contentAlignment = Alignment.Center) {
        CircularProgressIndicator(Modifier.size(28.dp), strokeWidth = 2.5.dp, color = kern.accent)
    }
}

@Composable
fun EmptyState(icon: ImageVector, title: String, body: String? = null, modifier: Modifier = Modifier, action: Pair<String, () -> Unit>? = null) {
    Column(modifier.fillMaxWidth().padding(horizontal = 32.dp, vertical = 48.dp), horizontalAlignment = Alignment.CenterHorizontally) {
        Box(Modifier.size(56.dp).clip(CircleShape).background(kern.surface2), contentAlignment = Alignment.Center) {
            Icon(icon, null, tint = kern.text3, modifier = Modifier.size(26.dp))
        }
        Spacer(Modifier.height(14.dp))
        Text(title, style = MaterialTheme.typography.titleMedium, color = kern.text, textAlign = TextAlign.Center)
        if (body != null) {
            Spacer(Modifier.height(4.dp))
            Text(body, style = MaterialTheme.typography.bodyMedium, color = kern.text2, textAlign = TextAlign.Center)
        }
        if (action != null) {
            Spacer(Modifier.height(14.dp))
            KButton(action.first, primary = true, onClick = action.second)
        }
    }
}

@Composable
fun ErrorState(message: String, onRetry: () -> Unit) =
    EmptyState(Icons.Outlined.ErrorOutline, "Couldn't load this", message, action = "Try again" to onRetry)

@Composable
fun KButton(text: String, modifier: Modifier = Modifier, primary: Boolean = false, danger: Boolean = false, enabled: Boolean = true, icon: ImageVector? = null, onClick: () -> Unit) {
    val k = kern
    val bg = when { danger -> k.danger; primary -> k.accent; else -> k.surface }
    val fg = when { danger -> Color.White; primary -> k.onAccent; else -> k.text }
    Surface(
        onClick = onClick,
        enabled = enabled,
        shape = RoundedCornerShape(10.dp),
        color = bg.copy(alpha = if (enabled) 1f else 0.5f),
        contentColor = fg,
        // The border belongs to the Surface so it hugs the visible button, not the larger touch target.
        border = if (!primary && !danger) androidx.compose.foundation.BorderStroke(1.dp, k.borderStrong) else null,
        modifier = modifier.height(44.dp),
    ) {
        Row(Modifier.padding(horizontal = 16.dp), verticalAlignment = Alignment.CenterVertically, horizontalArrangement = Arrangement.Center) {
            if (icon != null) { Icon(icon, null, Modifier.size(18.dp)); Spacer(Modifier.width(8.dp)) }
            Text(text, style = MaterialTheme.typography.labelLarge, fontWeight = if (primary || danger) FontWeight.SemiBold else FontWeight.Medium)
        }
    }
}

@Composable
fun KField(
    value: String,
    onChange: (String) -> Unit,
    label: String,
    modifier: Modifier = Modifier,
    singleLine: Boolean = true,
    keyboard: androidx.compose.foundation.text.KeyboardOptions = androidx.compose.foundation.text.KeyboardOptions.Default,
    actions: androidx.compose.foundation.text.KeyboardActions = androidx.compose.foundation.text.KeyboardActions.Default,
    visual: androidx.compose.ui.text.input.VisualTransformation = androidx.compose.ui.text.input.VisualTransformation.None,
    placeholder: String? = null,
    minLines: Int = 1,
) {
    val k = kern
    OutlinedTextField(
        value = value, onValueChange = onChange, label = { Text(label) }, singleLine = singleLine, minLines = minLines,
        placeholder = placeholder?.let { { Text(it, color = k.text3) } },
        keyboardOptions = keyboard, keyboardActions = actions, visualTransformation = visual,
        shape = RoundedCornerShape(10.dp),
        colors = OutlinedTextFieldDefaults.colors(
            focusedBorderColor = k.accent, unfocusedBorderColor = k.borderStrong, focusedLabelColor = k.accent,
            unfocusedLabelColor = k.text2, cursorColor = k.accent, focusedContainerColor = k.bg, unfocusedContainerColor = k.bg,
        ),
        modifier = modifier.fillMaxWidth(),
    )
}

@Composable
fun Pill(text: String, color: Color, modifier: Modifier = Modifier, onClick: (() -> Unit)? = null) {
    val k = kern
    Text(
        text,
        style = MaterialTheme.typography.labelMedium,
        color = color,
        maxLines = 1,
        modifier = modifier.clip(RoundedCornerShape(6.dp)).background(k.tint(color))
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(horizontal = 7.dp, vertical = 2.dp),
    )
}

@Composable
fun Card(modifier: Modifier = Modifier, onClick: (() -> Unit)? = null, padding: PaddingValues = PaddingValues(16.dp), content: @Composable () -> Unit) {
    val k = kern
    val shape = RoundedCornerShape(14.dp)
    Box(
        modifier.clip(shape).background(k.surface).border(1.dp, k.border, shape)
            .then(if (onClick != null) Modifier.clickable(onClick = onClick) else Modifier)
            .padding(padding)
    ) { content() }
}

@Composable
fun Divider(modifier: Modifier = Modifier) = HorizontalDivider(modifier, color = kern.border)

@Composable
fun TextAction(text: String, onClick: () -> Unit) = TextButton(onClick = onClick) { Text(text, color = kern.accent, style = MaterialTheme.typography.labelLarge) }

@Composable
fun Dot(color: Color, size: Dp = 8.dp) = Box(Modifier.size(size).clip(CircleShape).background(color))

@Composable
fun Narrow(content: @Composable () -> Unit) = Box(Modifier.fillMaxWidth(), contentAlignment = Alignment.TopCenter) {
    Box(Modifier.widthIn(max = 720.dp)) { content() }
}

// ------------------------------------------------------------------ dates

fun parseInstant(s: String?): Instant? = s?.let {
    runCatching { OffsetDateTime.parse(it).toInstant() }.getOrNull()
        ?: runCatching { Instant.parse(it) }.getOrNull()
}

fun ago(s: String?): String {
    val t = parseInstant(s) ?: return ""
    val mins = ChronoUnit.MINUTES.between(t, Instant.now())
    return when {
        mins < 1 -> "just now"
        mins < 60 -> "${mins}m ago"
        mins < 60 * 24 -> "${mins / 60}h ago"
        mins < 60 * 24 * 7 -> "${mins / 1440}d ago"
        else -> DateTimeFormatter.ofPattern("d MMM yyyy", Locale.getDefault()).format(t.atZone(ZoneId.systemDefault()))
    }
}

fun dueLabel(due: String?): String {
    if (due == null) return ""
    val d = runCatching { LocalDate.parse(due.take(10)) }.getOrNull() ?: return due
    val today = LocalDate.now()
    val diff = ChronoUnit.DAYS.between(today, d)
    return when {
        diff == 0L -> "Today"
        diff == 1L -> "Tomorrow"
        diff == -1L -> "Yesterday"
        diff in 2..6 -> d.dayOfWeek.getDisplayName(java.time.format.TextStyle.FULL, Locale.getDefault())
        d.year == today.year -> DateTimeFormatter.ofPattern("d MMM", Locale.getDefault()).format(d)
        else -> DateTimeFormatter.ofPattern("d MMM yyyy", Locale.getDefault()).format(d)
    }
}

fun bytes(n: Long): String = when {
    n < 1024 -> "$n B"
    n < 1024 * 1024 -> "%.1f KB".format(n / 1024.0)
    n < 1024L * 1024 * 1024 -> "%.1f MB".format(n / 1048576.0)
    else -> "%.2f GB".format(n / 1073741824.0)
}

@Composable
fun rememberSnack(): Snack = LocalSnack.current
