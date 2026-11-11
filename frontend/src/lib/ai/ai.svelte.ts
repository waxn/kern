import { goto } from '$app/navigation';
import { api, ApiError } from '../api.ts';
import { ui } from '../state/ui.svelte.ts';

export interface AiConfig {
	provider: string;
	model: string;
	base_url: string;
	configured: boolean;
	has_key: boolean;
	key_hint: string;
	providers: Record<string, { label: string; base_url: string; model: string; needs_key: boolean }>;
}

class AiState {
	config = $state<AiConfig | null>(null);
	private loading: Promise<void> | null = null;

	async load(force = false) {
		if (this.loading && !force) return this.loading;
		this.loading = api.get<AiConfig>('/ai/config').then((c) => {
			this.config = c;
		}).catch(() => {});
		return this.loading;
	}

	/** True when a provider is set up; otherwise send the user to the AI settings. */
	async ready(): Promise<boolean> {
		if (!this.config) await this.load();
		if (this.config?.configured) return true;
		ui.toast('Set up an AI provider first.');
		goto('/settings?s=ai');
		return false;
	}

	/** Call an AI endpoint; a missing setup sends the user to settings. */
	async run<T>(path: string, body: Record<string, unknown>): Promise<T | null> {
		try {
			return await api.post<T>(path, body);
		} catch (e) {
			if (e instanceof ApiError && e.data?.setup) {
				goto('/settings?s=ai');
			}
			ui.error(e);
			return null;
		}
	}
}

export const ai = new AiState();
