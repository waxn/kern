package app.kern.ui.components

import androidx.compose.foundation.layout.size
import androidx.compose.material3.Icon
import androidx.compose.runtime.Composable
import androidx.compose.runtime.remember
import androidx.compose.ui.Modifier
import androidx.compose.ui.geometry.Offset
import androidx.compose.ui.graphics.Brush
import androidx.compose.ui.graphics.Color
import androidx.compose.ui.graphics.lerp
import androidx.compose.ui.graphics.vector.ImageVector
import androidx.compose.ui.graphics.vector.PathParser
import androidx.compose.ui.unit.Dp
import androidx.compose.ui.unit.dp
import app.kern.ui.theme.kern

private const val SPARKLE_NAME = "KernSparkle"

// Same four-pointed star as the web's lib/ai/Sparkle.svelte.
private const val SPARKLE_PATH =
    "M12 1.5c.5 5.6 4.9 10 10.5 10.5-5.6.5-10 4.9-10.5 10.5C11.5 16.9 7.1 12.5 1.5 12 7.1 11.5 11.5 7.1 12 1.5Z"

/** The Intelligence mark: web's diagonal accent → pink-ish → purple gradient, built from the current theme. */
val sparkleIcon: ImageVector
    @Composable get() {
        val k = kern
        return remember(k.accent, k.pink, k.purple) {
            val brush = Brush.linearGradient(
                0f to k.accent,
                0.55f to lerp(k.pink, k.accent, 0.55f),
                1f to k.purple,
                start = Offset(3f, 3f),
                end = Offset(21f, 21f),
            )
            ImageVector.Builder(SPARKLE_NAME, 24.dp, 24.dp, 24f, 24f)
                .addPath(PathParser().parsePathString(SPARKLE_PATH).toNodes(), fill = brush)
                .build()
        }
    }

/** Tint to hand an `Icon` so the sparkle keeps its gradient; every other icon keeps [fallback]. */
fun ImageVector.tintOr(fallback: Color): Color = if (name == SPARKLE_NAME) Color.Unspecified else fallback

@Composable
fun Sparkle(size: Dp = 16.dp, modifier: Modifier = Modifier) {
    Icon(sparkleIcon, null, tint = Color.Unspecified, modifier = modifier.size(size))
}
