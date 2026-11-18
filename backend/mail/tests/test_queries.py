"""Guard against N+1 queries: page loads must cost the same with 10 or 100 rows."""

import pytest
from django.db import connection
from django.test.utils import CaptureQueriesContext

from mail.models import Folder, FolderRole, Message, Thread

pytestmark = pytest.mark.django_db


def count(fn):
    with CaptureQueriesContext(connection) as ctx:
        fn()
    return len(ctx.captured_queries)


def test_thread_list_query_count_is_constant(loaded, api, monkeypatch):
    from mail.api import views

    view = f"folder:{Folder.objects.get(role=FolderRole.INBOX).pk}"
    monkeypatch.setattr(views, "PAGE", 3)
    small = count(lambda: api.get("/api/threads", view=view))
    monkeypatch.setattr(views, "PAGE", 25)
    big = count(lambda: api.get("/api/threads", view=view))
    assert big == small, (small, big)
    assert big <= 12


def test_thread_detail_query_count_is_constant(loaded, api):
    huge = Message.objects.filter(message_id__startswith="huge").first().thread
    small = Thread.objects.get(pk=Message.objects.get(subject="Lunch on Friday?").thread_id)
    q_small = count(lambda: api.get(f"/api/threads/{small.pk}"))
    q_huge = count(lambda: api.get(f"/api/threads/{huge.pk}"))  # 200 messages
    assert q_huge <= q_small + 2, (q_small, q_huge)


def test_folder_list_query_count(loaded, api):
    assert count(lambda: api.get("/api/folders")) <= 10
