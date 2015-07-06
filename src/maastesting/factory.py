# Copyright 2012-2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Test object factories."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "factory",
    "NO_VALUE",
    "TooManyRandomRetries",
    ]

import datetime
from functools import partial
import httplib
import io
from itertools import (
    count,
    imap,
    islice,
    repeat,
    )
import os
import os.path
import random
import string
import subprocess
import time
import urllib2
import urlparse
from uuid import uuid1

from maastesting.fixtures import TempDirectory
import mock
from netaddr import (
    IPAddress,
    IPNetwork,
    )

# Occasionally a parameter needs separate values for None and "no value
# given, make one up."  In that case, use NO_VALUE as the default and
# accept None as a normal value.
NO_VALUE = object()


class TooManyRandomRetries(Exception):
    """Something that relies on luck did not get lucky.

    Some factory methods need to generate random items until they find one
    that meets certain requirements.  This exception indicates that it took
    too many retries, which may mean that no matching item is possible.
    """


def network_clashes(network, other_networks):
    """Does the IP range for `network` clash with any in `other_networks`?

    :param network: An `IPNetwork`.
    :param other_networks: An iterable of `IPNetwork` items.
    :return: Whether the IP range for `network` overlaps with any of those
        for the networks in `other_networks`.
    """
    for other_network in other_networks:
        if network in other_network or other_network in network:
            return True
    return False


