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

API: `GET /api/web/list?q=&kind=`, `POST /api/web/archive`, `GET|PATCH|DELETE /api/web/<id>`,
`POST /api/web/<id>/process`, `POST /api/web/<id>/download-video`, `GET /api/web/<id>/preview`.
