import { describe, expect, it } from 'vitest';
import { renderMarkdown, tableCells } from './md.ts';

describe('chat markdown tables', () => {
	it('renders a pipe table', () => {
		const html = renderMarkdown('Sources:\n\n| Source | Main point |\n|--------|------------|\n| **Cleveland Clinic** | Gas bubbles; no arthritis |\n| Harvard | `a|b` is fine |');
		expect(html).toContain('<table>');
		expect(html).toContain('<th>Source</th><th>Main point</th>');
		expect(html).toContain('<td><strong>Cleveland Clinic</strong></td>');
		expect(html).toContain('<code>a|b</code>');
		expect(html.match(/<tr>/g)?.length).toBe(3);
		expect(html).not.toContain('|---');
	});
	it('handles alignment, missing cells and no outer pipes', () => {
		const html = renderMarkdown('a | b\n:- | --:\n1 |\nAfter the table.');
		expect(html).toContain('<th style="text-align:right">b</th>');
		expect(html).toContain('<td>1</td><td style="text-align:right"></td>');
		expect(html).toContain('<p>After the table.</p>');
	});
	it('escapes cell content and leaves plain pipes in text alone', () => {
		expect(renderMarkdown('| x |\n|---|\n| <img src=x> |')).toContain('&lt;img src=x&gt;');
		expect(renderMarkdown('this | that')).toBe('<p>this | that</p>');
		expect(renderMarkdown('either | or\n---')).not.toContain('<table>');
	});
	it('splits cells', () => {
		expect(tableCells('| a | b \\| c |')).toEqual(['a', 'b | c']);
	});
});
