export interface Doc {
	id: string;
	parent: string | null;
	title: string;
	icon: string;
	cover: string;
	position: number;
	is_favorite: boolean;
	is_archived: boolean;
	trashed_at: string | null;
	created_at: string;
	updated_at: string;
	last_opened_at: string | null;
	entry_of: string | null;
	database: string | null;
	is_template: boolean;
	kind?: 'page' | 'group';
	template_tag: string | null;
	template_db: string | null;
	tags: string[];
	templates_applied?: string[];
	block_count?: number;
	/** Untitled page with no content; hidden from Recent. */
	empty?: boolean;
}

export type BlockType =
	| 'paragraph' | 'h1' | 'h2' | 'h3' | 'bullet' | 'numbered' | 'todo' | 'toggle'
	| 'quote' | 'callout' | 'divider' | 'code' | 'equation' | 'table'
	| 'image' | 'video' | 'audio' | 'file' | 'bookmark' | 'embed' | 'synced' | 'database';

export interface Block {
	id: string;
	parent: string | null;
	position: number;
	type: BlockType;
	html: string;
	props: Record<string, any>;
	collapsed: boolean;
}

export interface Tag {
	id: string;
	name: string;
	color: string;
	doc_count?: number;
}

export type PropType =
	| 'text' | 'number' | 'boolean' | 'date' | 'url' | 'email' | 'phone'
	| 'select' | 'multi_select' | 'status' | 'relation' | 'rating'
	| 'rollup' | 'formula' | 'created_time' | 'last_edited_time';

export interface PropOption {
	id: string;
	name: string;
	color: string;
	group?: 'todo' | 'in_progress' | 'done';
}

export interface PropDef {
	id: string;
	tag: string | null;
	name: string;
	type: PropType;
	options: PropOption[];
	config: Record<string, any>;
	database: string | null;
	position: number;
}

export interface DbInfo {
	id: string;
	page: string;
	title: string;
	icon: string;
	trashed?: boolean;
}

export interface DbRow {
	id: string;
	title: string;
	icon: string;
	cover: string;
	position: number;
	created_at: string;
	updated_at: string;
	values: Record<string, any>;
}

export type ViewType = 'table' | 'board' | 'calendar' | 'gallery' | 'list';

export interface FilterRule {
	prop: string;
	op: string;
	value?: any;
}
export interface FilterGroup {
	op: 'and' | 'or';
	rules: (FilterRule | FilterGroup)[];
}

export interface ViewConfig {
	filter?: FilterGroup;
	sorts?: { prop: string; dir: 'asc' | 'desc' }[];
	visible?: string[];
	hidden?: string[];
	widths?: Record<string, number>;
	group_by?: string;
	collapsed?: string[];
	hide_empty_groups?: boolean;
	date_prop?: string;
	calendar_mode?: 'month' | 'week';
	card_size?: 'small' | 'medium' | 'large';
	cover?: 'page' | 'none';
	wrap?: boolean;
}

export interface DbView {
	id: string;
	name: string;
	type: ViewType;
	config: ViewConfig;
	position: number;
}

export interface DbPayload {
	database: DbInfo;
	properties: PropDef[];
	views: DbView[];
	rows: DbRow[];
	templates: { id: string; title: string; icon: string }[];
}

export interface RefInfo {
	title: string;
	icon?: string;
	color?: string;
	doc?: string;
	doc_title?: string;
	trashed?: boolean;
}

export interface BacklinkGroup {
	doc: { id: string; title: string; icon: string };
	items: { block: string; type: string; html: string; context: string }[];
}

export interface DocPayload {
	document: Doc;
	blocks: Block[];
	refs: Record<string, RefInfo>;
	properties: { defs: PropDef[]; values: Record<string, any> };
	block_backlinks: Record<string, number>;
	block_cards: Record<string, number>;
	block_tasks: Record<string, { id: string; due: string | null; priority: number; recurrence: any; done: boolean }>;
	card_count: number;
	version?: string;
	backlink_count: number;
}

export interface SearchResult {
	kind: 'doc' | 'block' | 'tag' | 'card' | 'task';
	id: string;
	title: string;
	snippet: string;
	doc?: string;
	doc_title?: string;
	icon?: string;
	path?: string[];
	color?: string;
}

export interface Suggestion {
	kind: 'doc' | 'tag' | 'block';
	id: string;
	title: string;
	icon?: string;
	color?: string;
	path?: string[];
	doc?: string;
	doc_title?: string;
}

export type CardKind = 'basic' | 'cloze' | 'concept' | 'occlusion';

export interface Region {
	id: string;
	n: number;
	x: number;
	y: number;
	w: number;
	h: number;
	label: string;
}

export interface Note {
	id: string;
	kind: CardKind;
	front: string;
	back: string;
	image: string;
	regions: Region[];
	deck: string | null;
	document: string | null;
	doc_title: string | null;
	block: string | null;
	auto: boolean;
	active: boolean;
	cards?: Card[];
}

export interface Card {
	id: string;
	note: string;
	kind: CardKind;
	ordinal: number;
	state: 'new' | 'learning' | 'review' | 'relearning';
	due: string | null;
	reps: number;
	lapses: number;
	stability: number;
	difficulty: number;
	suspended: boolean;
	last_review: string | null;
	deck: string | null;
	document: string | null;
	doc_title: string | null;
	block: string | null;
	auto: boolean;
	front: string;
	back: string;
	image?: string;
	regions?: Region[];
	intervals?: Record<string, number>;
}

export interface Deck {
	id: string;
	name: string;
	total?: number;
	new?: number;
	due?: number;
}

export interface CardStats {
	due_today: number;
	due_total: number;
	new_available: number;
	reviewed_today: number;
	time_today_ms: number;
	accuracy_today: number | null;
	accuracy_30d: number | null;
	counts: Record<string, number>;
	suspended: number;
	forecast: number[];
	history: Record<string, number>;
	settings: { new_per_day: number; reviews_per_day: number; retention: number; show_intervals: boolean };
}

export interface Recurrence {
	freq: 'day' | 'week' | 'month' | 'year';
	interval: number;
}

export interface Task {
	id: string;
	title: string;
	description: string;
	done: boolean;
	completed_at: string | null;
	priority: number;
	due: string | null;
	start: string | null;
	recurrence: Recurrence | null;
	document: string | null;
	project: string | null;
	block: string | null;
	tags: string[];
	position: number;
	created_at: string;
	updated_at: string;
}