class Factory:

    random_letters = imap(
        random.choice, repeat(string.letters + string.digits))

    random_letters_with_spaces = imap(
        random.choice, repeat(string.letters + string.digits + ' '))

    # See django.contrib.auth.forms.UserCreationForm.username.
    random_letters_for_usernames = imap(
        random.choice, repeat(string.letters + '.@+-'))

    random_http_responses = imap(
        random.choice, repeat(tuple(httplib.responses)))

    random_octet = partial(random.randint, 0, 255)

    random_octets = iter(random_octet, None)

    def make_string(self, size=10, spaces=False, prefix=""):
        if spaces:
            return prefix + "".join(
                islice(self.random_letters_with_spaces, size))
        else:
            return prefix + "".join(islice(self.random_letters, size))

    def make_bytes(self, size=10):
        """Return a `bytes` filled with random data."""
        return os.urandom(size)

    def make_username(self, size=10):
        """Create an arbitrary user name (but not the actual user)."""
        return "".join(islice(self.random_letters_for_usernames, size))

    def make_email_address(self, login_size=10):
        """Generate an arbitrary email address."""
        return "%s@example.com" % self.make_string(size=login_size)

    def make_status_code(self):
        """Return an arbitrary HTTP status code."""
        return next(self.random_http_responses)

    exception_type_names = (b"TestException#%d" % i for i in count(1))

    def make_exception_type(self, bases=(Exception,), **namespace):
        return type(next(self.exception_type_names), bases, namespace)

    def make_exception(self, message=None, bases=(Exception,), **namespace):
        exc_type = self.make_exception_type(bases, **namespace)
        return exc_type() if message is None else exc_type(message)

    def pick_bool(self):
        """Return an arbitrary Boolean value (`True` or `False`)."""
        return random.choice((True, False))

    def pick_port(self, port_min=1024, port_max=65535):
        assert port_min >= 0 and port_max <= 65535
        return random.randint(port_min, port_max)

    def make_vlan_tag(self, allow_none=False, but_not=None):
        """Create a random VLAN tag.

        :param allow_none: Whether `None` ("no VLAN") can be allowed as an
            outcome.  If `True`, `None` will be included in the possible
            results with a deliberately over-represented probability, in order
            to help trip up bugs that might only show up once in about 4094
            calls otherwise.
        :param but_not: A list of tags that should not be returned.  Any zero
            or `None` entries will be ignored.
        """
        if but_not is None:
            but_not = []
        if allow_none and self.pick_bool():
            return None
        else:
            for _ in range(100):
                vlan_tag = random.randint(1, 0xffe)
                if vlan_tag not in but_not:
                    return vlan_tag
            raise TooManyRandomRetries("Could not find an available VLAN tag.")

    def make_ipv4_address(self):
        octets = islice(self.random_octets, 4)
        return '%d.%d.%d.%d' % tuple(octets)

    def make_ipv6_address(self):
        # We return from the fc00::/7 space because that's a private
        # space and shouldn't cause problems of addressing the outside
        # world.
        network = IPNetwork('fc00::/7')
        # We can't use random.choice() because there are too many
        # elements in network.
        random_address_index = random.randint(0, network.size - 1)
        return unicode(IPAddress(network[random_address_index]))

    def make_ip_address(self):
        if random.randint(0, 1):
            return self.make_ipv6_address()
        else:
            return self.make_ipv4_address()

    def make_UUID(self):
        return unicode(uuid1())

    def _make_random_network(
            self, slash=None, but_not=None, disjoint_from=None,
            random_address_factory=None):
        """Generate a random IP network.

        :param slash: Netmask or bit width of the network, e.g. 24 or
            '255.255.255.0' for what used to be known as a class-C network.
        :param but_not: Optional iterable of `IPNetwork` objects whose values
            should not be returned.  Use this when you need a different network
            from any returned previously.  The new network may overlap any of
            these, but it won't be identical.
        :param disjoint_from: Optional iterable of `IPNetwork` objects whose
            IP ranges the new network must not overlap.
        :param random_address_factory: A callable that returns a random IP
            address. If not provided, will default to
            Factory.make_ipv4_address().
        :return: A network spanning at least 8 IP addresses (at most 29 bits).
        :rtype: :class:`IPNetwork`
        """
        if but_not is None:
            but_not = []
        but_not = frozenset(but_not)
        if disjoint_from is None:
            disjoint_from = []
        if slash is None:
            slash = random.randint(16, 29)
        if random_address_factory is None:
            random_address_factory = self.make_ipv4_address
        # Look randomly for a network that matches our criteria.
        for _ in range(100):
            network = IPNetwork('%s/%s' % (random_address_factory(), slash))
            forbidden = (network in but_not)
            clashes = network_clashes(network, disjoint_from)
            if not forbidden and not clashes:
                return network
        raise TooManyRandomRetries("Could not find available network")

    def make_ipv4_network(self, slash=None, but_not=None, disjoint_from=None):
        """Generate a random IPv4 network.

        :param slash: Netmask or bit width of the network, e.g. 24 or
            '255.255.255.0' for what used to be known as a class-C network.
        :param but_not: Optional iterable of `IPNetwork` objects whose values
            should not be returned.  Use this when you need a different network
            from any returned previously.  The new network may overlap any of
            these, but it won't be identical.
        :param disjoint_from: Optional iterable of `IPNetwork` objects whose
            IP ranges the new network must not overlap.
        :return: A network spanning at least 8 IP addresses (at most 29 bits).
        :rtype: :class:`IPNetwork`
        """
        if slash is None:
            slash = random.randint(16, 29)
        return self._make_random_network(
            slash=slash, but_not=but_not, disjoint_from=disjoint_from,
            random_address_factory=self.make_ipv4_address)

    def make_ipv6_network(self, slash=None, but_not=None, disjoint_from=None):
        """Generate a random IPv6 network.

        :param slash: Netmask or bit width of the network. If not
            specified, will default to a bit width of between 112 (65536
            addresses) and 125 (8 addresses);
        :param but_not: Optional iterable of `IPNetwork` objects whose values
            should not be returned.  Use this when you need a different network
            from any returned previously.  The new network may overlap any of
            these, but it won't be identical.
        :param disjoint_from: Optional iterable of `IPNetwork` objects whose
            IP ranges the new network must not overlap.
        :return: A network spanning at least 8 IP addresses.
        :rtype: :class:`IPNetwork`
        """
        if slash is None:
            slash = random.randint(112, 125)
        return self._make_random_network(
            slash=slash, but_not=but_not, disjoint_from=disjoint_from,
            random_address_factory=self.make_ipv6_address)

    def pick_ip_in_network(self, network, but_not=None):
        if but_not is None:
            but_not = []
        but_not = [IPAddress(but) for but in but_not if but is not None]
        address = IPAddress(random.randint(network.first, network.last))
        for _ in range(100):
            address = IPAddress(random.randint(network.first, network.last))
            if address not in but_not:
                return bytes(address)
        raise TooManyRandomRetries("Could not find available IP in network")

    def make_ipv4_range(self, network=None, but_not=None):
        """Return a pair of IPv4 addresses.

        :param network: Return IP addresses within this network.
        :param but_not: A pair of addresses that should not be returned.
        :return: A pair of `IPAddress`.
        """
        if network is None:
            network = self.make_ipv4_network()
        if but_not is not None:
            low, high = but_not
            but_not = (IPAddress(low), IPAddress(high))
        for _ in range(100):
            ip_range = tuple(sorted(
                IPAddress(factory.pick_ip_in_network(network))
                for _ in range(2)
                ))
            if ip_range[0] < ip_range[1] and ip_range != but_not:
                return ip_range
        raise TooManyRandomRetries("Could not find available IP range")

    make_ip_range = make_ipv4_range  # DEPRECATED.

    def make_ipv6_range(self, network=None, but_not=None):
        """Return a pair of IPv6 addresses.

        :param network: Return IP addresses within this network.
        :param but_not: A pair of addresses that should not be returned.
        :return: A pair of `IPAddress`.
        """
        if network is None:
            network = self.make_ipv6_network()
        return self.make_ip_range(network=network, but_not=but_not)

    def make_mac_address(self, delimiter=":"):
        assert isinstance(delimiter, unicode)
        octets = islice(self.random_octets, 6)
        return delimiter.join(format(octet, "02x") for octet in octets)

    def make_random_leases(self, num_leases=1):
        """Create a dict of arbitrary ip-to-mac address mappings."""
        # This could be a dict comprehension, but the current loop
        # guards against shortfalls as random IP addresses collide.
        leases = {}
        while len(leases) < num_leases:
            leases[self.make_ipv4_address()] = self.make_mac_address()
        return leases

    def make_date(self, year=2011):
        start = time.mktime(datetime.datetime(year, 1, 1).timetuple())
        end = time.mktime(datetime.datetime(year + 1, 1, 1).timetuple())
        stamp = random.randrange(start, end)
        return datetime.datetime.fromtimestamp(stamp)

    def make_timedelta(self):
        return datetime.timedelta(
            days=random.randint(0, 3 * 365),
            seconds=random.randint(0, 24 * 60 * 60 - 1),
            microseconds=random.randint(0, 999999))

    def make_file(self, location, name=None, contents=None):
        """Create a file, and write data to it.

        Prefer the eponymous convenience wrapper in
        :class:`maastesting.testcase.MAASTestCase`.  It creates a temporary
        directory and arranges for its eventual cleanup.

        :param location: Directory.  Use a temporary directory for this, and
            make sure it gets cleaned up after the test!
        :param name: Optional name for the file.  If none is given, one will
            be made up.
        :param contents: Optional contents for the file.  If omitted, some
            arbitrary ASCII text will be written.
        :type contents: unicode, but containing only ASCII characters.
        :return: Path to the file.
        """
        if name is None:
            name = self.make_string()
        if contents is None:
            contents = self.make_string().encode('ascii')
        path = os.path.join(location, name)
        with open(path, 'w') as f:
            f.write(contents)
        return path

    def make_name(self, prefix=None, sep='-', size=6):
        """Generate a random name.

        :param prefix: Optional prefix.  Pass one to help make test failures
            and tracebacks easier to read!  If you don't, you might as well
            use `make_string`.
        :param sep: Separator that will go between the prefix and the random
            portion of the name.  Defaults to a dash.
        :param size: Length of the random portion of the name.  Don't get
            hung up on this; you may need more if uniqueness is really
            important or less if it doesn't but legibility does, but
            generally, use the default.
        :return: A randomized unicode string.
        """
        return sep.join(
            filter(None, [prefix, self.make_string(size=size)]))

    def make_hostname(self, prefix='host', *args, **kwargs):
        """Generate a random hostname.

        The returned hostname is lowercase because python's urlparse
        implicitely lowercases the hostnames."""
        return self.make_name(prefix=prefix, *args, **kwargs).lower()

    # Always select from a scheme that allows parameters in the URL so
    # that we can round-trip a URL with params successfully (otherwise
    # the params don't get parsed out of the path).
    _make_parsed_url_schemes = tuple(
        scheme for scheme in urlparse.uses_params
        if scheme != "")

    def make_parsed_url(
            self, scheme=None, netloc=None, path=None, params=None,
            query=None, fragment=None):
        """Generate a random parsed URL object.

        Contains randomly generated values for all parts of a URL: scheme,
        location, path, parameters, query, and fragment. However, each part
        can be overridden individually.

        :return: Instance of :py:class:`urlparse.ParseResult`.
        """
        if scheme is None:
            # Select a scheme that allows parameters; see above.
            scheme = random.choice(self._make_parsed_url_schemes)
        if netloc is None:
            netloc = "%s.example.com" % self.make_name("netloc").lower()
        if path is None:
            # A leading forward-slash will be added in geturl() if we
            # don't, so ensure it's here now so tests can compare URLs
            # without worrying about it.
            path = self.make_name("/path")
        else:
            # Same here with the forward-slash prefix.
            if not path.startswith("/"):
                path = "/" + path
        if params is None:
            params = self.make_name("params")
        if query is None:
            query = self.make_name("query")
        if fragment is None:
            fragment = self.make_name("fragment")
        return urlparse.ParseResult(
            scheme, netloc, path, params, query, fragment)

    def make_url(
            self, scheme=None, netloc=None, path=None, params=None,
            query=None, fragment=None):
        """Generate a random URL.

        Contains randomly generated values for all parts of a URL: scheme,
        location, path, parameters, query, and fragment. However, each part
        can be overridden individually.

        :return: string
        """
        return self.make_parsed_url(
            scheme, netloc, path, params, query, fragment).geturl()

    def make_simple_http_url(self, netloc=None, path=None):
        """Create an arbitrary HTTP URL with only a location and path."""
        return self.make_parsed_url(
            scheme="http", netloc=netloc, path=path, params="", query="",
            fragment="").geturl()

    def make_names(self, *prefixes):
        """Generate random names.

        Yields a name for each prefix specified.

        :param prefixes: Zero or more prefixes. See `make_name`.
        """
        for prefix in prefixes:
            yield self.make_name(prefix)

    def make_tarball(self, location, contents):
        """Create a tarball containing the given files.

        :param location: Path to a directory where the tarball can be stored.
        :param contents: A dict mapping file names to file contents.  Where
            the value is `None`, the file will contain arbitrary data.
        :return: Path to a gzip-compressed tarball.
        """
        tarball = os.path.join(location, '%s.tar.gz' % self.make_name())
        with TempDirectory() as working_dir:
            source = working_dir.path
            for name, content in contents.items():
                self.make_file(source, name, content)

            subprocess.check_call(['tar', '-C', source, '-czf', tarball, '.'])

        return tarball

    def make_response(self, status_code, content, content_type=None):
        """Return a similar response to that which `urllib2` returns."""
        if content_type is None:
            headers_raw = b""
        else:
            if isinstance(content_type, unicode):
                content_type = content_type.encode("ascii")
            headers_raw = b"Content-Type: %s" % content_type
        headers = httplib.HTTPMessage(io.BytesIO(headers_raw))
        return urllib2.addinfourl(
            fp=io.BytesIO(content), headers=headers,
            url=None, code=status_code)

    def make_streams(self, stdin=None, stdout=None, stderr=None):
        """Make a fake return value for a SSHClient.exec_command."""
        # stdout.read() is called so stdout can't be None.
        if stdout is None:
            stdout = mock.Mock()

        return (stdin, stdout, stderr)

    def make_CalledProcessError(self):
        """Make a fake :py:class:`subprocess.CalledProcessError`."""
        return subprocess.CalledProcessError(
            returncode=random.randint(1, 10),
            cmd=[self.make_name("command")],
            output=factory.make_bytes())

# Create factory singleton.
factory = Factory()
