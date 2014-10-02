# Copyright 2014 Canonical Ltd.  This software is licensed under the
# GNU Affero General Public License version 3 (see the file LICENSE).

"""Obtain OS information from clusters."""

from __future__ import (
    absolute_import,
    print_function,
    unicode_literals,
    )

str = None

__metaclass__ = type
__all__ = [
    "compose_curtin_network_preseed",
    "gen_all_known_operating_systems",
    "get_preseed_data",
    "validate_license_key",
    "validate_license_key_for",
]

from collections import defaultdict
from functools import partial
from urlparse import urlparse

from maasserver.enum import BOOT_RESOURCE_TYPE
from maasserver.models import BootResource
from maasserver.rpc import (
    getAllClients,
    getClientFor,
    )
from maasserver.utils import async
from maasserver.utils.orm import get_one
from provisioningserver.rpc.cluster import (
    ComposeCurtinNetworkPreseed,
    GetOSReleaseTitle,
    GetPreseedData,
    ListOperatingSystems,
    ValidateLicenseKey,
    )
from provisioningserver.utils.twisted import synchronous
from twisted.python.failure import Failure


def get_uploaded_resource_with_name(resources, name):
    """Return the `BootResource` from `resources` that has the given `name`.
    """
    return get_one(resources.filter(name=name))


def fix_custom_osystem_release_titles(osystem):
    """Fix all release titles for the custom OS."""
    custom_resources = BootResource.objects.filter(
        rtype=BOOT_RESOURCE_TYPE.UPLOADED)
    for release in osystem["releases"]:
        resource = get_uploaded_resource_with_name(
            custom_resources, release["name"])
        if resource is not None and "title" in resource.extra:
            release["title"] = resource.extra["title"]
    return osystem


def suppress_failures(responses):
    """Suppress failures returning from an async/gather operation.

    This may not be advisable! Be very sure this is what you want.
    """
    for response in responses:
        if not isinstance(response, Failure):
            yield response


@synchronous
def gen_all_known_operating_systems():
    """Generator yielding details on OSes supported by any cluster.

    Each item yielded takes the same form as the ``osystems`` value from
    the :py:class:`provisioningserver.rpc.cluster.ListOperatingSystems`
    RPC command. Exactly matching duplicates are suppressed.
    """
    seen = defaultdict(list)
    responses = async.gather(
        partial(client, ListOperatingSystems)
        for client in getAllClients())
    for response in suppress_failures(responses):
        for osystem in response["osystems"]:
            name = osystem["name"]
            if osystem not in seen[name]:
                seen[name].append(osystem)
                if name == "custom":
                    osystem = fix_custom_osystem_release_titles(osystem)
                yield osystem


@synchronous
def get_os_release_title(osystem, release):
    """Get the title for the operating systems release."""
    title = ""
    responses = async.gather(
        partial(client, GetOSReleaseTitle, osystem=osystem, release=release)
        for client in getAllClients())
    for response in suppress_failures(responses):
        if response["title"] != "":
            title = response["title"]
    if title == "":
        return None
    return title


@synchronous
def get_preseed_data(preseed_type, node, token, metadata_url):
    """Obtain optional preseed data for this OS, preseed type, and node.

    :param preseed_type: The type of preseed to compose.
    :param node: The node model instance.
    :param token: The token model instance.
    :param metadata_url: The URL where this node's metadata will be made
        available.

    :raises NoConnectionsAvailable: When no connections to the node's
        cluster are available for use.
    :raises NoSuchOperatingSystem: When the node's declared operating
        system is not known to its cluster.
    :raises NotImplementedError: When this node's OS does not want to
        define any OS-specific preseed data.
    :raises TimeoutError: If a response has not been received within 30
        seconds.
    """
    client = getClientFor(node.nodegroup.uuid)
    call = client(
        GetPreseedData, osystem=node.get_osystem(), preseed_type=preseed_type,
        node_system_id=node.system_id, node_hostname=node.hostname,
        consumer_key=token.consumer.key, token_key=token.key,
        token_secret=token.secret, metadata_url=urlparse(metadata_url))
    return call.wait(30).get("data")


@synchronous
def compose_curtin_network_preseed(node, config):
    """Generate a Curtin network preseed for a node.

    The `config` is a dict like::

        {
            'interfaces': ['aa:bb:cc:dd:ee:ff', '00:11:22:33:44:55'],
            'auto_interfaces': ['aa:bb:cc:dd:ee:ff'],
            'ips_mapping': {
                'aa:bb:cc:dd:ee:ff': ['10.9.8.7'],
                '00:11:22:33:44:55': ['192.168.32.150'],
                },
            'gateways_mapping': {
                'aa:bb:cc:dd:ee:ff': ['10.9.1.1'],
                '00:11:22:33:44:55': ['192.168.32.254'],
                },
        }

    :param node: A `Node`.
    :param config: A dict detailing the network configuration:
        `interfaces` maps to a list of pairs of interface name and MAC address.
        `auto_interfaces` maps to a list of MAC addresses for those network
        interfaces that should come up automatically on node boot.
        `ips_mapping` maps to a dict which maps MAC addresses to lists of
        IP addresses (at most one IPv4 and one IPv6 each) to be assigned to the
        corresponding network interfaces.
        `gateways_mapping` maps to a dict which maps MAC addresses to lists of
        gateway IP addresses (at most one IPv4 and one IPv6) to be used by the
        corresponding network interfaces.
    :return: A list of preseed dicts.
    """
    client = getClientFor(node.nodegroup.uuid)
    call = client(
        ComposeCurtinNetworkPreseed, osystem=node.get_osystem(), config=config,
        disable_ipv4=node.disable_ipv4)
    return call.wait(30).get("data")


@synchronous
def validate_license_key_for(nodegroup, osystem, release, key):
    """Validate license key for the given nodegroup, OS, and release.

    :param nodegroup: The nodegroup model instance.
    :param osystem: The name of the operating system.
    :param release: The release for the operating system.
    :param key: The license key to validate.

    :return: True if valid, False otherwise.

    :raises NoConnectionsAvailable: When no connections to the node's
        cluster are available for use.
    :raises NoSuchOperatingSystem: When the node's declared operating
        system is not known to its cluster.
    :raises TimeoutError: If a response has not been received within 30
        seconds.
    """
    client = getClientFor(nodegroup.uuid)
    call = client(
        ValidateLicenseKey, osystem=osystem, release=release, key=key)
    return call.wait(30).get("is_valid")


@synchronous
def validate_license_key(osystem, release, key):
    """Validate license key for the given OS and release.

    Checks all nodegroups to determine if the license key is valid. Only
    one nodegroup has to say the license key is valid.

    :param osystem: The name of the operating system.
    :param release: The release for the operating system.
    :param key: The license key to validate.

    :return: True if valid, False otherwise.
    """
    responses = async.gather(
        partial(
            client, ValidateLicenseKey,
            osystem=osystem, release=release, key=key)
        for client in getAllClients())

    # Only one cluster needs to say the license key is valid, for it
    # to considered valid. Must go through all responses so they are all
    # marked handled.
    is_valid = False
    for response in suppress_failures(responses):
        is_valid = is_valid or response["is_valid"]
    return is_valid
