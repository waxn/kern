# Web Archive / Bookmarks

The `/web` route provides a bookmarks/archive page for saving and managing webpages, videos, and images captured from URLs.

## Features

### URL Input (Bookmarks Tab)
- Paste any URL in the search bar at the top of the page to create an archive
- Automatically detects content type:
  - **Webpage**: Regular HTML pages
  - **Video**: YouTube, Vimeo, Twitch, TikTok videos
  - **Image**: Direct image URLs (.jpg, .png, etc.)
  - **Mixed**: Content with both media and text

### Automatic Content Detection
- Extracts video information from platforms like YouTube using yt-dlp
- Detects Open Graph metadata (og:image, og:title, etc.) for thumbnails
- Automatically fetches webpage HTML content when saved

### Tile-based UI
- Grid/list view toggle
- Shows thumbnail, title, and kind (video/image/web)
- Duration displayed for videos
- Actions to:
  - **View**: Preview the archived snippet
  - **Edit**: Modify URL, title, metadata
  - Add notes about the archive
  - Create todos/tasks related to the content

### Video Download
- For video archives, click "Download" to save using yt-dlp
- Options:
  - **Best quality**: Highest available resolution
  - **Audio only**: Convert to MP3 at 192kbps
  - Quality presets: 1080p, 720p, 480p

### Notes and Todos
- Add personal notes about each archive
- Create todo checklist items
- Toggle todos on/off with checkboxes
- Enter note content with Ctrl/Cmd+Enter to save

### Supported Platforms
- YouTube (youtube.com, youtu.be)
- Vimeo
- Twitch
- TikTok
- Direct image URLs
- Regular webpages

## API Endpoints

### List Archives
```
GET /api/web/list?q=search&kind=type
```

### Create Archive
```
POST /api/web/archive
Body: {
  "url": "https://...",
  "title": "",
  "author": "",
  "description": "",
  "notes": ""
}
```

### Get Details
```
GET /api/web/<archive_id>
```

### Process Archive (fetch content)
```
GET /api/web/<archive_id>/process
```

### Edit Notes/Todos
```
PATCH /api/web/<archive_id>
Body: { "notes": "...", "todos": [...] }
```

### Download Video
```
POST /api/web/<archive_id>/download-video
```

### Preview Content
```
GET /api/web/<archive_id>/preview
```

## Environment Variables

Optional authentication for protected URLs:
```bash
WEB_ARCHIVE_USER=your_username
WEB_ARCHIVE_PASS=your_password
```

## Dependencies

**Required:**
- `youtube-dlc` or `youtube_dl` (for video downloading)
- `yt_dlp` (Python package, same as above)

**Install with:**
```bash
pip install youtube-dlc yt_dlp requests
```

## Usage Examples

### Save a YouTube Video
1. Paste: `https://www.youtube.com/watch?v=EXAMPLE`
2. Click Enter or View → Archive appears in list
3. Click "View" to see snippet
4. (Optional) Click "Download" to save with yt-dlp

### Add Notes to an Archive
1. Click an archive card
2. Click "Add notes" or "Edit"
3. Type your notes
4. Press Ctrl/Cmd+Enter to save

### Create a Todo from Content
1. View the archived content
2. Scroll to todos section at bottom
3. Type a todo item and press Enter
4. Check items to mark as done
