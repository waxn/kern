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
    # OR between words means either (like Gmail); a stray OR is just a word.
    assert search.message_queryset("lisbon OR nothing-at-all").count() == search.message_queryset("lisbon").count()
    assert search.message_queryset("lisbon OR").count() == 0


def test_or_groups_parse():
    pq = search.parse("invoice OR receipt OR bill march")
    assert pq.any_of == [["invoice", "receipt", "bill"]]
    assert pq.words == ["march"]


def test_new_operators(loaded):
    total = search.message_queryset("in:anywhere").count()
    assert search.message_queryset("has:pdf").filter(attachment_names__icontains="itinerary.pdf").exists()
    assert not search.message_queryset("has:presentation").filter(attachment_names__icontains="itinerary.pdf").exists()
    assert search.message_queryset("larger:1").count() > 0
    assert search.message_queryset("smaller:1").count() == 0
    assert search.message_queryset("larger:5M").count() < total
    assert search.message_queryset("newer_than:100y").count() > 0
    assert search.message_queryset("older_than:100y").count() == 0
    assert search.message_queryset("domain:bank.test").exists()
    assert not search.message_queryset("-domain:bank.test").filter(from_addr__iendswith="@bank.test").exists()
    assert search.message_queryset("to:me").exists()
    for q in ("is:snoozed", "is:muted", "list:x", "has:link", "after:7d", "before:2020/01/01"):
        list(search.message_queryset(q)[:3])


def test_prefix_on_every_word(loaded):
    assert search.message_queryset("lisb lisbo").exists()


def test_relevance_and_hits(loaded):
    ranked = search.ranked_thread_ids("lisbon")
    assert ranked
    found = search.hits("lisbon", ranked[:5])
    assert any(search.HIT_START in v for v in found.values())
    assert search.ranked_thread_ids("from:me") is None  # nothing to rank by


def test_search_api(api, loaded):
    r = api.get("/api/mail/threads", q="lisbon", sort="relevance").json()
    assert r["threads"] and r["total"] >= len(r["threads"])
    assert "hit" in r["threads"][0] and "who" in r["threads"][0]
    s = api.get("/api/mail/search/suggest", q="from:jo").json()
    assert any("joerg" in p["addr"] for p in s["people"])
    s = api.get("/api/mail/search/suggest", q="lisbon").json()
    assert s["threads"] and s["total"] >= 1
