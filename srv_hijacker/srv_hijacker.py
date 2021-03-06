import os
import re

from socket import error as SocketError, timeout as SocketTimeout

from urllib3.connection import HTTPConnection
from urllib3.exceptions import (NewConnectionError, ConnectTimeoutError)
from urllib3.util import connection

from dns import resolver

import logging

logger = logging.getLogger("srv_hijacker")


def resolve_ip_for_target(rrsets, target):
    for rrset in rrsets:
        if rrset.name == target:
            return rrset.items[0].address

    raise NewConnectionError("Couldn't find A record for target %s" % target)


def resolve_srv_record(old_host, resolver):
    ans = resolver.query(old_host, 'SRV')

    new_port = ans[0].port
    new_host = resolve_ip_for_target(ans.response.additional, ans[0].target)

    logger.debug("Resolved SRV record for host %s: (%s:%s)", old_host,
                 new_host, new_port)

    return new_host, new_port


original_new_conn = HTTPConnection._new_conn


def patched_new_conn(url_regex, srv_resolver):
    """
    Returns a function that does pretty much what
    `urllib3.connection.HTTPConnection._new_conn` does.

    url_regex:

    The regex to match a host against. If this regex matches the host, we
    hit the srv_resolver to fetch the new host + port
    """

    def patched_f(self):
        if re.search(url_regex, self.host):
            logger.debug("Host %s matched SRV regex, resolving", self.host)
            self.host, self.port = resolve_srv_record(self.host, srv_resolver)
        else:
            logger.debug("Host %s did not match SRV regex, ignoring",
                         self.host)

        return original_new_conn(self)

    return patched_f


def hijack(host_regex, srv_dns_host=None, srv_dns_port=None):
    """
    Usage:

    ```
    srv_hijacker.hijack(
        host_regex=r'service.consul$',
        srv_dns_host='127.0.0.1',
        srv_dns_port=8600
    )
    ```
    """
    srv_resolver = resolver.Resolver()
    if srv_dns_host:
        srv_resolver.nameservers = [srv_dns_host]
    if srv_dns_port:
        srv_resolver.port = int(srv_dns_port)

    HTTPConnection._new_conn = patched_new_conn(host_regex, srv_resolver)
