import { getContext, setContext } from 'svelte';
import type { EditorDoc } from './doc.svelte';

export interface EditorCtx {
	doc: EditorDoc;
	/** Id of a block that was just inserted and should open its setup UI. */
	fresh: { id: string | null };
	startDrag(id: string, e: DragEvent): void;
	blockMenu(at: MouseEvent | Element, id: string): void;
	uploadInto(id: string, file: File): Promise<void>;
}

const KEY = Symbol('kern-editor');
export const setEditor = (ctx: EditorCtx) => setContext(KEY, ctx);
export const getEditor = () => getContext<EditorCtx>(KEY);
