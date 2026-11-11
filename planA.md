# Build Specification: Personal Knowledge Management Platform

## 1. Project Vision

Build a comprehensive personal knowledge management and productivity application combining the strongest features of RemNote and Notion.

The application should function as a unified environment for:
- Taking and organizing notes.
- Creating documents and personal wikis.
- Building interconnected knowledge bases.
- Managing structured databases.
- Organizing projects and tasks.
- Creating and reviewing flashcards.
- Managing files and reference material.
- Tracking information through customizable properties and relationships.

The goal is to create a flexible system where almost any kind of personal information can be stored, organized, connected, searched, and presented in different ways.

The application should feel like a combination of RemNote's powerful outliner and learning tools with Notion's flexible editor, databases, and organizational capabilities.

This is primarily a personal, single-user application. Do not prioritize enterprise collaboration features at the expense of individual productivity.

The application should be polished, fast, intuitive, and enjoyable to use.

## 2. Technology Requirements

These are mandatory:

- Backend: Python with Django.
- API: Django REST Framework.
- Frontend: Svelte 5 and SvelteKit.
- Language: TypeScript on the frontend.
- Database: SQLite.
- Full-text search: SQLite FTS5 where appropriate.
- Deployment: 100% Docker-based using Docker Compose.

The entire application, including frontend and backend, must run in Docker. No application dependencies should need to be installed directly on the host.

Persistent data must survive container recreation and updates.

The application should not require external services, cloud accounts, subscriptions, or third-party APIs to function.

## 3. Main Application Interface

Create a modern desktop-oriented interface with three primary areas:

### Left Sidebar

The left sidebar should be the primary navigation system.

Include:

- Workspace navigation.
- Global search.
- Quick-create button.
- Favorites.
- Recently opened documents.
- Nested page and folder hierarchy.
- Database shortcuts.
- Flashcards.
- Task manager.
- Settings.

Users should be able to create, rename, move, nest, collapse, expand, favorite, and delete pages directly from the sidebar.

Allow drag-and-drop organization.

The sidebar should be collapsible and remember its state.

### Main Content Area

This is where the active document, database, flashcard interface, or other application feature is displayed.

It should support multiple open tabs or an equivalent quick-switching system so users can move between documents without constantly navigating through the sidebar.

### Contextual Right Sidebar

An optional contextual panel should display relevant information about the currently selected document or block.

Possible contents:

- Document properties.
- Tags.
- Backlinks.
- Related documents.
- Table of contents.
- Linked database information.
- Document history.

Allow the panel to be collapsed.

## 4. Documents and Page Organization

Documents are the foundation of the application.

Users should be able to create an unlimited number of documents and organize them into nested hierarchies.

Each document should support:

- Custom title.
- Icon or emoji.
- Optional cover image.
- Rich-text content.
- Nested documents.
- Tags.
- Custom properties.
- Backlinks.
- Attachments.
- Favorites.
- Archive status.
- Creation and modification timestamps.

Documents should be movable between folders and other documents.

Support breadcrumbs showing the current document's location.

Provide a quick switcher for navigating directly to any document.

Users should be able to duplicate, archive, export, and delete documents.

## 5. Rich Text and Block Editor

The editor is one of the most important parts of the application.

It should combine Notion's WYSIWYG editing experience with RemNote's hierarchical outliner.

Every line of content should be an independently manageable block.

### Supported Block Types

Implement:

- Paragraphs.
- Heading 1, 2, and 3.
- Bulleted lists.
- Numbered lists.
- Checklists.
- Toggle lists.
- Quotes.
- Callouts.
- Dividers.
- Code blocks.
- Images.
- Videos.
- Audio.
- File attachments.
- Mathematical equations.
- Tables.
- Bookmarks.
- Embedded documents.
- Synced blocks.
- Database views.

### Text Formatting

Support:

- Bold.
- Italic.
- Underline.
- Strikethrough.
- Inline code.
- Text colors.
- Background highlighting.
- Hyperlinks.
- Inline equations.

Formatting should be visible immediately while editing.

### Outliner Functionality

Every block should support:

- Nesting.
- Indentation.
- Outdentation.
- Reordering.
- Drag and drop.
- Collapsing and expanding.
- Multi-selection.
- Copying and pasting.
- Duplication.
- Deletion.
- Conversion to other block types.

Users should be able to write entire documents as nested outlines, with arbitrary nesting depth.

Nested blocks should remain easy to navigate, even in very large documents.

