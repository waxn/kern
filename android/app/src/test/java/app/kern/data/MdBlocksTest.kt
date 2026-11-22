package app.kern.data

import org.junit.Assert.assertEquals
import org.junit.Assert.assertTrue
import org.junit.Test

class MdBlocksTest {
    @Test fun splitsTextAndTables() {
        val b = markdownBlocks("Sources:\n\n| Source | Main point |\n|--------|------------|\n| **Cleveland Clinic** | Gas bubbles |\n| Harvard | `a|b` ok |\n\nSo, fine.")
        assertEquals(3, b.size)
        assertEquals(MdBlock.Text("Sources:"), b[0])
        val t = b[1] as MdBlock.Table
        assertEquals(listOf("Source", "Main point"), t.head)
        assertEquals(listOf(listOf("**Cleveland Clinic**", "Gas bubbles"), listOf("Harvard", "`a|b` ok")), t.rows)
        assertEquals(MdBlock.Text("So, fine."), b[2])
    }

    @Test fun alignmentAndShortRows() {
        val t = markdownBlocks("a | b | c\n:-- | :-: | --:\n1 |")[0] as MdBlock.Table
        assertEquals(listOf("", "center", "right"), t.align)
        assertEquals(listOf(listOf("1", "", "")), t.rows)
    }

    @Test fun leavesCodeAndPlainPipesAlone() {
        val b = markdownBlocks("```\n| a |\n|---|\n```\nthis | that")
        assertTrue(b.single() is MdBlock.Text)
        assertTrue(markdownBlocks("either | or\n---").single() is MdBlock.Text)
        assertEquals(listOf("a", "b | c"), tableCells("| a | b \\| c |"))
    }
}
