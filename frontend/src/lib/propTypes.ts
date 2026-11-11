import {
	AtSign, Calendar, CalendarClock, CircleDot, Clock, Hash, Link, List, ListChecks, Phone, Sigma,
	SquareCheck, Star, Text, ArrowUpRight, Search
} from '@lucide/svelte';
import type { Component } from 'svelte';
import type { PropType } from './types.ts';

export const PROP_TYPES: [PropType, string][] = [
	['text', 'Text'], ['number', 'Number'], ['boolean', 'Checkbox'], ['date', 'Date'], ['url', 'URL'],
	['select', 'Select'], ['multi_select', 'Multi-select'], ['relation', 'Relation'], ['rating', 'Rating']
];

export const DB_PROP_TYPES: [PropType, string][] = [
	['text', 'Text'], ['number', 'Number'], ['boolean', 'Checkbox'], ['date', 'Date'],
	['url', 'URL'], ['email', 'Email'], ['phone', 'Phone'], ['select', 'Select'],
	['multi_select', 'Multi-select'], ['status', 'Status'], ['relation', 'Relation'],
	['rollup', 'Rollup'], ['formula', 'Formula'], ['rating', 'Rating'],
	['created_time', 'Created time'], ['last_edited_time', 'Last edited time']
];

export const COMPUTED = new Set<PropType>(['rollup', 'formula', 'created_time', 'last_edited_time']);

export const PROP_ICONS: Record<PropType, Component<any>> = {
	text: Text, number: Hash, boolean: SquareCheck, date: Calendar, url: Link, email: AtSign,
	phone: Phone, select: CircleDot, multi_select: List, status: ListChecks, relation: ArrowUpRight,
	rating: Star, rollup: Search, formula: Sigma, created_time: Clock, last_edited_time: CalendarClock
};

export const ROLLUP_FNS: [string, string][] = [
	['show', 'Show original'], ['count', 'Count all'], ['count_values', 'Count values'],
	['count_unique', 'Count unique'], ['count_empty', 'Count empty'], ['count_not_empty', 'Count not empty'],
	['percent_empty', 'Percent empty'], ['percent_not_empty', 'Percent not empty'],
	['sum', 'Sum'], ['average', 'Average'], ['median', 'Median'], ['min', 'Min'], ['max', 'Max'],
	['range', 'Range'], ['checked', 'Checked'], ['unchecked', 'Unchecked'],
	['percent_checked', 'Percent checked'], ['earliest', 'Earliest date'], ['latest', 'Latest date']
];
