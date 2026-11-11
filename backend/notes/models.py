import uuid

from django.db import models


class Tag(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    key = models.CharField(max_length=120, unique=True)  # lower-cased name
    color = models.CharField(max_length=24, blank=True, default="")
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["key"]

    def save(self, *args, **kwargs):
        self.name = self.name.strip()
        self.key = self.name.lower()
        super().save(*args, **kwargs)


class Document(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    title = models.CharField(max_length=500, blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    cover = models.CharField(max_length=500, blank=True, default="")
    position = models.FloatField(default=0)
    is_favorite = models.BooleanField(default=False)
    is_archived = models.BooleanField(default=False)
    trashed_at = models.DateTimeField(null=True, blank=True, db_index=True)
    tags = models.ManyToManyField(Tag, blank=True, related_name="documents")
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now_add=True)
    last_opened_at = models.DateTimeField(null=True, blank=True)
    # Database entries are documents that belong to a database.
    entry_of = models.ForeignKey(
        "Database", null=True, blank=True, on_delete=models.CASCADE, related_name="entries"
    )
    # Templates are ordinary documents (so the full editor works on them),
    # hidden from the tree and search.
    is_template = models.BooleanField(default=False, db_index=True)
    template_tag = models.ForeignKey(
        Tag, null=True, blank=True, on_delete=models.SET_NULL, related_name="templates"
    )
    template_db = models.ForeignKey(
        "Database", null=True, blank=True, on_delete=models.CASCADE, related_name="templates"
    )

    class Meta:
        indexes = [models.Index(fields=["parent", "position"])]


class Block(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="blocks")
    parent = models.ForeignKey(
        "self", null=True, blank=True, on_delete=models.CASCADE, related_name="children"
    )
    position = models.FloatField(default=0)
    type = models.CharField(max_length=32, default="paragraph")
    html = models.TextField(blank=True, default="")
    props = models.JSONField(default=dict, blank=True)
    collapsed = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)

    class Meta:
        indexes = [models.Index(fields=["document", "parent", "position"])]


class Link(models.Model):
    """A reference from a block to a document, block or tag."""

    source_block = models.ForeignKey(Block, on_delete=models.CASCADE, related_name="links")
    source_document = models.ForeignKey(
        Document, on_delete=models.CASCADE, related_name="outgoing_links"
    )
    target_kind = models.CharField(max_length=8)  # doc | block | tag
    target_id = models.CharField(max_length=36)

    class Meta:
        indexes = [models.Index(fields=["target_kind", "target_id"])]


class Database(models.Model):
    """A collection of entry documents. Its title and icon live on `page`."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    page = models.OneToOneField(Document, on_delete=models.CASCADE, related_name="database")
    created_at = models.DateTimeField(auto_now_add=True)


class DbView(models.Model):
    TYPES = ["table", "board", "calendar", "gallery", "list"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    database = models.ForeignKey(Database, on_delete=models.CASCADE, related_name="views")
    name = models.CharField(max_length=120, default="Table")
    type = models.CharField(max_length=16, default="table")
    config = models.JSONField(default=dict, blank=True)
    position = models.FloatField(default=0)

    class Meta:
        ordering = ["position"]


class PropertyDef(models.Model):
    TYPES = [
        "text", "number", "boolean", "date", "url", "email", "phone",
        "select", "multi_select", "status", "relation", "rating",
        "rollup", "formula", "created_time", "last_edited_time",
    ]
    COMPUTED = {"rollup", "formula", "created_time", "last_edited_time"}

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    # Tag-bound definitions appear on every document carrying the tag;
    # definitions without a tag are ad-hoc properties added per document.
    tag = models.ForeignKey(
        Tag, null=True, blank=True, on_delete=models.CASCADE, related_name="properties"
    )
    database = models.ForeignKey(
        Database, null=True, blank=True, on_delete=models.CASCADE, related_name="properties"
    )
    name = models.CharField(max_length=120)
    type = models.CharField(max_length=16, default="text")
    options = models.JSONField(default=list, blank=True)  # [{id, name, color}]
    # relation: {target: db id | null, reverse: prop id | null}
    # rollup: {relation: prop id, target: prop id | "title", fn}
    # formula: {expr}
    config = models.JSONField(default=dict, blank=True)
    position = models.FloatField(default=0)

    class Meta:
        ordering = ["position", "name"]


class PropertyValue(models.Model):
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="property_values")
    definition = models.ForeignKey(PropertyDef, on_delete=models.CASCADE, related_name="values")
    value = models.JSONField(null=True, blank=True)

    class Meta:
        constraints = [
            models.UniqueConstraint(fields=["document", "definition"], name="uniq_doc_property")
        ]


class Attachment(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    file = models.FileField(upload_to="files/%Y/%m")
    name = models.CharField(max_length=255)
    mime = models.CharField(max_length=127, blank=True, default="")
    size = models.BigIntegerField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)


class Setting(models.Model):
    key = models.CharField(max_length=120, primary_key=True)
    value = models.JSONField(null=True)


class SearchEntry(models.Model):
    """Maps an indexed object to its rowid in the FTS5 table `search_fts`."""

    kind = models.CharField(max_length=12)  # doc | block | tag
    ref_id = models.CharField(max_length=36)
    document = models.ForeignKey(Document, null=True, on_delete=models.CASCADE)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["kind", "ref_id"], name="uniq_search_ref")]


# ------------------------------------------------------------------ learning


class Deck(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    name = models.CharField(max_length=120)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        ordering = ["name"]


class CardNote(models.Model):
    """The source of one or more cards (a cloze note yields one card per gap)."""

    KINDS = ["basic", "cloze", "concept", "occlusion"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    kind = models.CharField(max_length=12, default="basic")
    front = models.TextField(blank=True, default="")  # basic/concept: question or term; cloze: text
    back = models.TextField(blank=True, default="")
    image = models.CharField(max_length=500, blank=True, default="")  # occlusion
    regions = models.JSONField(default=list, blank=True)  # occlusion: [{id, x, y, w, h, label}]
    deck = models.ForeignKey(Deck, null=True, blank=True, on_delete=models.SET_NULL, related_name="notes")
    document = models.ForeignKey(
        "Document", null=True, blank=True, on_delete=models.CASCADE, related_name="card_notes"
    )
    # Id of the source block. A plain id (not a foreign key) so review history
    # survives the block being deleted and restored with undo.
    block_ref = models.CharField(max_length=36, blank=True, default="", db_index=True)
    # Created from `::`, `;;` or `{{cloze}}` syntax in a block; kept in step with it.
    auto = models.BooleanField(default=False)
    # Inactive notes keep their history but produce no reviews (e.g. the syntax was removed).
    active = models.BooleanField(default=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class Card(models.Model):
    STATES = ["new", "learning", "review", "relearning"]

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    note = models.ForeignKey(CardNote, on_delete=models.CASCADE, related_name="cards")
    ordinal = models.IntegerField(default=0)
    state = models.CharField(max_length=12, default="new")
    due = models.DateTimeField(null=True, blank=True, db_index=True)
    stability = models.FloatField(default=0)
    difficulty = models.FloatField(default=0)
    reps = models.IntegerField(default=0)
    lapses = models.IntegerField(default=0)
    step = models.IntegerField(default=0)  # position in learning steps
    last_review = models.DateTimeField(null=True, blank=True)
    suspended = models.BooleanField(default=False)
    created_at = models.DateTimeField(auto_now_add=True)

    class Meta:
        constraints = [models.UniqueConstraint(fields=["note", "ordinal"], name="uniq_card_ordinal")]


class ReviewLog(models.Model):
    card = models.ForeignKey(Card, on_delete=models.CASCADE, related_name="logs")
    rating = models.IntegerField()  # 1 again, 2 hard, 3 good, 4 easy
    state = models.CharField(max_length=12)  # state before the review
    reviewed_at = models.DateTimeField(db_index=True)
    elapsed_days = models.FloatField(default=0)
    scheduled_days = models.FloatField(default=0)
    duration_ms = models.IntegerField(default=0)
    before = models.JSONField(null=True, blank=True)  # card state before, for undo


# --------------------------------------------------------------------- tasks


class Task(models.Model):
    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    title = models.CharField(max_length=500, blank=True, default="")
    description = models.TextField(blank=True, default="")
    done = models.BooleanField(default=False, db_index=True)
    completed_at = models.DateTimeField(null=True, blank=True)
    priority = models.IntegerField(default=0)  # 0 none, 1 low, 2 medium, 3 high
    due = models.DateField(null=True, blank=True, db_index=True)
    start = models.DateField(null=True, blank=True)
    # {freq: day|week|month|year, interval: n}; completing advances the dates instead.
    recurrence = models.JSONField(null=True, blank=True)
    document = models.ForeignKey(
        "Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="tasks"
    )
    project = models.ForeignKey(
        "Document", null=True, blank=True, on_delete=models.SET_NULL, related_name="project_tasks"
    )
    block = models.OneToOneField(
        "Block", null=True, blank=True, on_delete=models.SET_NULL, related_name="task"
    )
    tags = models.ManyToManyField(Tag, blank=True, related_name="tasks")
    position = models.FloatField(default=0)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)


class DocVersion(models.Model):
    """A snapshot of a document's title and blocks, for version history."""

    id = models.UUIDField(primary_key=True, default=uuid.uuid4, editable=False)
    document = models.ForeignKey(Document, on_delete=models.CASCADE, related_name="versions")
    created_at = models.DateTimeField(db_index=True)
    title = models.CharField(max_length=500, blank=True, default="")
    icon = models.CharField(max_length=64, blank=True, default="")
    blocks = models.JSONField(default=list)
    reason = models.CharField(max_length=16, default="auto")  # auto | manual | restore
    block_count = models.IntegerField(default=0)

    class Meta:
        ordering = ["-created_at"]
