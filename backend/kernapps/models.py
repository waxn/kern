"""Apps: small programs that Kern runs for you, each served at its own path (``/<slug>/``).

The registry lives in the shared database (like git tokens) because the gateway has to find an app
from its path alone, before anyone is known. Each row names its owner; everything an app does on
disk lives under ``DATA_DIR/apps/<id>/`` (see :mod:`kernapps.paths`).
"""
from django.db import models

ACCESS = [("private", "Only me"), ("users", "Signed-in users"), ("public", "Everyone")]
SOURCES = [("kern", "Kern repository"), ("url", "Git URL")]
RUNTIMES = [("", "Detect"), ("static", "Static files"), ("python", "Python"), ("node", "Node.js"), ("command", "Command")]

# What the supervisor reports (App.state). "enabled" is what you asked for; this is what is true.
STATES = ["stopped", "starting", "running", "crashed", "building", "failed", "new"]


class App(models.Model):
    owner = models.IntegerField(db_index=True)  # user id (their tenant)
    slug = models.CharField(max_length=40, unique=True)
    name = models.CharField(max_length=80)
    description = models.CharField(max_length=300, blank=True, default="")
    icon = models.CharField(max_length=16, blank=True, default="")  # one emoji
    color = models.CharField(max_length=12, blank=True, default="")  # a chip color name

    # Where the code comes from.
    source = models.CharField(max_length=8, choices=SOURCES, default="kern")
    repo = models.CharField(max_length=64, blank=True, default="")  # Kern repository of the owner
    git_url = models.CharField(max_length=500, blank=True, default="")
    git_token_enc = models.TextField(blank=True, default="")  # secretbox; for private remotes
    branch = models.CharField(max_length=200, default="main")
    subdir = models.CharField(max_length=200, blank=True, default="")  # app root inside the repository
    auto_deploy = models.BooleanField(default=True)  # deploy on every push to the branch

    # How it runs. Empty values come from .kern/app.yml or detection.
    runtime = models.CharField(max_length=8, choices=RUNTIMES, blank=True, default="")
    build_cmd = models.CharField(max_length=500, blank=True, default="")
    start_cmd = models.CharField(max_length=500, blank=True, default="")
    health_path = models.CharField(max_length=200, blank=True, default="")
    env_enc = models.TextField(blank=True, default="")  # secretbox JSON {name: value}

    # Who can open /<slug>/.
    access = models.CharField(max_length=8, choices=ACCESS, default="private")
    public_paths = models.JSONField(default=list, blank=True)  # prefixes open to everyone, e.g. "/api/ingest"
    strip_prefix = models.BooleanField(default=True)  # the app sees "/x" for "/<slug>/x"

    enabled = models.BooleanField(default=True)  # keep it running (also after a restart of the server)
    secret = models.CharField(max_length=64)  # sent to the app as KERN_APP_SECRET (trust X-Kern-User)
    hook_secret = models.CharField(max_length=64)  # deploy hook URL

    state = models.CharField(max_length=10, default="new")
    state_detail = models.CharField(max_length=500, blank=True, default="")
    state_at = models.DateTimeField(null=True, blank=True)
    live = models.ForeignKey("Deployment", null=True, blank=True, on_delete=models.SET_NULL, related_name="+")

    created = models.DateTimeField(auto_now_add=True)
    updated = models.DateTimeField(auto_now=True)

    class Meta:
        ordering = ["name"]


class Deployment(models.Model):
    """One build of one commit. Its files live in ``releases/<number>`` and its log in ``logs/deploy-<number>.log``."""

    app = models.ForeignKey(App, on_delete=models.CASCADE, related_name="deployments")
    number = models.PositiveIntegerField()
    sha = models.CharField(max_length=64, blank=True, default="")
    ref = models.CharField(max_length=200, blank=True, default="")
    subject = models.CharField(max_length=300, blank=True, default="")
    trigger = models.CharField(max_length=12, default="manual")  # manual | push | hook | ai | rollback | create | edit
    who = models.CharField(max_length=150, blank=True, default="")
    status = models.CharField(max_length=10, default="queued")  # queued | building | starting | live | failed | old | cancelled
    error = models.CharField(max_length=1000, blank=True, default="")
    runtime = models.CharField(max_length=8, blank=True, default="")
    rollback_of = models.PositiveIntegerField(null=True, blank=True)  # reuse that release's files
    created = models.DateTimeField(auto_now_add=True)
    started = models.DateTimeField(null=True, blank=True)
    finished = models.DateTimeField(null=True, blank=True)

    class Meta:
        ordering = ["-number"]
        unique_together = [("app", "number")]


class BuilderChat(models.Model):
    """The AI builder's conversation for one app. ``progress`` lists what the current turn has done so far."""

    app = models.OneToOneField(App, on_delete=models.CASCADE, related_name="chat")
    transcript = models.JSONField(default=list)  # what the screen shows
    history = models.JSONField(default=list)  # what the model sees (provider format)
    provider = models.CharField(max_length=10, blank=True, default="")
    status = models.CharField(max_length=8, default="idle")  # idle | queued | running
    pending = models.TextField(blank=True, default="")  # the message waiting to run
    progress = models.JSONField(default=list)
    stop = models.BooleanField(default=False)
    updated = models.DateTimeField(auto_now=True)
