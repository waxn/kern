import type { Component } from 'svelte';

export interface MenuItem {
	label?: string;
	icon?: Component<any>;
	hint?: string;
	danger?: boolean;
	checked?: boolean;
	separator?: boolean;
	heading?: string;
	onSelect?: () => void;
}

interface Toast {
	id: number;
	message: string;
	kind: 'info' | 'error';
	action?: { label: string; run: () => void };
}

interface ConfirmOptions {
	title: string;
	message?: string;
	confirmLabel?: string;
	danger?: boolean;
}

class UI {
	searchOpen = $state(false);
	searchQuery = $state('');
	menu = $state<{ x: number; y: number; items: MenuItem[] } | null>(null);
	toasts = $state<Toast[]>([]);
	confirmState = $state<(ConfirmOptions & { resolve: (ok: boolean) => void }) | null>(null);
	mobileNav = $state(false);
	capturingShortcut = $state(false);
	/** The flashcard editor dialog: an existing note, or initial values for a new one. */
	cardEditor = $state<{ note?: import('../types.ts').Note; init?: Partial<import('../types.ts').Note>; onsaved?: () => void } | null>(null);
	private seq = 0;

	openSearch(query = '') {
		this.searchQuery = query;
		this.searchOpen = true;
	}

	openMenu(at: MouseEvent | { x: number; y: number }, items: MenuItem[]) {
		if (at instanceof MouseEvent) {
			at.preventDefault();
			at.stopPropagation();
			this.menu = { x: at.clientX, y: at.clientY, items };
		} else this.menu = { ...at, items };
	}

	/** Open a menu anchored under an element (for buttons). */
	menuBelow(el: Element, items: MenuItem[]) {
		const r = el.getBoundingClientRect();
		this.menu = { x: r.left, y: r.bottom + 4, items };
	}

	confirm(options: ConfirmOptions): Promise<boolean> {
		return new Promise((resolve) => {
			this.confirmState = { ...options, resolve };
		});
	}

	toast(message: string, opts: { kind?: 'info' | 'error'; action?: Toast['action'] } = {}) {
		const id = ++this.seq;
		this.toasts.push({ id, message, kind: opts.kind ?? 'info', action: opts.action });
		setTimeout(() => this.dismiss(id), opts.action ? 7000 : 4000);
	}

	error(e: unknown) {
		this.toast(e instanceof Error ? e.message : String(e), { kind: 'error' });
	}

	dismiss(id: number) {
		this.toasts = this.toasts.filter((t) => t.id !== id);
	}
}

export const ui = new UI();
