import pytest

from mail.aicontext import context_note, thread_context
from mail.models import Message

pytestmark = pytest.mark.django_db


def test_thread_context_has_the_mail(loaded):
    m = Message.objects.get(subject="Lunch on Friday?")
    subject, text = thread_context(m.thread_id)
    assert subject == "Lunch on Friday?"
    assert m.from_addr in text and "Subject: Lunch on Friday?" in text


def test_context_note_marks_mail_untrusted(loaded):
    m = Message.objects.get(subject="Lunch on Friday?")
    note = context_note(m.thread_id)
    assert "UNTRUSTED DATA" in note and note.rstrip().endswith("</email>")
    assert note.count("</email>") == 1


def test_unknown_thread_adds_nothing(loaded):
    assert context_note(999999) == "" and context_note("x") == ""