### Slash Commands

Typing `/` should open a searchable command menu for inserting blocks.

Commands should include all supported block types.

The menu should be keyboard navigable.

### Keyboard-First Editing

Support intuitive keyboard shortcuts for:

- Creating blocks.
- Moving between blocks.
- Indenting and outdenting.
- Formatting text.
- Inserting links.
- Opening search.
- Opening the command menu.
- Undoing and redoing actions.
- Navigating between documents.

The editor should feel fast and predictable without requiring constant mouse interaction.

### Autosave

Changes should save automatically.

Show subtle save-state feedback when appropriate.

Never lose a user's edits because they navigated away from a document.

## 6. Internal Linking and Backlinks

Build a comprehensive bidirectional linking system.

Users should be able to link to:

- Entire documents.
- Individual blocks.
- Database entries.
- Tags.

Typing `[[` should open an autocomplete menu allowing users to search for and insert internal references.

Links should navigate directly to their targets.

### Backlinks

Every document and block should display incoming references.

Show:
- Number of backlinks.
- Source documents.
- Source blocks.
- Context surrounding each reference.

Backlinks should update automatically when references are created, edited, or deleted.

Allow users to open backlinks directly.

### Transclusion and Synced Blocks

Support RemNote-style portals and Notion-style synced blocks.

Users should be able to embed an existing block or document inside another document.

The embedded content must remain connected to its original source.

Changes to the original should appear in every embedded instance.

Allow users to create multiple references to the same content without duplicating it.

Prevent circular embedding.

## 7. Tags and Properties

Implement a flexible tagging and metadata system.

Tags should be first-class entities rather than ordinary text.

Users should be able to:

- Create tags.
- Rename tags.
- Assign multiple tags to content.
- Search tags.
- Browse everything associated with a tag.
- Filter content by tags.

### Tag Properties

Tags should support their own property definitions.

For example:

A Person tag could have:
- Birthday.
- Email.
- Phone number.
- Organization.

A Project tag could have:
- Status.
- Priority.
- Start date.
- Deadline.

Supported property types should include:

- Text.
- Number.
- Boolean.
- Date.
- URL.
- Select.
- Multi-select.
- Relation.
- Rating.

Allow users to view and edit property values directly from documents.

## 8. Relational Database System

Implement a fully functional Notion-style database system.

Databases should be first-class objects that can be placed inside documents or accessed through the sidebar.

A database contains entries, and every entry should be capable of opening as its own document with additional content.

### Database Properties

Support:

- Title.
- Text.
- Number.
- Checkbox.
- Date.
- URL.
- Email.
- Phone.
- Select.
- Multi-select.
- Status.
- Relation.
- Rollup.
- Formula.
- Created time.
- Last edited time.

Properties should be configurable per database.

Users should be able to create, edit, reorder, hide, and delete properties.

### Database Views

A single database should support multiple views of the same entries.

Changes made in one view must immediately be reflected in every other view.

**Table View**

- Spreadsheet-like interface.
- Editable cells.
- Resizable columns.
- Configurable column visibility.
- Sorting.
- Filtering.
- Row selection.
- Quick entry creation.

**Board View**

- Kanban-style columns.
- Grouping by status or select properties.
- Drag-and-drop cards.
- Customizable card contents.
- Collapsible groups.

**Calendar View**

- Display entries according to date properties.
- Monthly and weekly navigation.
- Create entries from calendar dates.
- Open entries directly.

**Gallery View**

- Visual card layout.
- Optional cover images.
- Customizable card properties.
- Configurable card sizes.

**List View**

- Compact entry listing.
- Configurable metadata.
- Sorting and filtering.

### Database Filtering

Support filters based on:

- Text values.
- Numbers.
- Dates.
- Select properties.
- Multi-select properties.
- Checkboxes.
- Relations.
- Empty and non-empty values.

Support AND/OR filter combinations.

Allow multiple sorting conditions.

Users should be able to save different database views with their own filters, sorting, grouping, and visible properties.

### Relations and Rollups

Allow databases to reference other databases.

For example:
- Projects can reference tasks.
- Tasks can reference projects.
- Books can reference authors.
- People can reference organizations.

Relations should be navigable in both directions.

Rollups should retrieve and summarize information from related entries.

### Formulas

Provide a formula property type that can calculate values using other properties.

Support basic mathematical operations, comparisons, conditional expressions, and useful functions.

## 9. Templates

