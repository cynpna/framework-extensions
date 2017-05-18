# Copyright (C) 2016 iNuron NV
#
# This file is part of Open vStorage Open Source Edition (OSE),
# as available from
#
#      http://www.openvstorage.org and
#      http://www.openvstorage.com.
#
# This file is free software; you can redistribute it and/or modify it
# under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
# as published by the Free Software Foundation, in version 3 as it comes
# in the LICENSE.txt file of the Open vStorage OSE distribution.
#
# Open vStorage is distributed in the hope that it will be useful,
# but WITHOUT ANY WARRANTY of any kind.

"""
OVS migration module
"""
import os


class OVSMigrator(object):
    """
    Handles all model related migrations
    """

    identifier = 'ovs'  # Used by migrator.py, so don't remove
    THIS_VERSION = 12

    def __init__(self):
        """ Init method """
        pass

    @staticmethod
    def migrate(previous_version, master_ips=None, extra_ips=None):
        """
        Migrates from a given version to the current version. It uses 'previous_version' to be smart
        wherever possible, but the code should be able to migrate any version towards the expected version.
        When this is not possible, the code can set a minimum version and raise when it is not met.
        :param previous_version: The previous version from which to start the migration
        :type previous_version: float
        :param master_ips: IP addresses of the MASTER nodes
        :type master_ips: list or None
        :param extra_ips: IP addresses of the EXTRA nodes
        :type extra_ips: list or None
        """

        _ = master_ips, extra_ips
        working_version = previous_version

        # From here on, all actual migration should happen to get to the expected state for THIS RELEASE
        if working_version < OVSMigrator.THIS_VERSION:
            from ovs.extensions.generic.configuration import Configuration
            from ovs.extensions.generic.sshclient import SSHClient
            from ovs.extensions.generic.system import System
            local_machine_id = System.get_my_machine_id()
            local_ip = Configuration.get('/ovs/framework/hosts/{0}/ip'.format(local_machine_id))
            local_client = SSHClient(endpoint=local_ip, username='root')

            # Multiple Proxies
            if local_client.dir_exists(directory='/opt/OpenvStorage/config/storagedriver/storagedriver'):
                local_client.dir_delete(directories=['/opt/OpenvStorage/config/storagedriver/storagedriver'])

        return OVSMigrator.THIS_VERSION
