package app.kern.ui.theme

import androidx.compose.foundation.isSystemInDarkTheme
import androidx.compose.material3.ColorScheme
import androidx.compose.material3.MaterialTheme
import androidx.compose.material3.Shapes
import androidx.compose.material3.Typography
import androidx.compose.material3.darkColorScheme
import androidx.compose.material3.lightColorScheme
import androidx.compose.runtime.Composable
import androidx.compose.runtime.CompositionLocalProvider
import androidx.compose.runtime.Immutable
import androidx.compose.runtime.staticCompositionLocalOf
import androidx.compose.foundation.shape.RoundedCornerShape
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.text.TextStyle
import androidx.compose.ui.text.font.Font
import androidx.compose.ui.text.font.FontFamily
import androidx.compose.ui.text.font.FontVariation
import androidx.compose.ui.text.font.FontWeight
import androidx.compose.ui.unit.dp
import androidx.compose.ui.unit.sp
import app.kern.R
import app.kern.data.Html

/** The same tokens as the web app's app.css. */
@Immutable
data class KernColors(
    val dark: Boolean,
    val bg: Color,
    val side: Color,
    val surface: Color,
    val surface2: Color,
    val hover: Color,
    val active: Color,
    val border: Color,
    val borderStrong: Color,
    val text: Color,
    val text2: Color,
    val text3: Color,
    val accent: Color,
    val onAccent: Color,
    val danger: Color,
    val codeBg: Color,
    val gray: Color, val brown: Color, val orange: Color, val yellow: Color, val green: Color,
    val blue: Color, val purple: Color, val pink: Color, val red: Color,
) {
    fun named(name: String?): Color = when (name?.lowercase()) {
        "gray", "grey", "default" -> gray
        "brown" -> brown; "orange" -> orange; "yellow" -> yellow; "green" -> green
        "blue" -> blue; "purple" -> purple; "pink" -> pink; "red" -> red
        null, "" -> text2
        else -> runCatching { Color(android.graphics.Color.parseColor(name)) }.getOrDefault(text2)
    }

    /** Soft background for a coloured chip, like the web's color-mix with --tint. */
    fun tint(c: Color) = c.copy(alpha = if (dark) 0.18f else 0.14f)

    val palette get() = Html.Palette(
        accent = accent, link = blue, code = text, codeBg = codeBg,
        mark = accent.copy(alpha = 0.28f), tagColor = { named(it.ifBlank { null }).let { c -> if (it.isBlank()) accent else c } }, muted = text2,
    )
}

val DarkKern = KernColors(
    dark = true,
    bg = Color(0xFF0F0F11), side = Color(0xFF131315), surface = Color(0xFF19191C), surface2 = Color(0xFF212125),
    hover = Color(0x0EFFFFFF), active = Color(0x17FFFFFF), border = Color(0xFF26262B), borderStrong = Color(0xFF37373D),
    text = Color(0xFFE7E5E0), text2 = Color(0xFFA5A39D), text3 = Color(0xFF706E69),
    accent = Color(0xFFE2A85A), onAccent = Color(0xFF17130C), danger = Color(0xFFE8695F), codeBg = Color(0x12FFFFFF),
    gray = Color(0xFF9B9A97), brown = Color(0xFFC39B82), orange = Color(0xFFE69A5B), yellow = Color(0xFFDCC06A),
    green = Color(0xFF7FBF8F), blue = Color(0xFF74A9E0), purple = Color(0xFFA996E0), pink = Color(0xFFDC8FB9), red = Color(0xFFE8776E),
)