Implement reusable templates for documents and database entries.

A template should be able to contain:

- Default title.
- Icon.
- Default properties.
- Tags.
- Predefined blocks.
- Nested block structures.

Users should be able to create, edit, duplicate, and delete templates.

Allow templates to be selected when creating new documents or database entries.

Support tag-associated templates that automatically insert predefined structures when a particular tag is applied.

## 10. Flashcards and Spaced Repetition

Implement a complete flashcard system integrated with the note-taking environment.

Flashcards should be directly linked to the notes and documents they originate from.

### Card Types

**Basic Cards**

A question on the front and an answer on the back.

**Cloze Cards**

Hide selected words or phrases within a sentence.

Example:

The capital of France is {{Paris}}.

**Concept Cards**

A term on one side and its definition or explanation on the other.

**Image Occlusion**

Allow users to upload an image and create hidden regions that must be identified during review.

### Card Creation

Users should be able to create cards:

- From within documents.
- From individual blocks.
- From selected text.
- Through a dedicated flashcard editor.

Allow users to browse, edit, search, suspend, and delete cards.

### Review Interface

Create a dedicated distraction-free flashcard review interface.

Show one card at a time.

Users should reveal the answer and rate their recall:

- Again.
- Hard.
- Good.
- Easy.

Use an established spaced-repetition scheduling system such as FSRS.

### Flashcard Dashboard

Display:

- Cards due today.
- New cards.
- Reviews completed.
- Review accuracy.
- Upcoming reviews.
- Historical review activity.

Allow users to browse decks or filtered groups of cards.

## 11. Task Management

Implement an integrated task management system.

Tasks should be usable independently or associated with documents, blocks, and database entries.

Support:

- Task title.
- Description.
- Completion status.
- Priority.
- Due date.
- Start date.
- Recurrence.
- Associated document.
- Associated project.
- Tags.

Provide dedicated task views:

**Inbox:** Tasks that have not been organized.

**Today:** Tasks due today.

**Upcoming:** Tasks due in the future.

**Completed:** Finished tasks.

Support sorting and filtering.

Allow users to create tasks directly from checklist blocks.

Completing a task should update its associated block or database entry where applicable.

## 12. Search and Navigation

Build a powerful global search system.

Search across:

- Documents.
- Block contents.
- Titles.
- Tags.
- Properties.
- Database entries.
- Flashcards.
- Tasks.

Search results should display:
- Matching title.
- Content preview.
- Matching text highlighted.
- Document location.
- Relevant metadata.

Support filtering search results by content type.

Include:
- Recent searches.
- Recent documents.
- Favorites.
- Quick navigation.
- Search suggestions.

The global search should be accessible from anywhere in the application through a keyboard shortcut.

Also provide saved searches or search-based views that automatically display matching content.

## 13. Knowledge Graph

Create an interactive graph visualization of the workspace.

Show relationships between:

- Documents.
- Blocks.
- Tags.
- Database entries.
- Internal references.

Allow users to:

- Zoom.
- Pan.
- Select nodes.
- Open documents.
- Search nodes.
- Filter relationship types.
- Focus on a selected node.
- Explore connected content.

Distinguish between hierarchical relationships, tags, and explicit references.

Provide useful controls to prevent large graphs from becoming visually overwhelming.

## 14. Media and Attachments

Allow users to upload and embed:

- Images.
- PDFs.
- Audio files.
- Video files.
- General documents.

Support:
- Inline image previews.
- Image enlargement.
- PDF viewing.
- Audio playback.
- Video playback.
- File downloads.
- Attachment management.

Attachments should be reusable across documents where appropriate.

Provide a centralized file browser showing all uploaded files.

## 15. Import and Export

Users must be able to import existing information and export their workspace without being locked into the application.

### Import Formats

Support:
- Markdown.
- CSV.
- JSON.
- OPML.
- HTML.
- Anki decks where practical.

Preserve document hierarchy, formatting, tags, and links where possible.

Support importing folders of Markdown files.

### Export Formats

Support:
- Markdown.
- HTML.
- JSON.
- CSV.
- OPML.
- PDF.
- Anki APKG where practical.

Allow exporting:
- Individual documents.
- Entire folders.
- Databases.
- Flashcard collections.
- The complete workspace.

Provide full workspace backups that include attachments and database contents.

Include a restoration feature.

## 16. Version History

Provide document version history.

Users should be able to:

