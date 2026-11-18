"""Package tracking: rule-based detection from shipping emails."""

from datetime import date, datetime, timezone

import pytest

from mail import packages
from mail.models import Shipment


# --- check digits ---------------------------------------------------------------

@pytest.mark.parametrize("fn,good,bad", [
    (packages.ups_valid, "1Z999AA10123456784", "1Z999AA10123456785"),
    (packages.s10_valid, "RR123456785SE", "RR123456784SE"),
    (packages.fedex12_valid, "986578788855", "986578788856"),
    (packages.dhl10_valid, "3318810025", "3318810026"),
    (packages.mod10_31_valid, "9400111202555842332669", "9400111202555842332668"),
])
def test_check_digits(fn, good, bad):
    assert fn(good) and not fn(bad)


# --- status ---------------------------------------------------------------------

@pytest.mark.parametrize("subject,status", [
    ("Your package will be delivered tomorrow", "in_transit"),
    ("Delivered: Your Amazon package", "delivered"),
    ("UPS Update: Package Delivered", "delivered"),
    ("Out for delivery: arriving today", "out_for_delivery"),
    ("Ihr Paket wird heute zugestellt", "out_for_delivery"),
    ("Ditt paket kan hämtas", "ready_for_pickup"),
    ("We missed you - delivery attempted", "exception"),
    ("Your order has shipped", "in_transit"),
    ("We're getting your order ready", "ordered"),
])
def test_status(subject, status):
    assert packages.detect_status(subject, "") == status


def test_expected_dates():
    sent = datetime(2026, 11, 16, 9, tzinfo=timezone.utc)  # a Monday
    assert packages.expected_date("Arriving tomorrow", sent) == (date(2026, 11, 17), "Tomorrow")
    assert packages.expected_date("Estimated delivery: Thursday, November 19", sent)[0] == date(2026, 11, 19)
    assert packages.expected_date("Scheduled delivery: Friday", sent)[0] == date(2026, 11, 20)
    assert packages.expected_date("Expected delivery 2026-12-01", sent)[0] == date(2026, 12, 1)
    # December mail promising January -> next year.
    assert packages.expected_date("Estimated delivery: January 4", datetime(2026, 12, 20))[0] == date(2027, 1, 4)
    assert packages.expected_date("Nothing to see here", sent) == (None, "")


def test_no_shipping_words_no_scan():
    assert packages.scan("Hi", "1Z999AA10123456784", "a@b.test", None).packages == []


def test_digit_only_numbers_need_the_carrier_named():
    text = "Your parcel tracking number is 986578788855"
    # Named carrier but no tracking word right before the digits: an invoice, not a parcel.
    assert packages.scan("FedEx invoice", "Shipping invoice 986578788855 from FedEx", "a@b.test", None).packages == []
    assert packages.scan("Shipped", text, "shop@x.test", None).packages == []
    assert packages.scan("Shipped", text + " (FedEx)", "shop@x.test", None).packages[0].carrier == "fedex"
    assert packages.scan("Shipped", text, "track@fedex.com", None).packages[0].carrier == "fedex"


def test_track_urls_are_carrier_pages():
    assert packages.track_url("ups", "1Z999AA10123456784").startswith("https://www.ups.com/")
    assert packages.track_url("post", "RR123456785XX") == ""
    assert packages.track_url("nope", "x") == ""


# --- pipeline + API over the corpus --------------------------------------------

def _ship(number):
    return Shipment.objects.get(number=number)


def test_corpus_shipments(loaded):
    numbers = set(Shipment.objects.values_list("number", flat=True))
    assert numbers == {"1Z999AA10123456784", "9400111202555842332669", "RR123456785SE", "986578788855", "TBA312345678901"}

    ups = _ship("1Z999AA10123456784")
    assert ups.status == "delivered"           # the later UPS email wins
    assert ups.merchant == "Northwind Outfitters"  # from the shop, not the carrier
    assert len(ups.message_keys) == 2
    assert ups.thread.subject.startswith("Your order #40019")  # opens the shop's email, not UPS's

    assert _ship("9400111202555842332669").status == "out_for_delivery"
    pn = _ship("RR123456785SE")
    assert (pn.carrier, pn.status) == ("postnord", "ready_for_pickup")
    fx = _ship("986578788855")
    assert fx.status == "in_transit" and fx.expected and fx.expected.weekday() == 0
    amz = _ship("TBA312345678901")
    assert amz.carrier == "amazon" and amz.expected_text == "Tomorrow"