val LightKern = KernColors(
    dark = false,
    bg = Color(0xFFFCFBF9), side = Color(0xFFF5F3EF), surface = Color(0xFFFFFFFF), surface2 = Color(0xFFF1EFEA),
    hover = Color(0x0E1E190F), active = Color(0x171E190F), border = Color(0xFFE6E3DC), borderStrong = Color(0xFFD3CFC6),
    text = Color(0xFF23221F), text2 = Color(0xFF696761), text3 = Color(0xFF9A978F),
    accent = Color(0xFFB4721F), onAccent = Color(0xFFFFFFFF), danger = Color(0xFFC9443A), codeBg = Color(0x111E190F),
    gray = Color(0xFF787774), brown = Color(0xFF8F6248), orange = Color(0xFFC26A1C), yellow = Color(0xFFA37C0A),
    green = Color(0xFF3D8253), blue = Color(0xFF2F74B8), purple = Color(0xFF7557C4), pink = Color(0xFFB84A86), red = Color(0xFFCC4B40),
)

val LocalKern = staticCompositionLocalOf { DarkKern }

@OptIn(androidx.compose.ui.text.ExperimentalTextApi::class)
private fun inter(w: Int) = Font(R.font.inter, FontWeight(w), variationSettings = FontVariation.Settings(FontVariation.weight(w)))

val Inter = FontFamily(inter(400), inter(500), inter(550), inter(600), inter(700))

private fun scheme(k: KernColors): ColorScheme {
    val base = if (k.dark) darkColorScheme() else lightColorScheme()
    return base.copy(
        primary = k.accent, onPrimary = k.onAccent,
        primaryContainer = k.tint(k.accent), onPrimaryContainer = k.text,
        secondary = k.text2, onSecondary = k.bg,
        secondaryContainer = k.active, onSecondaryContainer = k.text,
        tertiary = k.blue,
        background = k.bg, onBackground = k.text,
        surface = k.bg, onSurface = k.text,
        surfaceVariant = k.surface2, onSurfaceVariant = k.text2,
        surfaceContainerLowest = k.bg, surfaceContainerLow = k.side,
        surfaceContainer = k.surface, surfaceContainerHigh = k.surface, surfaceContainerHighest = k.surface2,
        surfaceTint = Color.Transparent,
        outline = k.borderStrong, outlineVariant = k.border,
        error = k.danger, onError = Color.White,
        inverseSurface = k.text, inverseOnSurface = k.bg, inversePrimary = k.accent,
        scrim = Color.Black.copy(alpha = 0.55f),
    )
}

private fun typography(k: KernColors, scale: Float): Typography {
    fun s(size: Int, w: Int = 400, lh: Float = 1.45f, ls: Float = 0f) =
        TextStyle(fontFamily = Inter, fontSize = (size * scale).sp, fontWeight = FontWeight(w), lineHeight = (size * scale * lh).sp, letterSpacing = ls.sp)
    return Typography(
        displaySmall = s(30, 700, 1.2f, -0.6f),
        headlineLarge = s(28, 700, 1.22f, -0.5f),
        headlineMedium = s(24, 650, 1.25f, -0.4f),
        headlineSmall = s(20, 600, 1.3f, -0.25f),
        titleLarge = s(19, 600, 1.3f, -0.2f),
        titleMedium = s(16, 600, 1.35f),
        titleSmall = s(14, 600, 1.35f),
        bodyLarge = s(16, 400, 1.55f),
        bodyMedium = s(14, 400, 1.5f),
        bodySmall = s(12, 400, 1.45f),
        labelLarge = s(14, 550),
        labelMedium = s(12, 550),
        labelSmall = s(11, 600, 1.3f, 0.4f),
    )
}

@Composable
fun KernTheme(theme: String = "system", content: @Composable () -> Unit) {
    val dark = when (theme) { "dark" -> true; "light" -> false; else -> isSystemInDarkTheme() }
    val k = if (dark) DarkKern else LightKern
    CompositionLocalProvider(LocalKern provides k) {
        MaterialTheme(
            colorScheme = scheme(k),
            typography = typography(k, 1f),
            shapes = Shapes(
                extraSmall = RoundedCornerShape(4.dp), small = RoundedCornerShape(6.dp),
                medium = RoundedCornerShape(10.dp), large = RoundedCornerShape(14.dp), extraLarge = RoundedCornerShape(20.dp),
            ),
            content = content,
        )
    }
}

val kern: KernColors @Composable get() = LocalKern.current
