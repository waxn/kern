<script lang="ts">
	import { ArrowRight, BookMarked, Calendar, ChevronRight, CircleCheck, Database, FileText, FolderOpen, GitBranch, Globe, Hash, Layers, Moon, Network, Search, Server, Sun, Trash2, Settings, LayoutTemplate, Archive } from '@lucide/svelte';
	import Logo from '#lib/components/Logo.svelte';
	import { session } from '#lib/state/session.svelte.ts';

	let site = $derived(session.site!);
	let canSignup = $derived(site.signup_mode !== 'closed');
	let dark = $state(document.documentElement.dataset.theme !== 'light');

	function toggleTheme() {
		dark = !dark;
		const t = dark ? 'dark' : 'light';
		document.documentElement.dataset.theme = t;
		try {
			const p = JSON.parse(localStorage.getItem('kern:prefs') ?? '{}');
			localStorage.setItem('kern:prefs', JSON.stringify({ ...p, theme: t }));
		} catch {
			/* storage unavailable */
		}
	}

	// A year of "commits" for the git tile: deterministic so it does not shuffle on every visit.
	const weeks = 24;
	const heat = (() => {
		let s = 7;
		const rnd = () => ((s = (s * 1664525 + 1013904223) % 4294967296) / 4294967296);
		return Array.from({ length: weeks * 7 }, (_, i) => {
			const wk = Math.floor(i / 7);
			const busy = 0.25 + 0.55 * Math.sin((wk / weeks) * Math.PI * 1.6 + 0.4) ** 2;
			const r = rnd();
			return r > busy + 0.1 ? 0 : r > busy * 0.5 ? 1 : r > busy * 0.2 ? 2 : r > busy * 0.05 ? 3 : 4;
		});
	})();

	// Nodes of the little knowledge graph.
	const nodes = [
		{ x: 150, y: 92, r: 9, hub: true }, { x: 66, y: 52, r: 5 }, { x: 52, y: 128, r: 6 }, { x: 118, y: 168, r: 4 },
		{ x: 226, y: 48, r: 6 }, { x: 262, y: 118, r: 5 }, { x: 214, y: 168, r: 7 }, { x: 24, y: 80, r: 3.5 },
		{ x: 300, y: 70, r: 3.5 }, { x: 170, y: 20, r: 4 }, { x: 96, y: 112, r: 3.5 }
	];
	const edges = [[0, 1], [0, 2], [0, 3], [0, 4], [0, 5], [0, 6], [1, 7], [1, 10], [2, 7], [2, 3], [4, 9], [4, 8], [5, 8], [5, 6], [0, 9], [10, 2]];

	const features = [
		{ id: 'outline', icon: Layers, title: 'An outliner that thinks in blocks', text: 'Every line is a block you can nest, move, reference and embed. Type [[ to link a page, # to tag it.' },
		{ id: 'graph', icon: Network, title: 'Everything links back', text: 'Backlinks and a knowledge graph show how your notes connect, without a folder tree getting in the way.' },
		{ id: 'db', icon: Database, title: 'Databases, not just tables', text: 'View the same entries as a table, board, calendar or gallery. Properties, filters, sorting and formulas.' },
		{ id: 'cards', icon: BookMarked, title: 'Flashcards that schedule themselves', text: 'Spaced repetition is built in. Turn any note into cards and review a few minutes a day.' },
		{ id: 'web', icon: Globe, title: 'Pages that stay saved', text: 'Save a page, image or video. Web pages are stored as a full snapshot that still opens when the site changes or disappears.' },
		{ id: 'git', icon: GitBranch, title: 'Your own git server', text: 'Create repositories, push and clone over HTTP, and browse code, commits and contribution stats in the same place as your notes.' }
	];
</script>