def test_older_email_does_not_roll_back_status(db, server, engine):
    from mail.testing import corpus

    items = corpus.by_name()
    server.deliver("INBOX", items["ship-ups-delivered"].raw, [], items["ship-ups-delivered"].date)
    engine.sync_all()
    server.deliver("INBOX", items["ship-ups-shipped"].raw, [], items["ship-ups-shipped"].date)
    engine.sync_all()
    assert _ship("1Z999AA10123456784").status == "delivered"


def test_sent_and_junk_are_ignored(db, server, engine):
    from mail.testing import corpus

    raw = corpus.by_name()["ship-fedex"].raw
    server.deliver("Junk", raw, [])
    engine.sync_all()
    assert not Shipment.objects.exists()


def test_packages_api(api, loaded):
    from django.utils import timezone

    Shipment.objects.update(status_at=timezone.now())  # corpus dates are weeks old; make them current
    r = api.get("/api/packages").json()
    active = {p["number"]: p for p in r["active"]}
    assert "1Z999AA10123456784" not in active
    assert [p["number"] for p in r["delivered"]] == ["1Z999AA10123456784"]
    usps = active["9400111202555842332669"]
    assert usps["step"] == 2 and usps["statusLabel"] == "Out for delivery"
    assert usps["trackUrl"].startswith("https://tools.usps.com/")
    assert usps["threadId"]

    # Hide and mark delivered.
    fx = active["986578788855"]
    assert api.post(f"/api/packages/{fx['id']}", {"action": "delivered"}).json()["status"] == "delivered"
    assert api.post(f"/api/packages/{fx['id']}", {"action": "hide"}).status_code == 200
    r = api.get("/api/packages").json()
    assert "986578788855" not in {p["number"] for p in r["active"] + r["delivered"]}
    assert api.post(f"/api/packages/{fx['id']}", {"action": "bogus"}).status_code == 400

    # Thread list chip and thread detail card.
    t = api.get(f"/api/threads/{usps['threadId']}").json()
    assert [p["number"] for p in t["packages"]] == ["9400111202555842332669"]
    from mail.models import Folder, FolderRole

    view = f"folder:{Folder.objects.get(role=FolderRole.INBOX).id}"
    inbox = api.get("/api/threads", view=view, limit=200).json()["threads"]
    chips = [x["package"] for x in inbox if x["package"]]
    assert {"status": "out_for_delivery", "label": "Out for delivery"} in chips
    # The carrier's own email carries the chip too, not just the shop's.
    by_subject = {x["subject"]: x["package"] for x in inbox}
    assert by_subject["UPS Update: Package Delivered"]["status"] == "delivered"
    assert by_subject["Your order #40019 has shipped!"]["status"] == "delivered"
    ups_thread = next(x["id"] for x in inbox if x["subject"] == "UPS Update: Package Delivered")
    assert [p["number"] for p in api.get(f"/api/threads/{ups_thread}").json()["packages"]] == ["1Z999AA10123456784"]


def test_packages_api_needs_login(db, anon):
    assert anon.get("/api/packages").status_code == 401


def test_status_change_emits_live_event(db, server, engine):
    from mail.models import ChangeEvent
    from mail.testing import corpus

    items = corpus.by_name()
    engine.sync_all()  # first sync done, so later mail is "live"
    server.deliver("INBOX", items["ship-ups-shipped"].raw, [], items["ship-ups-shipped"].date)
    engine.sync_all()
    server.deliver("INBOX", items["ship-ups-delivered"].raw, [], items["ship-ups-delivered"].date)
    engine.sync_all()
    statuses = [e.data["status"] for e in ChangeEvent.objects.filter(kind="package").order_by("id")]
    assert statuses[-1] == "delivered"


def test_stale_shipments_drop_off(api, loaded):
    from datetime import timedelta

    from django.utils import timezone

    old = timezone.now() - timedelta(days=40)
    Shipment.objects.filter(number="TBA312345678901").update(status_at=old, expected=old.date())
    Shipment.objects.filter(number="986578788855").update(status_at=old, expected=None)
    Shipment.objects.filter(number="RR123456785SE").update(status_at=old, expected=(timezone.now() + timedelta(days=2)).date())
    active = {p["number"] for p in api.get("/api/packages").json()["active"]}
    assert "TBA312345678901" not in active and "986578788855" not in active
    assert "RR123456785SE" in active  # still expected soon
