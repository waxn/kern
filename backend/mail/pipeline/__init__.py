"""Processing pipeline for incoming mail.

Every newly stored message runs through the stages listed in
settings.MAIL_PIPELINE, in order. A stage is a small class:

    class MyStage(Stage):
        name = "my-stage"
        version = 1                # bump to make `reprocess` re-run it
        def applies(self, ctx): ...  # optional filter
        def run(self, ctx): ...      # mutate ctx.message (save what you change)
                                     # return PENDING if the work is not finished yet and
                                     # something else will finish it later

The context gives each stage the stored Message and the parsed MIME
(ParsedMessage) so nothing is re-parsed. Completed stages are recorded in
Message.pipeline as {name: version}; `manage.py reprocess` re-runs stages
whose version changed (or a named stage) over existing mail.

Future stages (a local-model phishing signal, a personal spam filter) slot in
here. Risk contract: only RiskStage sets the base score; any later stage may
only ADD findings through mail.risk.raise_risk(), which can never lower the
score or level.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from functools import lru_cache

from django.conf import settings
from django.utils.module_loading import import_string

from ..identity import my_addresses

log = logging.getLogger("kern.mail.pipeline")


PENDING = 0  # recorded in Message.pipeline instead of the version: "started, not finished"


@dataclass
class Context:
    message: object
    parsed: object
    initial: bool = False
    me: set[str] = field(default_factory=my_addresses)

    @property
    def from_me(self) -> bool:
        return self.message.from_addr in self.me


class Stage:
    name = "stage"
    version = 1

    def applies(self, ctx: Context) -> bool:
        return True

    def run(self, ctx: Context) -> None:  # pragma: no cover - interface
        raise NotImplementedError


@lru_cache(maxsize=1)
def load_stages() -> list[Stage]:
    return [import_string(path)() for path in settings.MAIL_PIPELINE]


def run_pipeline(message, parsed, *, initial: bool = False, only: set[str] | None = None,
                 force: bool = False) -> None:
    ctx = Context(message=message, parsed=parsed, initial=initial)
    done = dict(message.pipeline or {})
    for stage in load_stages():
        if only and stage.name not in only:
            continue
        if not force and done.get(stage.name) == stage.version:
            continue
        if not stage.applies(ctx):
            continue
        result = stage.run(ctx)
        done[stage.name] = PENDING if result is PENDING else stage.version
    message.pipeline = done
    message.save(update_fields=["pipeline"])
