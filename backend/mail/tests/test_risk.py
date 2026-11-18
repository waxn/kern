import pytest

from mail import risk
from mail.models import Message
from mail.risk import auth as auth_mod
from mail.risk.domains import looks_like, org_domain, skeleton
from mail.risk.rules import RiskInput

pytestmark = pytest.mark.django_db


def rules_of(m):
    return {f["rule"] for f in m.risk_findings}


def test_phish_is_high_with_explanations(loaded):
    m = Message.objects.get(message_id="phish1@paypa1-secure.test")
    assert m.risk_level == "high"
    fired = rules_of(m)
    assert {"dmarc_fail", "brand_impersonation", "reply_to_mismatch", "link_text_mismatch", "link_ip",
            "dangerous_attachment"} <= fired
    assert all(f["reason"] and f["title"] for f in m.risk_findings)


def test_forged_authentication_results_ignored(loaded):
    m = Message.objects.get(message_id="forged@evil.example")
    assert m.auth_results["dmarc"] == "fail"  # the top (trusted) header, not the forged "pass"
    assert "dmarc_fail" in rules_of(m)


def test_legit_mail_is_low(loaded):
    for mid in ("m0@sender.test", "qp1@friends.test", "digest@news.shop.test"):
        m = Message.objects.get(message_id=mid)
        assert m.risk_level == "low", (mid, m.risk_findings)


def test_idn_homoglyph_flagged(loaded):
    m = Message.objects.get(subject="Your Apple ID was locked")
    fired = rules_of(m)
    assert "idn_domain" in fired or "brand_lookalike_domain" in fired
    assert m.risk_level in ("medium", "high")


def test_sent_mail_not_scored(loaded):
    m = Message.objects.get(message_id="trip0@manifest.test")
    assert m.risk_findings == [] and m.risk_level == ""


def test_contact_impersonation_after_history(loaded):
    """History rules are skipped during the first sync; rescoring applies them."""
    from django.core.management import call_command

    call_command("reprocess", stage=["risk"], verbosity=0)
    m = Message.objects.get(subject="Quick favour")
    assert "contact_impersonation" in rules_of(m)


def test_auth_results_parsing():
    items = [
        ("Authentication-Results", "other.example; dmarc=pass"),
        ("Authentication-Results", "mx.manifest.test; spf=pass smtp.mailfrom=a@b.test; dkim=fail (bad sig) header.d=b.test; dkim=pass header.d=c.test; dmarc=fail (p=reject) header.from=b.test"),
        ("Received", "from x"),
        ("Authentication-Results", "mx.manifest.test; dmarc=pass"),
    ]
    trusted = auth_mod.trusted_headers(items, "mx.manifest.test")
    assert len(trusted) == 1
    parsed = auth_mod.parse(trusted)
    assert parsed["spf"] == "pass" and parsed["dmarc"] == "fail"
    assert {d["result"] for d in parsed["dkim"]} == {"fail", "pass"}
    assert parsed["spf_domain"] == "b.test"


def test_domain_helpers():
    assert org_domain("mail.paypal.co.uk") == "paypal.co.uk"
    assert looks_like("paypa1.com", "paypal.com")
    assert looks_like("rnicrosoft.com", "microsoft.com")
    assert looks_like("paypal.co", "paypal.com")
    assert not looks_like("paypal.co", "paypal.com", same_name_counts=False)
    assert not looks_like("mail.paypal.com", "paypal.com")
    assert not looks_like("applebees.com", "apple.com")
    assert skeleton("аpple") == skeleton("apple")


def _x(**kw):
    base = dict(from_addr="a@x.test", from_name="", reply_to=[], return_path="", auth={"trusted": True, "spf": "pass",
                "dkim": [{"result": "pass", "domain": "x.test"}], "dmarc": "pass"}, links=[], attachment_names=[],
                brands=risk.brands())
    base.update(kw)
    return RiskInput(**base)


def test_rule_level_examples():
    score, level, f = risk.evaluate(_x(from_name='"support@bank.test"'))
    assert "display_name_address" in {x["rule"] for x in f}
    score, level, f = risk.evaluate(_x(attachment_names=["photo.jpg", "invoice.pdf.exe"]))
    assert "dangerous_attachment" in {x["rule"] for x in f}
    score, level, f = risk.evaluate(_x(links=[("https://evil.test/x", "www.mybank.test")]))
    assert "link_text_mismatch" in {x["rule"] for x in f}
    score, level, f = risk.evaluate(_x(links=[("https://mybank.test/x", "https://www.mybank.test")]))
    assert "link_text_mismatch" not in {x["rule"] for x in f}


def test_raise_risk_only_raises(loaded):
    m = Message.objects.get(message_id="m0@sender.test")
    before_score, before_level = m.risk_score, m.risk_level
    risk.raise_risk(m, [{"rule": "model", "reason": "x", "weight": -50}])
    assert (m.risk_score, m.risk_level) == (before_score, before_level)
    risk.raise_risk(m, [{"rule": "model", "reason": "suspicious", "weight": 70}])
    assert m.risk_level == "high"


def test_rules_described_for_ui():
    d = risk.describe_rules()
    ids = {r["id"] for r in d["rules"]}
    assert "dmarc_fail" in ids and d["thresholds"]["high"] > d["thresholds"]["medium"]
