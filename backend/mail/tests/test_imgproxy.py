import pytest

from mail import imgproxy


@pytest.mark.parametrize("ip", ["127.0.0.1", "10.0.0.5", "172.16.3.4", "192.168.1.1", "169.254.169.254",
                                "100.64.0.1", "0.0.0.0", "::1", "fc00::1", "fe80::1", "::ffff:127.0.0.1",
                                "224.0.0.1", "240.0.0.1"])
def test_private_addresses_refused(ip):
    assert not imgproxy.is_public_ip(ip)


def test_public_address_allowed():
    assert imgproxy.is_public_ip("93.184.215.14")
    assert imgproxy.is_public_ip("2606:4700::1111")


def test_signature():
    url = "https://img.example/a.png"
    sig = imgproxy.sign(url)
    assert imgproxy.verify(url, sig)
    assert not imgproxy.verify(url + "x", sig)
    assert not imgproxy.verify(url, "")


def test_fetch_refuses_internal_hosts():
    with pytest.raises(imgproxy.ProxyError):
        imgproxy.fetch("http://localhost:8000/healthz")
    with pytest.raises(imgproxy.ProxyError):
        imgproxy.fetch("http://169.254.169.254/latest/meta-data")
    with pytest.raises(imgproxy.ProxyError):
        imgproxy.fetch("file:///etc/passwd")
    with pytest.raises(imgproxy.ProxyError):
        imgproxy.fetch("http://user:pw@example.com/x.png")


def test_dns_rebinding_resolver_is_checked():
    calls = []

    def resolver(host, port):
        calls.append(host)
        raise imgproxy.ProxyError("refusing non-public address")

    with pytest.raises(imgproxy.ProxyError):
        imgproxy.fetch("https://rebind.example/x.png", resolver=resolver)
    assert calls == ["rebind.example"]