<div class="landing">
	<header>
		<div class="bar">
			<a class="brand" href="/" aria-label={site.site_name}><Logo size={22} />{site.site_name}</a>
			<nav>
				<a href="#features">Features</a>
				<a href="#private">Private by design</a>
			</nav>
			<span class="grow"></span>
			<button class="icon-btn" onclick={toggleTheme} aria-label="Switch between light and dark">{#if dark}<Sun size={15} />{:else}<Moon size={15} />{/if}</button>
			<a class="btn ghost" href="/login">Sign in</a>
			{#if canSignup}<a class="btn primary" href="/signup">Create account</a>{/if}
		</div>
	</header>

	<section class="hero">
		<div class="copy">
			<p class="eyebrow">Self-hosted knowledge base</p>
			<h1>Write it down.<br />Link it up.<br /><em>Keep it yours.</em></h1>
			<p class="lede">
				{site.site_name} is a private workspace for notes, databases, flashcards, tasks, bookmarks and code. Everything is connected, and everything runs on a server you control.
			</p>
			<div class="cta">
				<a class="btn primary big" href={canSignup ? '/signup' : '/login'}>{canSignup ? 'Create an account' : 'Sign in'}<ArrowRight size={15} /></a>
				{#if canSignup}<a class="btn big" href="/login">Sign in</a>{/if}
				<a class="more" href="#features">See what's inside<ChevronRight size={14} /></a>
			</div>
		</div>

		<!-- The app, drawn rather than screenshotted. -->
		<div class="win" aria-hidden="true">
			<div class="win-bar">
				<span class="dot"></span><span class="dot"></span><span class="dot"></span>
				<div class="tab on"><FileText size={11} />Reading list</div>
				<div class="tab"><Database size={11} />Projects</div>
				<div class="tab"><Layers size={11} />Spanish</div>
			</div>
			<div class="win-body">
				<aside class="m-side">
					<div class="m-brand"><Logo size={15} />Kern</div>
					<div class="m-row"><Search size={12} />Search<kbd>⌘K</kbd></div>
					<div class="m-row"><CircleCheck size={12} />Tasks<b>4</b></div>
					<div class="m-row"><Layers size={12} />Review<b>12</b></div>
					<div class="m-sec">Pages</div>
					<div class="m-row on"><FileText size={12} />Reading list</div>
					<div class="m-row ind"><ChevronRight size={10} />Notes on Rust</div>
					<div class="m-row ind"><ChevronRight size={10} />Kitchen reno</div>
					<div class="m-row"><Database size={12} />Projects</div>
					<div class="m-row"><FileText size={12} />Weekly review</div>
					<div class="m-foot">
						<div class="m-row"><Network size={12} />Graph</div>
						<div class="m-row"><GitBranch size={12} />Git</div>
						<div class="m-row"><Settings size={12} />Settings</div>
					</div>
				</aside>
				<div class="m-doc">
					<div class="m-crumb">Pages / Reading list</div>
					<div class="m-title">Reading list</div>
					<div class="m-chips"><span class="chip" data-c="blue">#books</span><span class="chip" data-c="green">#2026</span></div>
					<div class="m-blk"><i class="bul"></i><span><b>Currently:</b> <span class="lk">The Pragmatic Programmer</span></span></div>
					<div class="m-blk ind"><i class="bul"></i><span>Chapter 3 on <span class="lk">Plain text</span> changed how I take notes</span></div>
					<div class="m-blk ind"><i class="bul"></i><span class="hl">“Care about your craft.”</span></div>
					<div class="m-blk"><i class="bul"></i><span>Next up</span></div>
					<div class="m-blk ind"><i class="chk"></i><span>Pick a book for the trip</span></div>
					<div class="m-blk ind"><i class="chk on"></i><span class="done">Return library copies</span></div>
					<div class="m-blk"><i class="bul"></i><span>Compare with <span class="lk">Notes on Rust</span> and the <span class="lk">Weekly review</span></span></div>
				</div>
				<aside class="m-panel">
					<div class="m-sec">Backlinks · 3</div>
					<div class="m-bl"><b>Weekly review</b><span>Finished the <span class="lk">Reading list</span></span></div>
					<div class="m-bl"><b>Notes on Rust</b><span>Book is on my <span class="lk">Reading list</span></span></div>
					<div class="m-bl"><b>Projects</b><span>Entry · Reading list</span></div>
					<div class="m-sec">Tags</div>
					<div class="m-chips"><span class="chip" data-c="blue">#books</span><span class="chip" data-c="green">#2026</span></div>
				</aside>
			</div>
		</div>
	</section>

	<section id="features" class="features">
		<div class="head">
			<p class="eyebrow">What's inside</p>
			<h2>One workspace instead of six apps</h2>
			<p>Notes, a database, a flashcard deck, a task list, a read-later queue and a git host share one search, one set of tags and one set of links.</p>
		</div>

		<div class="bento">
			<!-- outliner -->
			<article class="tile t-outline">
				<div class="art">
					<div class="ol"><i class="bul"></i><span>Trip to Lisbon</span></div>
					<div class="ol l1"><i class="bul"></i><span>Flights <em class="chip" data-c="orange">#booked</em></span></div>
					<div class="ol l2"><i class="bul"></i><span>Out Fri 07:40, back Tue</span></div>
					<div class="ol l1"><i class="bul"></i><span>Places to eat</span></div>
					<div class="ol l2"><i class="bul"></i><span>Time Out Market → <span class="lk">Food guide</span></span></div>
					<div class="ol l2 caret"><i class="bul"></i><span>Pastéis de Belém<b></b></span></div>
				</div>
				<h3>{features[0].title}</h3><p>{features[0].text}</p>
			</article>

			<!-- graph -->
			<article class="tile t-graph">
				<div class="art">
					<svg viewBox="0 0 324 188" role="img" aria-label="A small knowledge graph">
						{#each edges as [a, b]}<line x1={nodes[a].x} y1={nodes[a].y} x2={nodes[b].x} y2={nodes[b].y} />{/each}
						{#each nodes as n}
							{#if n.hub}<circle class="halo" cx={n.x} cy={n.y} r={n.r + 11} />{/if}
							<circle class:hub={n.hub} cx={n.x} cy={n.y} r={n.r} />
						{/each}
					</svg>
				</div>
				<h3>{features[1].title}</h3><p>{features[1].text}</p>
			</article>

			<!-- databases -->
			<article class="tile t-db">
				<div class="art">
					<div class="views"><span class="on">Board</span><span>Table</span><span>Calendar</span><span>Gallery</span></div>
					<div class="board">
						<div class="col"><h6><i style="--c: var(--c-gray)"></i>To do<b>3</b></h6><div class="card">Draft proposal<span class="chip" data-c="blue">Work</span></div><div class="card">Book dentist</div><div class="card">Renew passport<span class="chip" data-c="red">Due Fri</span></div></div>
						<div class="col"><h6><i style="--c: var(--c-orange)"></i>Doing<b>2</b></h6><div class="card">Kitchen quotes<span class="chip" data-c="green">Home</span></div><div class="card">Learn some Rust</div></div>
						<div class="col"><h6><i style="--c: var(--c-green)"></i>Done<b>1</b></h6><div class="card muted">Tax return</div></div>
					</div>
				</div>
				<h3>{features[2].title}</h3><p>{features[2].text}</p>
			</article>

			<!-- flashcards -->
			<article class="tile t-cards">
				<div class="art">
					<div class="fc">
						<small>Spanish · 1 of 12</small>
						<div class="q">¿Dónde está la estación?</div>
						<div class="a">Where is the station?</div>
						<div class="rate"><span class="r1">Again<em>1m</em></span><span class="r2">Hard<em>6m</em></span><span class="r3 on">Good<em>3d</em></span><span class="r4">Easy<em>9d</em></span></div>
					</div>
				</div>
				<h3>{features[3].title}</h3><p>{features[3].text}</p>
			</article>

			<!-- web archive -->
			<article class="tile t-web">
				<div class="art">
					<div class="snap">
						<div class="snap-bar"><i></i><span>essays.example.org/small-tools</span><b>Saved copy</b></div>
						<div class="snap-body"><div class="h"></div><div class="l"></div><div class="l s"></div><div class="l"></div><div class="img"></div><div class="l s"></div></div>
					</div>
				</div>
				<h3>{features[4].title}</h3><p>{features[4].text}</p>
			</article>

			<!-- git -->
			<article class="tile t-git">
				<div class="art">
					<div class="clone"><span>$</span> git clone https://{site.site_name.toLowerCase().replace(/[^a-z0-9]+/g, '') || 'kern'}.example/git/<b>site.git</b></div>
					<div class="heat" style="--weeks: {weeks}">
						{#each heat as v}<i data-v={v}></i>{/each}
					</div>
					<div class="legend">Less <i data-v="0"></i><i data-v="1"></i><i data-v="2"></i><i data-v="3"></i><i data-v="4"></i> More</div>
				</div>
				<h3>{features[5].title}</h3><p>{features[5].text}</p>
			</article>
		</div>

		<ul class="also">
			<li><CircleCheck size={15} /><span><b>Tasks</b>with due dates, tags and a Today view</span></li>
			<li><FolderOpen size={15} /><span><b>Files</b>PDFs, Word, audio and video, with version history</span></li>
			<li><LayoutTemplate size={15} /><span><b>Templates</b>for pages, and for every database</span></li>
			<li><Hash size={15} /><span><b>Tags</b>with their own properties</span></li>
			<li><Calendar size={15} /><span><b>Calendar</b>views of any dated entry</span></li>
			<li><Archive size={15} /><span><b>Archive &amp; trash</b>so nothing disappears by accident</span></li>
		</ul>
	</section>

	<section id="private" class="private">
		<div class="p-copy">
			<p class="eyebrow">Private by design</p>
			<h2>Your server. Your data. Your own corner of it.</h2>
			<p>{site.site_name} runs on a machine you control. Each account gets a completely separate workspace: its own database, its own files, its own git repositories. Nobody else, including other people on the same server, can open them.</p>
			<ul>
				<li><b>No tracking.</b> No analytics and no third-party scripts on any page.</li>
				<li><b>One-file backups.</b> Download everything as a single .zip, or restore from one.</li>
				<li><b>Open formats.</b> Export to Markdown, HTML, CSV and JSON whenever you like.</li>
				<li><b>AI only if you want it.</b> Add your own key or a local model; nothing is sent anywhere until you do.</li>
			</ul>
		</div>
		<div class="p-art" aria-hidden="true">
			<svg viewBox="0 0 360 250">
				<rect class="srv" x="8" y="8" width="344" height="234" rx="12" />
				<text class="lbl" x="24" y="34">YOUR SERVER</text>
				<g>
					<rect class="ws" x="24" y="50" width="96" height="176" rx="8" />
					<rect class="ws" x="132" y="50" width="96" height="176" rx="8" />
					<rect class="ws" x="240" y="50" width="96" height="176" rx="8" />
					<g class="who"><circle cx="40" cy="72" r="8" /><circle cx="148" cy="72" r="8" /><circle cx="256" cy="72" r="8" /></g>
					<text class="nm" x="54" y="76">you</text><text class="nm" x="162" y="76">sam</text><text class="nm" x="270" y="76">ines</text>
					{#each [24, 132, 240] as x}
						<rect class="fi" x={x + 12} y="98" width="72" height="22" rx="4" /><text class="ft" x={x + 20} y="113">notes.db</text>
						<rect class="fi" x={x + 12} y="128" width="72" height="22" rx="4" /><text class="ft" x={x + 20} y="143">files/</text>
						<rect class="fi" x={x + 12} y="158" width="72" height="22" rx="4" /><text class="ft" x={x + 20} y="173">git/</text>
						<rect class="fi" x={x + 12} y="188" width="72" height="22" rx="4" /><text class="ft" x={x + 20} y="203">backups/</text>
					{/each}
				</g>
			</svg>
		</div>
	</section>

	<section class="final">
		<h2>{canSignup ? 'Ready when you are.' : 'Welcome back.'}</h2>
		<p>{canSignup ? 'Make an account and start with a blank page.' : 'Sign in to open your workspace.'}</p>
		<div class="cta center">
			<a class="btn primary big" href={canSignup ? '/signup' : '/login'}>{canSignup ? 'Create an account' : 'Sign in'}<ArrowRight size={15} /></a>
			{#if canSignup}<a class="btn big" href="/login">Sign in</a>{/if}
		</div>
	</section>

	<footer>
		<span class="brand sm"><Logo size={16} />{site.site_name}</span>
		<span class="faint"><Server size={12} /> Self-hosted. Your notes stay on your server.</span>
	</footer>
</div>

<style>
	.landing { height: 100dvh; overflow-y: auto; overflow-x: hidden; background: var(--bg); scroll-behavior: smooth; --max: 1120px; }
	.grow { flex: 1; }
	a { text-decoration: none; }
	.eyebrow { margin: 0 0 12px; font-size: 11.5px; font-weight: 650; letter-spacing: 0.09em; text-transform: uppercase; color: var(--accent); }
	h1, h2, h3 { letter-spacing: -0.02em; margin: 0; }

	/* ---- header */
	header { position: sticky; top: 0; z-index: 10; background: color-mix(in srgb, var(--bg) 88%, transparent); backdrop-filter: blur(10px); border-bottom: 1px solid var(--border); }
	.bar { max-width: var(--max); margin: 0 auto; height: 54px; padding: 0 24px; display: flex; align-items: center; gap: 8px; }
	.brand { display: flex; align-items: center; gap: 8px; font-weight: 650; font-size: 15.5px; letter-spacing: -0.01em; color: var(--text); margin-right: 14px; }
	.bar nav { display: flex; gap: 2px; }
	.bar nav a { padding: 5px 10px; border-radius: var(--radius); color: var(--text-2); }
	.bar nav a:hover { background: var(--hover); color: var(--text); }
	.bar .btn { height: 30px; text-decoration: none; }
	.btn.big { height: 40px; padding: 0 18px; font-size: 14px; border-radius: 8px; text-decoration: none; }

	/* ---- hero */
	.hero { max-width: var(--max); margin: 0 auto; padding: 72px 24px 30px; display: grid; grid-template-columns: minmax(0, 0.9fr) minmax(0, 1.25fr); gap: 52px; align-items: center; }
	h1 { font-size: clamp(36px, 5.2vw, 58px); line-height: 1.04; font-weight: 700; letter-spacing: -0.035em; }
	h1 em { font-family: var(--font-serif); font-weight: 500; font-style: italic; color: var(--accent); letter-spacing: -0.02em; }
	.lede { margin: 20px 0 26px; font-size: 16.5px; line-height: 1.55; color: var(--text-2); max-width: 46ch; }
	.cta { display: flex; align-items: center; flex-wrap: wrap; gap: 10px; }
	.cta.center { justify-content: center; }
	.more { display: inline-flex; align-items: center; gap: 2px; margin-left: 8px; color: var(--text-2); }
	.more:hover { color: var(--text); }

	/* the drawn app window */
	.win { border: 1px solid var(--border-strong); border-radius: 12px; overflow: hidden; background: var(--bg); box-shadow: 0 30px 70px -30px rgba(0, 0, 0, 0.55), 0 0 0 1px color-mix(in srgb, var(--text) 4%, transparent); user-select: none; transform: perspective(1600px) rotateY(-3deg) rotateX(1deg); transform-origin: left center; }
	.win-bar { display: flex; align-items: center; gap: 5px; height: 34px; padding: 0 12px; background: var(--bg-side); border-bottom: 1px solid var(--border); }
	.dot { width: 9px; height: 9px; border-radius: 50%; background: var(--border-strong); margin-right: 1px; }
	.win-bar .dot:first-child { margin-right: 1px; }
	.tab { display: flex; align-items: center; gap: 5px; height: 24px; padding: 0 9px; border-radius: 6px; font-size: 11.5px; color: var(--text-3); }
	.tab:first-of-type { margin-left: 10px; }
	.tab.on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border); }
	.win-body { display: grid; grid-template-columns: 150px minmax(0, 1fr) 170px; height: 340px; font-size: 11.5px; }
	.m-side { background: var(--bg-side); border-right: 1px solid var(--border); padding: 8px 6px; display: flex; flex-direction: column; gap: 1px; }
	.m-brand { display: flex; align-items: center; gap: 6px; padding: 2px 6px 8px; font-weight: 650; font-size: 12px; }
	.m-row { display: flex; align-items: center; gap: 7px; height: 22px; padding: 0 7px; border-radius: 4px; color: var(--text-2); white-space: nowrap; }
	.m-row.on { background: var(--active); color: var(--text); }
	.m-row.ind { padding-left: 17px; color: var(--text-3); }
	.m-row kbd, .m-row b { margin-left: auto; font-size: 9.5px; padding: 0 4px; }
	.m-row b { font-style: normal; font-weight: 650; color: var(--accent); background: color-mix(in srgb, var(--accent) 15%, transparent); border-radius: 8px; }
	.m-sec { padding: 10px 7px 3px; font-size: 9.5px; font-weight: 650; letter-spacing: 0.06em; text-transform: uppercase; color: var(--text-3); }
	.m-foot { margin-top: auto; padding-top: 6px; border-top: 1px solid var(--border); }
	.m-doc { padding: 16px 22px; overflow: hidden; }
	.m-crumb { font-size: 10.5px; color: var(--text-3); margin-bottom: 10px; }
	.m-title { font-size: 21px; font-weight: 650; letter-spacing: -0.02em; margin-bottom: 7px; }
	.m-chips { display: flex; gap: 5px; margin-bottom: 12px; }
	.m-chips .chip { height: 17px; font-size: 10.5px; }
	.m-blk { display: flex; gap: 8px; align-items: flex-start; padding: 3px 0; line-height: 1.45; font-size: 12.5px; }
	.m-blk.ind { margin-left: 20px; }
	.lk { color: var(--accent); background: color-mix(in srgb, var(--accent) 12%, transparent); padding: 0 3px; border-radius: 3px; }
	.bul { flex: none; width: 5px; height: 5px; margin-top: 7px; border-radius: 50%; background: var(--text-3); }
	.chk { flex: none; width: 12px; height: 12px; margin-top: 3px; border-radius: 3px; border: 1.5px solid var(--text-3); }
	.chk.on { background: var(--accent); border-color: var(--accent); }
	.done { color: var(--text-3); text-decoration: line-through; }
	.hl { background: color-mix(in srgb, var(--c-yellow) 26%, transparent); border-radius: 2px; padding: 0 2px; }
	.m-panel { border-left: 1px solid var(--border); padding: 8px 10px; background: var(--bg); }
	.m-panel .m-sec { padding-left: 0; }
	.m-bl { padding: 6px 8px; margin-bottom: 5px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); }
	.m-bl b { display: block; font-size: 11px; margin-bottom: 1px; }
	.m-bl > span { color: var(--text-3); font-size: 10.5px; line-height: 1.35; display: block; }

	/* ---- features */
	.features, .private, .final { max-width: var(--max); margin: 0 auto; padding: 84px 24px 20px; }
	.head { max-width: 640px; margin-bottom: 34px; }
	.head h2, .p-copy h2 { font-size: clamp(26px, 3.4vw, 36px); line-height: 1.12; font-weight: 700; }
	.head p:not(.eyebrow) { margin: 12px 0 0; font-size: 15.5px; line-height: 1.55; color: var(--text-2); }
	.bento { display: grid; grid-template-columns: repeat(6, 1fr); gap: 14px; }
	.tile { grid-column: span 2; display: flex; flex-direction: column; padding: 14px 14px 20px; border: 1px solid var(--border); border-radius: 12px; background: var(--surface); transition: border-color 0.15s var(--ease), transform 0.15s var(--ease); }
	.tile:hover { border-color: var(--border-strong); transform: translateY(-2px); }
	.t-outline, .t-graph { grid-column: span 3; }
	.t-db { grid-column: span 6; }
	.art { height: 214px; margin-bottom: 18px; border-radius: 8px; background: var(--bg); border: 1px solid var(--border); overflow: hidden; position: relative; padding: 16px; }
	.t-db .art { height: 268px; }
	.tile h3 { font-size: 16px; font-weight: 650; padding: 0 6px; }
	.tile p { margin: 6px 0 0; padding: 0 6px; color: var(--text-2); line-height: 1.5; font-size: 13.5px; max-width: 62ch; }

	.ol { display: flex; gap: 9px; align-items: flex-start; padding: 4px 0; font-size: 13px; position: relative; }
	.ol.l1 { margin-left: 22px; } .ol.l2 { margin-left: 44px; }
	.ol.l1::before, .ol.l2::before { content: ''; position: absolute; left: -17px; top: -4px; bottom: 6px; border-left: 1px solid var(--border-strong); }
	.ol .chip { height: 17px; font-size: 10.5px; margin-left: 4px; }
	.ol b { display: inline-block; width: 1.5px; height: 14px; background: var(--accent); vertical-align: middle; margin-left: 1px; animation: blink 1.1s steps(2) infinite; }
	@keyframes blink { 50% { opacity: 0; } }

	.t-graph .art { padding: 0; display: grid; place-items: center; background-image: radial-gradient(color-mix(in srgb, var(--text) 10%, transparent) 1px, transparent 1px); background-size: 16px 16px; }
	.t-graph svg { width: 100%; height: 100%; }
	.t-graph line { stroke: var(--border-strong); stroke-width: 1; }
	.t-graph circle { fill: var(--text-3); }
	.t-graph circle.hub { fill: var(--accent); }
	.t-graph .halo { fill: var(--accent); opacity: 0.16; }

	.views { display: flex; gap: 2px; margin-bottom: 12px; width: max-content; padding: 2px; border-radius: 6px; background: var(--surface-2); font-size: 11.5px; }
	.views span { padding: 3px 10px; border-radius: 4px; color: var(--text-3); }
	.views .on { background: var(--bg); color: var(--text); box-shadow: 0 0 0 1px var(--border-strong); }
	.board { display: grid; grid-template-columns: repeat(3, 1fr); gap: 10px; }
	.col h6 { display: flex; align-items: center; gap: 6px; margin: 0 0 7px; font-size: 11.5px; font-weight: 600; color: var(--text-2); }
	.col h6 i { width: 7px; height: 7px; border-radius: 50%; background: var(--c); }
	.col h6 b { margin-left: auto; color: var(--text-3); font-weight: 500; }
	.card { display: flex; flex-direction: column; gap: 5px; align-items: flex-start; padding: 8px 10px; margin-bottom: 6px; border: 1px solid var(--border); border-radius: 6px; background: var(--surface); font-size: 12px; }
	.card.muted { color: var(--text-3); text-decoration: line-through; }
	.card .chip { height: 16px; font-size: 10px; }

	.fc { height: 100%; display: flex; flex-direction: column; align-items: center; justify-content: center; text-align: center; gap: 6px; }
	.fc small { color: var(--text-3); font-size: 11px; }
	.fc .q { font-size: 20px; font-weight: 600; letter-spacing: -0.015em; }
	.fc .a { color: var(--text-2); font-size: 14px; padding-top: 8px; margin-top: 4px; border-top: 1px dashed var(--border-strong); width: min(260px, 90%); }
	.rate { display: flex; gap: 6px; margin-top: 12px; }
	.rate span { display: flex; flex-direction: column; align-items: center; min-width: 52px; padding: 5px 6px; border-radius: 6px; border: 1px solid var(--border-strong); font-size: 11.5px; font-weight: 550; }
	.rate em { font-style: normal; font-size: 9.5px; color: var(--text-3); font-weight: 400; }
	.rate .r1 { color: var(--c-red); } .rate .r2 { color: var(--c-orange); } .rate .r3 { color: var(--c-green); } .rate .r4 { color: var(--c-blue); }
	.rate .on { background: color-mix(in srgb, var(--c-green) 14%, transparent); border-color: var(--c-green); }

	.snap { height: 100%; border: 1px solid var(--border-strong); border-radius: 8px; overflow: hidden; background: #fbfaf7; display: flex; flex-direction: column; }
	.snap-bar { display: flex; align-items: center; gap: 8px; height: 26px; padding: 0 10px; background: var(--bg-side); border-bottom: 1px solid var(--border); font-size: 10.5px; color: var(--text-3); white-space: nowrap; }
	.snap-bar i { width: 8px; height: 8px; border-radius: 50%; background: var(--c-green); }
	.snap-bar b { margin-left: auto; font-weight: 600; color: var(--c-green); }
	.snap-body { padding: 14px 18px; display: flex; flex-direction: column; gap: 7px; }
	.snap-body > div { background: #dcd8ce; border-radius: 2px; height: 6px; }
	.snap-body .h { height: 12px; width: 62%; background: #2d2b27; margin-bottom: 5px; }
	.snap-body .s { width: 78%; }
	.snap-body .img { height: 34px; background: #e8dfc9; }

	.clone { padding: 8px 10px; margin-bottom: 14px; border: 1px solid var(--border-strong); border-radius: 6px; background: var(--surface); font: 11.5px var(--font-mono); color: var(--text-2); white-space: nowrap; overflow: hidden; text-overflow: ellipsis; }
	.clone span { color: var(--accent); margin-right: 6px; } .clone b { color: var(--text); font-weight: 500; }
	.heat { opacity: 0.95; display: grid; grid-auto-flow: column; grid-template-rows: repeat(7, 1fr); grid-template-columns: repeat(var(--weeks), 1fr); gap: 3px; }
	.heat i, .legend i { aspect-ratio: 1; border-radius: 2px; background: var(--surface-2); }
	i[data-v='1'] { background: color-mix(in srgb, var(--accent) 28%, var(--surface-2)); }
	i[data-v='2'] { background: color-mix(in srgb, var(--accent) 52%, var(--surface-2)); }
	i[data-v='3'] { background: color-mix(in srgb, var(--accent) 76%, var(--surface-2)); }
	i[data-v='4'] { background: var(--accent); }
	.legend { display: flex; align-items: center; justify-content: flex-end; gap: 3px; margin-top: 9px; font-size: 10px; color: var(--text-3); }
	.legend i { width: 9px; height: 9px; aspect-ratio: auto; }

	.also { list-style: none; margin: 26px 0 0; padding: 0; display: grid; grid-template-columns: repeat(3, 1fr); gap: 0 28px; }
	.also li { display: flex; gap: 11px; align-items: flex-start; padding: 15px 0; border-top: 1px solid var(--border); color: var(--text-3); }
	.also li > :global(svg) { margin-top: 2px; color: var(--accent); flex: none; }
	.also span { color: var(--text-2); font-size: 13.5px; line-height: 1.45; }
	.also b { display: block; color: var(--text); font-weight: 600; }

	/* ---- private */
	.private { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 0.95fr); gap: 60px; align-items: center; padding-top: 100px; }
	.p-copy > p:not(.eyebrow) { margin: 14px 0 20px; font-size: 15.5px; line-height: 1.6; color: var(--text-2); }
	.p-copy ul { margin: 0; padding: 0; list-style: none; display: flex; flex-direction: column; gap: 10px; }
	.p-copy li { padding-left: 18px; position: relative; color: var(--text-2); line-height: 1.5; }
	.p-copy li::before { content: ''; position: absolute; left: 0; top: 8px; width: 7px; height: 7px; border-radius: 2px; background: var(--accent); }
	.p-copy li b { color: var(--text); font-weight: 600; }
	.p-art svg { width: 100%; height: auto; }
	.srv { fill: var(--bg-side); stroke: var(--border-strong); }
	.lbl { fill: var(--text-3); font: 600 9.5px var(--font-sans); letter-spacing: 0.09em; }
	.ws { fill: var(--surface); stroke: var(--border-strong); }
	.who circle { fill: var(--accent); opacity: 0.85; }
	.who circle:nth-child(2) { fill: var(--c-blue); } .who circle:nth-child(3) { fill: var(--c-green); }
	.nm { fill: var(--text); font: 600 11px var(--font-sans); }
	.fi { fill: var(--bg); stroke: var(--border); }
	.ft { fill: var(--text-2); font: 10px var(--font-mono); }

	.final { text-align: center; padding: 110px 24px 90px; }
	.final h2 { font-size: clamp(28px, 4vw, 42px); font-weight: 700; }
	.final p { margin: 10px 0 26px; color: var(--text-2); font-size: 16px; }
	footer { max-width: var(--max); margin: 0 auto; padding: 22px 24px 40px; border-top: 1px solid var(--border); display: flex; flex-wrap: wrap; align-items: center; justify-content: space-between; gap: 10px; font-size: 12.5px; }
	footer .faint { display: flex; align-items: center; gap: 6px; }
	.brand.sm { font-size: 13px; margin: 0; }

	@media (max-width: 960px) {
		.hero { grid-template-columns: 1fr; padding-top: 44px; gap: 40px; }
		.win { transform: none; }
		.private { grid-template-columns: 1fr; gap: 36px; }
		.bento .tile, .t-db, .t-graph, .t-outline, .t-cards, .t-web, .t-git { grid-column: span 6; }
		.also { grid-template-columns: 1fr 1fr; }
	}
	@media (max-width: 640px) {
		.bar nav { display: none; }
		.bar { padding: 0 14px; }
		.win-body { grid-template-columns: 1fr; height: auto; }
		.m-side, .m-panel { display: none; }
		.win-bar .tab:not(.on) { display: none; }
		.also { grid-template-columns: 1fr; }
		.board { grid-template-columns: 1fr 1fr; }
		.board .col:nth-child(3) { display: none; }
		.t-db .art { height: 268px; }
	}
	@media (prefers-reduced-motion: reduce) { .landing { scroll-behavior: auto; } .tile { transition: none; } .ol b { animation: none; } }
</style>
