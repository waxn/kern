from types import SimpleNamespace

import pytest

from mail import imgproxy, unsubscribe
from mail.models import Message

PASS = {"trusted": True, "dkim": [{"result": "pass", "domain": "news.shop.test"}]}


def msg(headers, auth=PASS, sender="digest@news.shop.test"):
    return SimpleNamespace(headers=headers, auth_results=auth, from_addr=sender)


ONE_CLICK = {"list-unsubscribe": "<mailto:u@x.test>, <https://news.shop.test/u?id=1>",
             "list-unsubscribe-post": "List-Unsubscribe=One-Click"}


def test_one_click_needs_post_header_https_and_dkim():
    o = unsubscribe.options(msg(ONE_CLICK))
    assert o.one_click and o.https == "https://news.shop.test/u?id=1" and o.mailto == "mailto:u@x.test"
    assert not unsubscribe.options(msg({"list-unsubscribe": ONE_CLICK["list-unsubscribe"]})).one_click
    assert not unsubscribe.options(msg(ONE_CLICK, auth={"trusted": True, "dkim": [{"result": "fail", "domain": "news.shop.test"}]})).one_click
    # A signature from some other domain doesn't count.
    assert not unsubscribe.options(msg(ONE_CLICK, auth={"trusted": True, "dkim": [{"result": "pass", "domain": "evil.test"}]})).one_click
    assert not unsubscribe.options(msg(ONE_CLICK, auth={})).one_click
    http_only = {**ONE_CLICK, "list-unsubscribe": "<http://news.shop.test/u>"}
    assert unsubscribe.options(msg(http_only)) is None
    assert unsubscribe.options(msg({})) is None


def test_one_click_refuses_private_addresses():
    def resolver(host, port):
        raise imgproxy.ProxyError("refusing non-public address")

    with pytest.raises(imgproxy.ProxyError):
        unsubscribe.one_click("https://internal.test/unsub", resolver=resolver)
    with pytest.raises(imgproxy.ProxyError):
        unsubscribe.one_click("http://news.shop.test/u")


@pytest.mark.django_db
def test_endpoint_falls_back_to_link_without_one_click(loaded, api):
    m = Message.objects.get(message_id="digest@news.shop.test")
    r = api.post(f"/api/messages/{m.pk}/unsubscribe").json()
    assert r["done"] is False and r["url"] == "https://news.shop.test/unsub?u=1"
    detail = api.get(f"/api/threads/{m.thread_id}").json()
    assert detail["messages"][0]["unsubscribe"]["oneClick"] is False
