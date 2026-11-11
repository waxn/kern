import type { FileRef } from './kind.ts';

/** The one media file that is playing. Its player lives in the root layout, so playback
 *  continues while you browse other files or pages (minimised to a small dock). */
class Player {
	file = $state<FileRef | null>(null);
	mode = $state<'full' | 'mini'>('full');
	/** Bumped on every open so re-opening the same file expands the player again. */
	seq = $state(0);

	open(f: FileRef) {
		this.file = f;
		this.mode = 'full';
		this.seq++;
	}
	minimize() {
		this.mode = 'mini';
	}
	expand() {
		this.mode = 'full';
	}
	close() {
		this.file = null;
	}
}

export const player = new Player();
