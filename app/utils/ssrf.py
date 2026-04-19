"""SSRF guard — reject URLs that resolve to private/internal/loopback IPs.

Used by webhooks, web search page fetcher, and Google Docs / URL imports
to prevent server-side request forgery against cloud metadata endpoints
(e.g. http://169.254.169.254/), localhost services, or RFC1918 networks.
"""

from __future__ import annotations

import ipaddress
import socket
from urllib.parse import urlparse


def is_private_url(url: str) -> bool:
    """Return True if *url*'s hostname resolves to a private/internal IP.

    Conservative: returns True on parse errors, DNS failures, or any
    address that is private, loopback, link-local, multicast, or reserved.
    Resolves the hostname so DNS-rebinding host names that point at
    internal IPs are also blocked.
    """
    try:
        parsed = urlparse(url)
        hostname = parsed.hostname
        if not hostname:
            return True
        port = parsed.port or (443 if parsed.scheme == "https" else 80)
        addr_info = socket.getaddrinfo(hostname, port, proto=socket.IPPROTO_TCP)
        for _family, _stype, _proto, _canon, sockaddr in addr_info:
            ip = ipaddress.ip_address(sockaddr[0])
            if (
                ip.is_private
                or ip.is_loopback
                or ip.is_link_local
                or ip.is_multicast
                or ip.is_reserved
                or ip.is_unspecified
            ):
                return True
    except (socket.gaierror, ValueError, OSError):
        return True
    return False
