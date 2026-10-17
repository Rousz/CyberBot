"""Testler internetsiz çalışır: localhost dışına her bağlantı ve DNS sorgusu hata verir.

Böylece VM'den borsalara yanlışlıkla istek atılması testlerde imkânsızdır.
"""

import socket

import pytest

_LOCAL_HOSTS = {"127.0.0.1", "::1", "localhost", "", None}
_real_connect = socket.socket.connect
_real_connect_ex = socket.socket.connect_ex
_real_getaddrinfo = socket.getaddrinfo


def _host(address):
    return address[0] if isinstance(address, tuple) else address


def _check(address):
    if isinstance(address, (str, bytes)) or _host(address) in _LOCAL_HOSTS:
        return  # unix soketleri ve localhost serbest
    raise RuntimeError(f"Testlerde ağ erişimi yasak: {address!r}")


def _guarded_connect(self, address):
    _check(address)
    return _real_connect(self, address)


def _guarded_connect_ex(self, address):
    _check(address)
    return _real_connect_ex(self, address)


def _guarded_getaddrinfo(host, *args, **kwargs):
    if host not in _LOCAL_HOSTS:
        raise RuntimeError(f"Testlerde DNS sorgusu yasak: {host!r}")
    return _real_getaddrinfo(host, *args, **kwargs)


@pytest.fixture(autouse=True)
def no_network(monkeypatch):
    monkeypatch.setattr(socket.socket, "connect", _guarded_connect)
    monkeypatch.setattr(socket.socket, "connect_ex", _guarded_connect_ex)
    monkeypatch.setattr(socket, "getaddrinfo", _guarded_getaddrinfo)
