# Web Archive Feature - Summary

## Overview
A new bookmark/archive system that allows users to save, organize, and access webpages, videos, and images from URLs. Content is displayed as nice tiles on a bookmarks page with built-in support for video downloading via yt-dlp.

## Files Changed/Created

### Backend (Django)
1. **backend/notes/models_web.py** - New model for WebArchive entities
2. **backend/notes/views_web.py** - API endpoints for CRUD operations + yt-dlp integration
3. **backend/notes/urls.py** - Updated with new routes
4. **backend/notes/views.py** - Health check updated to report yt-dlp availability
5. **backend/notes/migrations/0008_web_archive_model.py** - Auto-generated migration

### Frontend (SvelteKit)
1. **frontend/src/routes/web/+page.svelte** - Main bookmarks page component
2. **frontend/src/routes/web/+page.svelte.md** - API documentation
3. **frontend/src/lib/components/Sidebar.svelte** - Added "Bookmarks" entry

### Documentation
1. **docs/web-archive.md** - User-facing documentation

## Features Implemented

### Core Functionality
- ✅ Paste URL to save (works for webpages, videos, images)
- ✅ Automatic content type detection (web/video/image/mixed)
- ✅ Fetch and save webpage content locally
- ✅ Extract Open Graph metadata (title, description, thumbnail)
- ✅ Tile-based UI with grid/list view toggle

### Video Support (YouTube, Vimeo, etc.)
- ✅ Auto-detect video platforms
- ✅ Extract: title, author, duration, description, thumbnail
- ✅ Download via yt-dlp (best quality, audio-only, quality presets)
- ✅ Download status indicator

### Image Support
- ✅ Save images from direct URLs
- ✅ Thumbnail display in tiles
- ✅ Click-through to original

### Notes & Todos System
- ✅ Add notes per archive
- ✅ Create todo checklist items
- ✅ Toggle todos with checkboxes
- ✅ Keyboard shortcuts (Ctrl/Cmd+Enter to save)

### UI/UX
- ✅ Consistent styling with app theme
- ✅ Responsive design (mobile-friendly)
- ✅ Loading states and error handling
- ✅ Empty state with helpful guidance
- ✅ Search/filter archives
- ✅ Action buttons: View, Edit, Delete

## Dependencies

### Python
```bash
pip install requests youtube-dlc yt_dlp
```

### Frontend
No new dependencies required - uses existing SvelteKit setup.

## How to Use

### Save a Webpage
1. Go to `/web`
2. Paste any URL and press Enter
3. Click "View" to see the saved content
4. Click "Edit" to modify metadata or "Add notes" for personal notes

### Download a Video
1. Paste YouTube/Vimeo URL
2. Wait for processing (metadata extraction)
3. Click "Download" button
4. Choose: Best quality, Audio only, or specific resolution
5. Video downloads to /tmp (check file manager)

### View Saved Archives
- Browse grid/list view of all archives
- Search by title, description, or URL
- Click tiles to expand and view full details
- Actions at bottom: View snippet, Edit, Add notes, Delete

## API Endpoints

| Method | Endpoint | Description |
|--------|----------|-------------|
| GET | `/api/web/list` | List all archives (with optional search) |
| POST | `/api/web/archive` | Create new archive from URL |
| GET | `/api/web/<id>` | Get archive details |
| GET | `/api/web/<id>/process` | Fetch/process content |
| PATCH | `/api/web/<id>` | Update notes/todos/metadata |
| POST | `/api/web/<id>/download-video` | Download video with yt-dlp |
| GET | `/api/web/<id>/preview` | Get preview of content |

## Environment Variables (Optional)

```bash
WEB_ARCHIVE_USER=username  # For authenticated sites
WEB_ARCHIVE_PASS=password  # Password for auth-required URLs
```

## Testing

### Check yt-dlp availability
```bash
curl http://localhost:8000/api/health
# Should return: {"ok":true,"yt_dlp":"available"}
```

### Test creating archive
```bash
curl -X POST http://localhost:8000/api/web/archive \
  -H "Content-Type: application/json" \
  -d '{"url":"https://example.com","title":"Test"}'
```

## Notes for Future Enhancement

- Consider adding bulk import from CSV/JSON
- Add support for RSS feeds and subscriptions
- Implement pagination for large archive collections
- Add tagging system for better organization
- Support for full-text search across notes
- Export archives as ZIP with local files
