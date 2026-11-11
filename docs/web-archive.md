# Web Archive Feature

The Web Archive feature allows you to save, organize, and access captured content from the internet including webpages, videos, and images. All content is displayed as nice tiles on a dedicated bookmarks page.

## Quick Start

### 1. Navigate to Bookmarks
Go to `/web` in your browser. You'll see a search bar at the top where you can paste URLs.

### 2. Save Content
Simply paste any URL and press Enter:
- **Webpages**: Any HTML page will be fetched and saved locally
- **Videos**: YouTube, Vimeo, Twitch videos are automatically detected for download options
- **Images**: Direct image links (JPG, PNG, GIF, WebP) can be captured

### 3. View Your Archives
All saved items appear as tiles with:
- Thumbnail preview
- Title and metadata
- Actions: View snippet, Edit, Add notes

## Features by Content Type

### Videos (YouTube, Vimeo, etc.)
- **Automatic detection**: Recognizes video platforms
- **Info extraction**: Title, author, duration, description
- **Download option**: Click "Download" to save the video/audio
  - *Best quality*: Highest resolution available
  - *Audio only*: Converts to MP3 (192kbps)
  - Quality: 1080p, 720p, or 480p

### Images
- **Direct capture**: Save images from URLs
- **Preview**: Thumbnail view in archive tiles
- **Click to view**: Opens original URL in new tab

### Webpages
- **Local storage**: Full HTML content saved on server
- **Meta extraction**: Open Graph data (title, description, thumbnail)
- **Sanitized preview**: Safe HTML viewer
- **Media detection**: Finds embedded audio/video files on pages

## Using Notes and Todos

### Add Notes
1. Click an archive card
2. Click "Add notes" button
3. Type your notes in the textarea
4. Press `Ctrl+Enter` (or `Cmd+Enter`) to save

Notes are stored separately from the original content, perfect for:
- Summary of key points
- Personal reminders about the resource
- Categorization tags (free-form text)

### Create Todos
1. While viewing an archive, scroll to the todos section
2. Type a task related to this content
3. Press Enter to add
4. Click checkboxes to mark as complete

Examples:
- "Read this article and take notes"
- "Watch tutorial and implement example"
- "Subscribe to this channel for updates"

## Technical Details

### File Storage
- Webpage HTML: Stored in database (text field, max 5MB recommended)
- Video downloads: Saved to `/tmp` by yt-dlp
- Thumbnails: Extracted from page metadata or video info

### yt-dlp Integration
The feature uses `youtube-dlp` for video downloading. The tool:
- Automatically handles authentication headers if configured
- Supports most major video platforms
- Can extract subtitles and chapter information
- Downloads in background (shows progress)

### Security Notes
- All external URLs are fetched through a controlled process
- HTML content is sanitized before storage
- Authentication can be set via environment variables for protected sites:
  ```bash
  WEB_ARCHIVE_USER=username
  WEB_ARCHIVE_PASS=password
  ```

## Installation Requirements

Before using video download features, ensure yt-dlp is installed:

```bash
# On Linux/Unix
pip install youtube-dlc yt_dlp

# Or use the provided script
curl -L https://github.com/yt-dlp/yt-dlp/releases/latest/download/yt-dlp.py -o /usr/local/bin/yt-dlp
chmod +x /usr/local/bin/yt-dlp
```

Verify installation:
```bash
python -c "import youtube_dl; print('yt-dlp available')"
```

## Troubleshooting

### "yt-dlp not installed" error
Run: `pip install youtube-dlc yt_dlp`

### Video download fails
1. Check YouTube Terms of Service for your use case
2. Some content may require authentication (set env vars)
3. Try different video quality options

### Thumbnail not showing
- The system extracts from Open Graph meta tags
- If no meta data, uses platform default thumbnail
- Click "View" to see content anyway

## Keyboard Shortcuts

- **Ctrl/Cmd + K**: Quick search (works on any page)
- **Ctrl/Cmd + Enter**: Save notes while editing
- **Tab**: Navigate between input fields

## API Reference

See `frontend/src/routes/web/+page.svelte.md` for complete API documentation.
