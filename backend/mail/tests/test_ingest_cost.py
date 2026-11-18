"""The first sync of a big mailbox must stay roughly linear in queries."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from mail.models import Message
from mail.testing import corpus

pytestmark = pytest.mark.django_db


def test_long_thread_sync_is_linear(engine, server):
    for item in corpus.huge_thread(200):
        server.deliver("INBOX", item.raw, item.flags, item.date)
    with CaptureQueriesContext(connection) as ctx:
        engine.sync_all()
    assert Message.objects.count() == 200
    per_message = len(ctx.captured_queries) / 200
    print(f"{per_message:.1f} queries per message")
    assert per_message < 40, per_message
    t = Message.objects.first().thread
    assert t.message_count == 200 and t.last_date is not None
