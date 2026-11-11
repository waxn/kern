// KaTeX (JS + CSS) is loaded on first use instead of at startup, so pages
// without math never parse or hold it in memory.
type Katex = typeof import('katex').default;

export const math = $state<{ katex: Katex | null }>({ katex: null });

let loading: Promise<Katex> | null = null;

export function loadKatex(): Promise<Katex> {
	loading ??= Promise.all([import('katex'), import('katex/dist/katex.min.css')]).then(([m]) => (math.katex = m.default));
	return loading;
}