- Browse previous versions.
- See when a version was created.
- Preview an older version.
- Compare revisions where practical.
- Restore a previous version.

Provide a clear visual distinction between the current document and historical versions.

Also support normal editor undo and redo.

## 17. Offline Usage

The application should support basic offline functionality.

Users should be able to:
- Open previously cached documents.
- Read cached content.
- Access cached attachments.
- Continue working on supported cached content.

Offline edits should be queued and synchronized when connectivity returns.

Clearly identify synchronization conflicts.

Never silently overwrite newer content with older offline changes.

This can be expanded after the core online experience is stable.

## 18. Settings and Customization

Create a comprehensive settings interface.

Include:

### Appearance
- Dark theme.
- Light theme.
- System theme.
- Custom accent color.
- Font preferences.
- Editor width.
- Interface density.
- Sidebar behavior.

### Editor
- Default block type.
- Default text formatting behavior.
- Keyboard shortcut configuration.
- Autosave preferences.
- Editor appearance.

### Workspace
- Default document behavior.
- Favorite management.
- Recently opened documents.
- Archive management.

### Flashcards
- Daily review limits.
- New card limits.
- Scheduling preferences.
- Review behavior.

### Data
- Backup creation.
- Backup restoration.
- Import.
- Export.
- Storage information.

## 19. Overall User Experience

The application should feel like a mature desktop productivity product.

Prioritize:

- Fast navigation.
- Minimal interaction friction.
- Keyboard accessibility.
- Responsive editing.
- Consistent UI components.
- Clear visual hierarchy.
- Useful empty states.
- Helpful contextual menus.
- Smooth animations.
- Persistent user preferences.

Use a modern, restrained visual style.

Prefer an off-black dark theme, subtle borders, neutral surfaces, and a carefully selected accent color.

Avoid generic AI-generated dashboard aesthetics, excessive gradients, excessive whitespace, oversized typography, and unnecessary cards.

The interface should be information-dense without feeling cluttered.

The primary desktop layout should be optimized for extended daily use.

Mobile browser support should also be provided, with appropriate responsive navigation and editing controls.

## 20. Reliability and Data Safety

The application is intended to store potentially years of personal information.

Data integrity is therefore critical.

Users must never lose documents, blocks, attachments, flashcards, or database entries due to ordinary application operations.

Ensure that:

- Autosave is reliable.
- Deletions behave predictably.
- References do not become silently corrupted.
- Moving blocks preserves their contents.
- Database relations remain valid.
- Backups include all relevant data.
- Restoration works.
- Import/export preserves as much structure as possible.

Provide confirmation for destructive operations.

Support undo for common accidental editing operations.

## 21. Development Priorities

Build the application in the following order.

### Priority 1: Core Knowledge Management

The initial usable product must include:

- Main interface.
- Sidebar navigation.
- Documents and nested pages.
- Rich-text editor.
- Block-based content.
- Outliner functionality.
- Autosaving.
- Internal linking.
- Backlinks.
- Tags.
- Properties.
- Global search.

### Priority 2: Advanced Organization

Add:

- Templates.
- Transclusion.
- Knowledge graph.
- Relational databases.
- Database properties.
- Table views.
- Board views.
- Calendar views.
- Gallery views.
- Filters and sorting.
- Relations and rollups.

### Priority 3: Learning and Productivity

Add:

- Flashcards.
- Cloze cards.
- Image occlusion.
- Spaced repetition.
- Review statistics.
- Tasks.
- Recurring tasks.
- Task dashboards.

### Priority 4: Advanced Functionality

Add:

- Media management.
- PDF support.
- Import and export.
- Version history.
- Offline functionality.
- Workspace backups.
- API documentation.
- Additional customization.

Each phase should result in working, persistent functionality.

Do not create visual placeholders for features that have not been implemented.

## 22. Final Expectations

The finished application should provide a unified experience where users can take notes, build a personal wiki, manage databases, organize projects, create flashcards, and connect information together.

The application should combine the flexibility of Notion with the knowledge-management and learning capabilities of RemNote.

It should be powerful enough to serve as the user's primary personal information system.

The application must be:

- Self-hosted.
- Single-user-first.
- Fully Docker-based.
- Built with Django and Python.
- Built with Svelte 5 and SvelteKit.
- Powered by SQLite.
- Free of mandatory external services.
- Designed for long-term use.

Prioritize a genuinely excellent user experience and complete functionality over superficial feature counts.

Build a cohesive product, not a collection of disconnected tools.
