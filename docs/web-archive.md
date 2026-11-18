# Bookmarks (web archive)

Save a link at **Bookmarks** (sidebar) and Kern fetches it, stores a sanitised copy of the page
(scripts removed), and fills in the title, description, author and thumbnail from the page's metadata.

- **Kinds** are detected from the URL: webpage, video (YouTube, Vimeo, Twitch, TikTok, Dailymotion) or image.
- **Edit** the title, author and description; add **notes** and a **to-do** checklist per bookmark.
- **Video download** (video bookmarks): choose video or audio-only and 1080p/720p/480p, then Download.
  It runs in the background through yt-dlp; the file is stored under the data dir (`media/web/<id>/`)
  and plays inline when finished. Needs `yt-dlp` (in `requirements.txt`) and `ffmpeg` (installed in the Docker image).
- Archived pages render in a fully sandboxed iframe. Only public `http(s)` addresses are fetched
  (private, loopback and link-local hosts are refused).

- **Tags** (shared with pages and tasks) can be added from a bookmark's side panel; filter the list by tag.
- **Watch for changes** (web pages): checks the page every hour to every week. Modes: new posts
  (RSS/Atom feed, or article links without one), price (JSON-LD, `product:price` meta, `itemprop=price`,
  then the page text), any text change, or automatic. The scheduler is a thread in each server
  process (`notes/monitor.py`); checks are claimed with a conditional update so each runs once.
  `KERN_NO_MONITOR=1` disables it.
- **History**: snapshots saved on each change, on "Save snapshot now", when first bookmarked, and when
  a re-fetch finds different text. Stored in `WebSnapshot`, with assets in `media/web-pages/v<id>/`
  (hard-linked). Versions can be viewed (sandboxed like the main snapshot) and diffed line by line.

API: `GET /api/web/list?q=&kind=&tag=&show=watched|changed`, `GET /api/web/changes`,
`POST /api/web/<id>/check`, `GET|POST /api/web/<id>/versions`, `GET|DELETE /api/web/<id>/versions/<vid>`,
`GET /api/web/<id>/versions/<vid>/diff?against=`, `GET /api/web/<id>/versions/<vid>/page`,
`GET /api/web/list?q=&kind=`, `POST /api/web/archive`, `GET|PATCH|DELETE /api/web/<id>`,
`POST /api/web/<id>/process`, `POST /api/web/<id>/download-video`, `GET /api/web/<id>/preview`.
