<script lang="ts">
	import { goto } from '$app/navigation';
	import { api } from '#lib/api.ts';

	export interface ModelInfo {
		name: string;
		description?: string;
	}

	interface ModelOption {
		model: string;
		info?: ModelInfo;
	}

	let config = $state<AiConfig | null>(null);
	let detectedModels = $state<string[]>([]);
	const detecting = $state(false);
	let showDropdown = $state(false);
	let loading = $state<string | null>(null);

	function toggleDropdown() {
		showDropdown = !showDropdown;
	}

	async function loadModels() {
		if (!config?.base_url || detecting) return;
		try {
			detecting = true;
			const result = await api.post<{ models: string[] }>('/ai/models', {
				provider: config.provider,
				base_url: config.base_url,
				api_key: ''
			});
			if (result.models) {
				detectedModels = result.models;
			}
		} catch {
			// Silently fail - models are optional
		} finally {
			detecting = false;
		}
	}

	function selectModel(model: string) {
		if (config) {
			config.model = model;
			onSave?.(model);
		}
		showDropdown = false;
	}

	function reset() {
		showDropdown = false;
		detectedModels = [];
		detecting = false;
	}

	export interface ModelSelectorProps {
		config?: AiConfig | null;
		onSave?: (model: string) => void;
		onreset?: () => void;
	}

	export let providerOptions = $props<Record<string, ModelInfo>>({
		anthropic: { name: 'Anthropic', description: 'Claude' },
		gemini: { name: 'Google' },
		openai: { name: 'OpenAI' },
		ollama: { name: 'Ollama' },
		lmstudio: { name: 'LM Studio' },
		custom: { name: 'Custom' }
	});

	export let apiEndpoint = $props<string>('/ai/models');
</script>

<div class="model-selector" class:open={showDropdown}>
	<button 
		class="model-btn" 
		type="button" 
		@click={toggleDropdown}
		disabled={!config || !config.base_url}
		title="Select a model to use for this intelligence feature"
	>
		{#if config?.model}
			<span class="model-name">{config.model}</span>
		{:else}
			<span class="faint">Default</span>
		{/if}
		<ChevronDown size={12} />
	</button>

	{#if showDropdown && config?.base_url}
		<div class="dropdown">
			{#if detecting}
				<div class="loading">Detecting models…</div>
			{:else if detectedModels.length === 0}
				<div class="no-models">No models found. You can still paste any model name manually.</div>
			{/if}

			{#each [...new Set([...detectedModels] as string[])] as model (model)}
				<button 
					class="dropdown-item" 
					type="button" 
					role="menuitemradio"
					aria-selected={config?.model === model}
					@click={() => selectModel(model)}
				>
					{model}{#if config?.model === model}<ChevronRight size={10} />{/if}
				</button>
			{/each}

			<div class="dropdown-separator"></div>

			<div class="custom-model">
				<input 
					class="model-input" 
					type="text" 
					placeholder="or paste a model name" 
					value={config?.model || ''}
					onkeydown={(e) => {
						if (e.key === 'Enter' && e.currentTarget.value.trim()) {
							const input = e.currentTarget;
							config?.model = input.value.trim();
							onSave?.(input.value.trim());
							input.value = '';
						}
					}}
				/>
			</div>

			<div class="dropdown-actions">
				<button 
					class="btn ghost sm" 
					type="button" 
					disabled={!!config?.base_url || !!config?.model}
					@click={() => loadModels()}
				>
					{detecting ? 'Detecting…' : 'Detect models'}
				</button>
			</div>

			<div class="dropdown-close" @click={toggleDropdown}>×</div>
		</div>
	{/if}
</div>

<style>
	.model-selector {
		position: relative;
		display: inline-flex;
		align-items: center;
		gap: 6px;
		font-size: 12px;
	}

	.model-btn {
		display: inline-flex;
		align-items: center;
		gap: 4px;
		height: 24px;
		padding: 0 8px;
		border-radius: 12px;
		border: 1px solid var(--border);
		background: var(--bg);
		color: var(--text-3);
		font-size: 11.5px;
		cursor: pointer;
		min-width: 140px;
		justify-content: space-between;
		transition: all .12s var(--ease);
	}

	.model-btn:hover {
		background: var(--hover);
		color: var(--text);
		border-color: color-mix(in srgb, var(--accent) 45%, var(--border));
	}

	.model-btn:disabled {
		cursor: default;
		opacity: 0.35;
	}

	.model-name {
		min-width: -webkit-fill-available;
		overflow: hidden;
		text-overflow: ellipsis;
		white-space: nowrap;
	}

	.faint {
		color: var(--text-3);
	}

	.dropdown {
		position: absolute;
		top: 100%;
		right: 0;
		margin-top: 4px;
		width: min-content;
		max-width: 280px;
		padding: 8px;
		border-radius: 10px;
		border: 1px solid var(--border-strong);
		background: var(--surface);
		box-shadow: 0 4px 12px color-mix(in srgb, var(--bg) 90%, black), 0 2px 8px rgba(0, 0, 0, 0.15);
		font-size: 12px;
		z-index: 100;
		min-height: 42px;
	}

	.loading, .no-models {
		display: block;
		text-align: center;
		padding: 8px;
		font-size: 11.5px;
		color: var(--text-3);
	}

	.no-models {
		font-style: italic;
	}

	.dropdown-item {
		display: flex;
		align-items: center;
		gap: 6px;
		width: 100%;
		height: 28px;
		padding: 0 10px;
		border-radius: 8px;
		color: var(--text-2);
		cursor: pointer;
		text-align: left;
		font-size: 12px;
		transition: background .12s, color .12s;
	}

	.dropdown-item:hover {
		background: var(--hover);
		color: var(--text);
	}

	.dropdown-separator {
		height: 1px;
		margin: 6px 0;
		border: none;
		border-top: 1px dashed var(--border);
	}

	.custom-model {
		display: flex;
		gap: 6px;
		align-items: center;
	}

	.model-input {
		flex: 1;
		height: 28px;
		padding: 0 10px;
		border-radius: 8px;
		border: 1px solid var(--border-strong);
		background: var(--bg);
		color: var(--text);
		font-size: 12px;
		outline: none;
	}

	.model-input:focus {
		border-color: color-mix(in srgb, var(--accent) 55%, var(--border-strong));
		box-shadow: 0 0 0 3px color-mix(in srgb, var(--accent) 12%, transparent);
	}

	.dropdown-actions {
		display: flex;
		gap: 6px;
		margin-top: 8px;
		align-items: center;
	}

	.dropdown-close {
		position: absolute;
		top: -9px;
		right: -9px;
		width: 18px;
		height: 18px;
		display: grid;
		place-items: center;
		border-radius: 50%;
		border: none;
		background: var(--surface);
		color: var(--text-3);
		cursor: pointer;
		font-size: 14px;
		line-height: 1;
		padding: 0;
		align-self: flex-start;
	}

	.dropdown-close:hover {
		background: var(--hover);
		color: var(--text);
	}

	.open .dropdown {
		animation: fade 0.1s ease-out;
	}

	@keyframes fade {
		from { opacity: 0; transform: translateY(-4px); }
		to { opacity: 1; transform: translateY(0); }
	}

	@media (max-width: 640px) {
		.model-btn {
			min-width: 120px;
		}

		.dropdown {
			max-width: calc(100vw - 40px);
		}
	}
</style>
