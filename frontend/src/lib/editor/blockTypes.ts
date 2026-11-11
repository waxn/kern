import {
	Bookmark, CircleDot, Heading1, Heading2, Heading3, Image, Lightbulb, List, ListCollapse,
	ListOrdered, Minus, Music, Paperclip, Pilcrow, Quote, Sigma, SquareCheck, SquareCode, Table, Video,
	Database, FileSymlink, Kanban, Repeat, Sparkles, TextQuote
} from '@lucide/svelte';
import type { Component } from 'svelte';
import type { BlockType } from '#lib/types.ts';

/** Blocks whose content is rich inline text. */
export const TEXT_TYPES = new Set<BlockType>([
	'paragraph', 'h1', 'h2', 'h3', 'bullet', 'numbered', 'todo', 'toggle', 'quote', 'callout'
]);
/** Blocks that cannot contain nested blocks. */
export const LEAF_TYPES = new Set<BlockType>([
	'divider', 'code', 'equation', 'table', 'image', 'video', 'audio', 'file', 'bookmark', 'embed', 'database'
]);
export const MEDIA_TYPES = new Set<BlockType>(['image', 'video', 'audio', 'file']);
/** Pressing Enter continues these with a block of the same type. */
export const CONTINUE_TYPES = new Set<BlockType>(['bullet', 'numbered', 'todo', 'toggle']);

export interface BlockSpec {
	type: BlockType;
	label: string;
	hint: string;
	icon: Component<any>;
	keywords: string;
	group: 'Basic' | 'Media' | 'Advanced' | 'Inline';
	shortcut?: string;
	inline?: 'math';
	ai?: boolean;
	props?: Record<string, any>;
}

export const BLOCK_SPECS: BlockSpec[] = [
	{ type: 'paragraph', label: 'Ask AI', hint: 'Write, summarize or brainstorm · or type “/ ”', icon: Sparkles, keywords: 'ai assistant ask write generate summarize', group: 'Basic', ai: true },
	{ type: 'paragraph', label: 'Text', hint: 'Plain paragraph', icon: Pilcrow, keywords: 'text paragraph plain', group: 'Basic' },
	{ type: 'h1', label: 'Heading 1', hint: 'Large section heading', icon: Heading1, keywords: 'h1 heading1 title', group: 'Basic', shortcut: '#' },
	{ type: 'h2', label: 'Heading 2', hint: 'Medium section heading', icon: Heading2, keywords: 'h2 heading2 subtitle', group: 'Basic', shortcut: '##' },
	{ type: 'h3', label: 'Heading 3', hint: 'Small section heading', icon: Heading3, keywords: 'h3 heading3', group: 'Basic', shortcut: '###' },
	{ type: 'bullet', label: 'Bulleted list', hint: 'Simple bullet point', icon: List, keywords: 'bullet unordered list ul', group: 'Basic', shortcut: '-' },
	{ type: 'numbered', label: 'Numbered list', hint: 'Ordered list item', icon: ListOrdered, keywords: 'numbered ordered list ol', group: 'Basic', shortcut: '1.' },
	{ type: 'todo', label: 'Checklist', hint: 'Item with a checkbox', icon: SquareCheck, keywords: 'todo task checkbox checklist', group: 'Basic', shortcut: '[]' },
	{ type: 'toggle', label: 'Toggle list', hint: 'Collapsible content', icon: ListCollapse, keywords: 'toggle collapse fold', group: 'Basic', shortcut: '>' },
	{ type: 'quote', label: 'Quote', hint: 'Quoted text', icon: Quote, keywords: 'quote blockquote citation', group: 'Basic', shortcut: '"' },
	{ type: 'callout', label: 'Callout', hint: 'Highlighted note', icon: Lightbulb, keywords: 'callout note info warning tip', group: 'Basic' },
	{ type: 'divider', label: 'Divider', hint: 'Horizontal rule', icon: Minus, keywords: 'divider separator hr line rule', group: 'Basic', shortcut: '---' },
	{ type: 'code', label: 'Code', hint: 'Monospaced code block', icon: SquareCode, keywords: 'code snippet pre', group: 'Advanced', shortcut: '```' },
	{ type: 'equation', label: 'Equation', hint: 'Block-level LaTeX math', icon: Sigma, keywords: 'equation math latex katex formula', group: 'Advanced' },
	{ type: 'paragraph', label: 'Inline equation', hint: 'LaTeX math inside text', icon: CircleDot, keywords: 'inline equation math latex', group: 'Inline', inline: 'math' },
	{ type: 'table', label: 'Table', hint: 'Simple grid of cells', icon: Table, keywords: 'table grid rows columns', group: 'Advanced' },
	{ type: 'image', label: 'Image', hint: 'Upload or link an image', icon: Image, keywords: 'image picture photo img', group: 'Media' },
	{ type: 'video', label: 'Video', hint: 'Upload or link a video', icon: Video, keywords: 'video movie mp4', group: 'Media' },
	{ type: 'audio', label: 'Audio', hint: 'Upload or link audio', icon: Music, keywords: 'audio sound music mp3', group: 'Media' },
	{ type: 'file', label: 'File', hint: 'Attach any file', icon: Paperclip, keywords: 'file attachment upload pdf document', group: 'Media' },
	{ type: 'bookmark', label: 'Bookmark', hint: 'Saved web link', icon: Bookmark, keywords: 'bookmark link url web', group: 'Media' },
	{ type: 'database', label: 'Database', hint: 'Table, board, calendar, gallery or list', icon: Database, keywords: 'database table board kanban calendar gallery list linked view', group: 'Advanced' },
	{ type: 'database', label: 'Kanban board', hint: 'Cards in columns, each one a page for notes', icon: Kanban, keywords: 'kanban board cards columns todo trello', group: 'Advanced', props: { preset: 'kanban' } },
	{ type: 'embed', label: 'Embed page', hint: 'Show another page here, kept in sync', icon: FileSymlink, keywords: 'embed page transclude portal document', group: 'Advanced', props: { kind: 'doc' } },
	{ type: 'embed', label: 'Embed block', hint: 'Mirror a block from any page', icon: TextQuote, keywords: 'embed block transclude portal mirror reference', group: 'Advanced', props: { kind: 'block' } },
	{ type: 'synced', label: 'Synced block', hint: 'Content you can mirror on other pages', icon: Repeat, keywords: 'synced sync block mirror', group: 'Advanced' }
];

export const TURN_INTO = BLOCK_SPECS.filter((s) => TEXT_TYPES.has(s.type) && !s.inline).concat(
	BLOCK_SPECS.filter((s) => s.type === 'code')
);

export const PLACEHOLDERS: Partial<Record<BlockType, string>> = {
	h1: 'Heading 1', h2: 'Heading 2', h3: 'Heading 3', quote: 'Quote', callout: 'Callout',
	toggle: 'Toggle', todo: 'To-do', bullet: 'List', numbered: 'List'
};

export const COLORS = ['gray', 'brown', 'orange', 'yellow', 'green', 'blue', 'purple', 'pink', 'red'];
export const HIGHLIGHTS = ['yellow', 'orange', 'green', 'blue', 'purple', 'pink', 'red', 'gray'];
