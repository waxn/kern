<script lang="ts">
	let { onpick, onclose, x, y }: { onpick: (emoji: string) => void; onclose: () => void; x: number; y: number } = $props();

	const groups: [string, string][] = [
		['Objects', '📄 📝 📓 📔 📕 📗 📘 📙 📚 📖 🗂️ 📁 📂 🗃️ 📌 📎 ✏️ 🖊️ 🔖 🏷️ 💡 🔑 🔒 🧰 🔧 ⚙️ 🧪 🔬 🔭 💻 🖥️ 📱 📷 🎧 🎹 🎨 🎬 🧩 🎲 🏆'],
		['Symbols', '⭐ ✨ 🔥 ⚡ 💎 🎯 ✅ ❌ ❓ ❗ 💬 💭 ♻️ 🔗 📍 🚩 ⏰ 📅 🧭 🗺️ ❤️ 🧡 💛 💚 💙 💜 🖤 🤍 🔴 🟠 🟡 🟢 🔵 🟣 ⚫ ⚪'],
		['Nature', '🌱 🌿 🍀 🌳 🌲 🌵 🌸 🌻 🍂 🍄 🌍 🌙 ☀️ ⛅ 🌧️ ❄️ 🌊 ⛰️ 🐦 🦉 🐝 🦋 🐢 🐟 🐈 🐕 🦊 🐻'],
		['Life', '🏠 🏢 🏫 🏥 🚀 ✈️ 🚗 🚲 🍎 🍞 ☕ 🍷 🏃 🧘 💪 🧠 👤 👥 👋 🙏 💰 💳 📈 📉 📊 🧾 🛒 🎁 🎓 🩺']
	];
	let custom = $state('');
	let el = $state<HTMLElement>();
	let pos = $state({ x: 0, y: 0 });

	$effect(() => {
		if (!el) return;
		const r = el.getBoundingClientRect();
		pos = { x: Math.max(8, Math.min(x, innerWidth - r.width - 8)), y: Math.max(8, Math.min(y, innerHeight - r.height - 8)) };
	});
</script>

<!-- svelte-ignore a11y_no_static_element_interactions -->
<div class="backdrop" onmousedown={onclose}></div>
<div class="picker popover" bind:this={el} style:left="{pos.x}px" style:top="{pos.y}px">
	<div class="top">
		<input class="input" placeholder="Paste any emoji…" bind:value={custom} maxlength="8"
			onkeydown={(e) => { if (e.key === 'Enter' && custom.trim()) onpick(custom.trim()); if (e.key === 'Escape') onclose(); }} />
		<button class="btn ghost" onclick={() => onpick('')}>Remove</button>
	</div>
	<div class="scroll">
		{#each groups as [name, list] (name)}
			<div class="menu-heading">{name}</div>
			<div class="grid">
				{#each list.split(' ') as e (e)}
					<button onclick={() => onpick(e)}>{e}</button>
				{/each}
			</div>
		{/each}
	</div>
</div>

<style>
	.backdrop { position: fixed; inset: 0; z-index: 900; }
	.picker { position: fixed; z-index: 901; width: 316px; padding: 8px; }
	.top { display: flex; gap: 6px; margin-bottom: 4px; }
	.top .input { flex: 1; }
	.scroll { max-height: 260px; overflow-y: auto; }
	.grid { display: grid; grid-template-columns: repeat(10, 1fr); }
	.grid button { height: 30px; border-radius: 4px; font-size: 18px; line-height: 1; }
	.grid button:hover { background: var(--hover); }
</style>
