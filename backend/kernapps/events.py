"""Pushes to a Kern repository deploy the apps that follow its branch (auto-deploy on)."""
import logging

from notes import gitevents

log = logging.getLogger("kern.apps")


@gitevents.on_push
def on_push(event: gitevents.PushEvent):
    from . import deploy
    from .models import App

    apps = list(App.objects.filter(owner=event.uid, source="kern", repo=event.repo, auto_deploy=True))
    for app in apps:
        for u in event.updates:
            if u.branch == app.branch and not u.deleted:
                special = {"kern:ai": ("ai", "AI builder"), "kern:create": ("create", "")}
                if event.pusher in special:
                    trigger, who = special[event.pusher]
                elif event.pusher.startswith("kern:"):  # saved in the app's Files tab
                    trigger, who = "edit", event.pusher.removeprefix("kern:")
                else:
                    trigger, who = "push", event.pusher
                deploy.queue(app, trigger, who, sha=u.new)


def repo_renamed(uid: int, old: str, new: str) -> None:
    from .models import App

    App.objects.filter(owner=uid, source="kern", repo=old).update(repo=new)


def repo_deleted(uid: int, name: str) -> None:
    """The apps keep running their last deployment; new deploys say the repository is gone."""
    from .models import App

    App.objects.filter(owner=uid, source="kern", repo=name).update(auto_deploy=False)
