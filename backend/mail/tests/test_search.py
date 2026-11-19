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


def test_fulltext(loaded):
    assert search.message_queryset("lisbo").exists()  # prefix match
    assert search.message_queryset("brulee").exists()  # unaccent
    assert search.message_queryset('"tram 28"').count() == 0
    assert search.message_queryset("lisbon -yes").count() == 1


def test_fts_syntax_in_user_text_is_harmless(loaded):
    # FTS5 operators and quotes typed by the user are searched for, never interpreted.
    for q in ['NEAR(a b)', 'a OR', '"unbalanced', 'x*', 'col:term', '^start', 'AND', '(', ')', 'subject:"', '-', '""']:
        list(search.message_queryset(q)[:5])
    assert search.message_queryset("lisbon OR nothing-at-all").count() == 0  # OR is a word here
