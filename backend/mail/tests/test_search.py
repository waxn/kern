import pytest
from django.db import connection

from mail import search
from mail.models import Message

pytestmark = pytest.mark.django_db


def test_query_parser():
    pq = search.parse('from:alice "exact phrase" -spam is:unread in:"Sent Items" word')
    assert ("from", "alice", False) in pq.ops
    assert ("in", "Sent Items", False) in pq.ops
    assert pq.phrases == ["exact phrase"]
    assert pq.negated == ["spam"]
    assert pq.words == ["word"]


def test_unbalanced_quotes_do_not_crash(db):
    list(search.message_queryset('"unterminated from:'))


def test_trash_and_junk_excluded_unless_asked(loaded):
    from mail import actions

    m = Message.objects.get(subject="Lunch on Friday?")
    actions.trash(m.thread, None)
    assert not search.message_queryset("lunch").filter(pk=m.pk).exists()
    assert search.message_queryset("lunch in:trash").filter(pk=m.pk).exists()


@pytest.mark.skipif(connection.vendor != "postgresql", reason="Postgres full-text search (runs in Docker)")
def test_postgres_fulltext(loaded):
    assert search.message_queryset("lisbo").exists()  # prefix match
    assert search.message_queryset("brulee").exists()  # unaccent
    assert search.message_queryset('"tram 28"').count() == 0
    assert search.message_queryset("lisbon -yes").count() == 1
