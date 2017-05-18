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
Systemd Mock module
"""

from ovs_extensions.generic.configuration import Configuration
from ovs_extensions.generic.system import System
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs_extensions.services.interfaces.manager import Manager


class SystemdMock(Manager):
    """
    Contains all logic related to Systemd Mock services
    """
    services = {}

    @staticmethod
    def add_service(name, client, params=None, target_name=None, startup_dependency=None, delay_registration=False):
        """
        Adds a mocked service
        """
        if params is None:
            params = {}

        key = 'None' if client is None else client.ip
        name = name if target_name is None else target_name
        params.update({'SERVICE_NAME': ExtensionsToolbox.remove_prefix(name, 'ovs-'),
                       'STARTUP_DEPENDENCY': '' if startup_dependency is None else '{0}.service'.format(startup_dependency)})
        if SystemdMock.has_service(name=name, client=client) is False:
            SystemdMock.services[key] = {name: 'HALTED'}
        if delay_registration is False:
            SystemdMock.register_service(node_name=System.get_my_machine_id(client), service_metadata=params)
        return params

    @staticmethod
    def get_service_status(name, client):
        """
        Retrieve the mocked service status
        """
        name = SystemdMock._get_name(name, client)
        key = 'None' if client is None else client.ip
        if SystemdMock.services.get(key, {}).get(name) == 'RUNNING':
            return 'active'
        return 'inactive'

    @staticmethod
    def remove_service(name, client, delay_unregistration=False):
        """
        Remove a mocked service
        """
        name = SystemdMock._get_name(name, client)
        key = 'None' if client is None else client.ip
        if name in SystemdMock.services[key]:
            SystemdMock.services[key].pop(name)
        if delay_unregistration is False:
            SystemdMock.unregister_service(service_name=name, node_name=System.get_my_machine_id(client))

    @staticmethod
    def start_service(name, client):
        """
        Start a mocked service
        """
        name = SystemdMock._get_name(name, client)
        key = 'None' if client is None else client.ip
        if name not in SystemdMock.services[key]:
            raise RuntimeError('Service {0} does not exist'.format(name))
        SystemdMock.services[key][name] = 'RUNNING'
        if SystemdMock.get_service_status(name, client) != 'active':
            raise RuntimeError('Start {0} failed'.format(name))

    @staticmethod
    def stop_service(name, client):
        """
        Stop a mocked service
        """
        name = SystemdMock._get_name(name, client)
        key = 'None' if client is None else client.ip
        if name not in SystemdMock.services[key]:
            raise RuntimeError('Service {0} does not exist'.format(name))
        SystemdMock.services[key][name] = 'HALTED'
        if SystemdMock.get_service_status(name, client) != 'inactive':
            raise RuntimeError('Stop {0} failed'.format(name))

    @staticmethod
    def restart_service(name, client):
        """
        Restart a mocked service
        """
        name = SystemdMock._get_name(name, client)
        SystemdMock.stop_service(name, client)
        SystemdMock.start_service(name, client)

    @staticmethod
    def has_service(name, client):
        """
        Verify whether a mocked service exists
        """
        try:
            name = SystemdMock._get_name(name, client)
            key = 'None' if client is None else client.ip
            return name in SystemdMock.services[key]
        except ValueError:
            return False

    @staticmethod
    def register_service(node_name, service_metadata):
        """
        Register the metadata of the service to the configuration management
        :param node_name: Name of the node on which the service is running
        :type node_name: str
        :param service_metadata: Metadata of the service
        :type service_metadata: dict
        :return: None
        """
        service_name = service_metadata['SERVICE_NAME']
        Configuration.set(key=SystemdMock.SERVICE_CONFIG_KEY.format(node_name, ExtensionsToolbox.remove_prefix(service_name, 'ovs-')),
                          value=service_metadata)

    @staticmethod
    def unregister_service(node_name, service_name):
        """
        Un-register the metadata of a service from the configuration management
        :param node_name: Name of the node on which to un-register the service
        :type node_name: str
        :param service_name: Name of the service to clean from the configuration management
        :type service_name: str
        :return: None
        """
        Configuration.delete(key=SystemdMock.SERVICE_CONFIG_KEY.format(node_name, ExtensionsToolbox.remove_prefix(service_name, 'ovs-')))

    @staticmethod
    def extract_from_service_file(name, client, entries=None):
        """
        Extract an entry, multiple entries or the entire service file content for a service
        :param name: Name of the service
        :type name: str
        :param client: Client on which to extract something from the service file
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param entries: Entries to extract
        :type entries: list
        :return: The requested entry information or entire service file content if entry=None
        :rtype: list
        """
        _ = name, client, entries
        return []

    @staticmethod
    def _service_exists(name, client, path):
        """
        Verify whether a mocked service exists
        """
        _ = path
        key = 'None' if client is None else client.ip
        return name in SystemdMock.services.get(key, {})

    @staticmethod
    def _get_name(name, client, path=None, log=True):
        """
        Make sure that for e.g. 'ovs-workers' the given service name can be either 'ovs-workers' as just 'workers'
        """
        _ = log
        if SystemdMock._service_exists(name, client, path):
            return name
        if SystemdMock._service_exists(name, client, '/lib/systemd/system/'):
            return name
        name = 'ovs-{0}'.format(name)
        if SystemdMock._service_exists(name, client, path):
            return name
        raise ValueError('Service {0} could not be found.'.format(name))

    @staticmethod
    def _clean():
        """
        Clean up mocked Class
        """
        SystemdMock.services = {}
