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
Systemd module
"""
import re
import time
import logging
from subprocess import CalledProcessError, check_output
from ovs_extensions.generic.configuration import Configuration
from ovs_extensions.generic.system import System
from ovs_extensions.generic.toolbox import ExtensionsToolbox
from ovs_extensions.services.interfaces.manager import Manager

logger = logging.getLogger(__name__)


class Systemd(Manager):
    """
    Contains all logic related to Systemd services
    """
    @classmethod
    def _service_exists(cls, name, client, path):
        if path is None:
            path = '/lib/systemd/system/'
        else:
            path = '{0}/'.format(path.rstrip('/'))
        file_to_check = '{0}{1}.service'.format(path, name)
        return client.file_exists(file_to_check)

    @classmethod
    def _get_name(cls, name, client, path=None, log=True):
        """
        Make sure that for e.g. 'ovs-workers' the given service name can be either 'ovs-workers' as just 'workers'
        """
        if cls._service_exists(name, client, path):
            return name
        if cls._service_exists(name, client, '/lib/systemd/system/'):
            return name
        name = 'ovs-{0}'.format(name)
        if cls._service_exists(name, client, path):
            return name
        if log is True:
            logger.info('Service {0} could not be found.'.format(name))
        raise ValueError('Service {0} could not be found.'.format(name))

    @classmethod
    def add_service(cls, name, client, params=None, target_name=None, startup_dependency=None, delay_registration=False):
        """
        Add a service
        :param name: Template name of the service to add
        :type name: str
        :param client: Client on which to add the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param params: Additional information about the service
        :type params: dict or None
        :param target_name: Overrule default name of the service with this name
        :type target_name: str or None
        :param startup_dependency: Additional startup dependency
        :type startup_dependency: str or None
        :param delay_registration: Register the service parameters in the config management right away or not
        :type delay_registration: bool
        :return: Parameters used by the service
        :rtype: dict
        """
        if params is None:
            params = {}

        service_name = cls._get_name(name, client, cls.CONFIG_TEMPLATE_DIR.format('systemd'))
        template_file = '{0}/{1}.service'.format(cls.CONFIG_TEMPLATE_DIR.format('systemd'), service_name)

        if not client.file_exists(template_file):
            # Given template doesn't exist so we are probably using system init scripts
            return

        if target_name is not None:
            service_name = target_name

        params.update({'SERVICE_NAME': ExtensionsToolbox.remove_prefix(service_name, 'ovs-'),
                       'STARTUP_DEPENDENCY': '' if startup_dependency is None else '{0}.service'.format(startup_dependency)})
        template_content = client.file_read(template_file)
        for key, value in params.iteritems():
            template_content = template_content.replace('<{0}>'.format(key), str(value))
        client.file_write('/lib/systemd/system/{0}.service'.format(service_name), template_content)

        try:
            client.run(['systemctl', 'daemon-reload'])
            client.run(['systemctl', 'enable', '{0}.service'.format(service_name)])
        except CalledProcessError as cpe:
            logger.exception('Add {0}.service failed, {1}'.format(service_name, cpe.output))
            raise Exception('Add {0}.service failed, {1}'.format(service_name, cpe.output))

        if delay_registration is False:
            cls.register_service(service_metadata=params, node_name=System.get_my_machine_id(client))
        return params

    @classmethod
    def regenerate_service(cls, name, client, target_name):
        """
        Regenerates the service files of a service.
        :param name: Template name of the service to regenerate
        :type name: str
        :param client: Client on which to regenerate the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param target_name: The current service name eg ovs-volumedriver_flash01.service
        :type target_name: str
        :return: None
        :rtype: NoneType
        """
        configuration_key = cls.SERVICE_CONFIG_KEY.format(System.get_my_machine_id(client), ExtensionsToolbox.remove_prefix(target_name, 'ovs-'))
        # If the entry is stored in arakoon, it means the service file was previously made
        if not Configuration.exists(configuration_key):
            raise RuntimeError('Service {0} was not previously added and cannot be regenerated.'.format(target_name))
        # Rewrite the service file
        service_params = Configuration.get(configuration_key)
        startup_dependency = service_params['STARTUP_DEPENDENCY']
        if startup_dependency == '':
            startup_dependency = None
        else:
            startup_dependency = '.'.join(startup_dependency.split('.')[:-1])  # Remove .service from startup dependency
        output = cls.add_service(name=name,
                                 client=client,
                                 params=service_params,
                                 target_name=target_name,
                                 startup_dependency=startup_dependency,
                                 delay_registration=True)
        if output is None:
            raise RuntimeError('Regenerating files for service {0} has failed'.format(target_name))

    @classmethod
    def get_service_status(cls, name, client):
        """
        Retrieve the status of a service
        :param name: Name of the service to retrieve the status of
        :type name: str
        :param client: Client on which to retrieve the status
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: The status of the service
        :rtype: str
        """
        name = cls._get_name(name, client)
        return client.run(['systemctl', 'is-active', name], allow_nonzero=True)

    @classmethod
    def remove_service(cls, name, client, delay_unregistration=False):
        """
        Remove a service
        :param name: Name of the service to remove
        :type name: str
        :param client: Client on which to remove the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param delay_unregistration: Un-register the service parameters in the config management right away or not
        :type delay_unregistration: bool
        :return: None
        :rtype: NoneType
        """
        name = cls._get_name(name, client)
        run_file_name = '{0}/{1}.version'.format(cls.RUN_FILE_DIR, ExtensionsToolbox.remove_prefix(name, 'ovs-'))
        if client.file_exists(run_file_name):
            client.file_delete(run_file_name)
        try:
            client.run(['systemctl', 'disable', '{0}.service'.format(name)])
        except CalledProcessError:
            pass  # Service already disabled
        client.file_delete('/lib/systemd/system/{0}.service'.format(name))
        client.run(['systemctl', 'daemon-reload'])

        if delay_unregistration is False:
            cls.unregister_service(service_name=name, node_name=System.get_my_machine_id(client))

    @classmethod
    def start_service(cls, name, client, timeout=5):
        """
        Start a service
        :param name: Name of the service to start
        :type name: str
        :param client: Client on which to start the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param timeout: Timeout within to verify the service status (in seconds)
        :type timeout: int
        :return: None
        :rtype: NoneType
        """
        if cls.get_service_status(name, client) == 'active':
            return

        try:
            # When service files have been adjusted, a reload is required for these changes to take effect
            client.run(['systemctl', 'daemon-reload'])
        except CalledProcessError:
            pass

        name = cls._get_name(name, client)
        timeout = timeout if timeout > 0 else 5
        try:
            client.run(['systemctl', 'start', '{0}.service'.format(name)])
            counter = 0
            while counter < timeout * 4:
                if cls.get_service_status(name=name, client=client) == 'active':
                    return
                time.sleep(0.25)
                counter += 1
        except CalledProcessError as cpe:
            logger.exception('Start {0} failed, {1}'.format(name, cpe.output))
            raise
        raise RuntimeError('Did not manage to start service {0} on node with IP {1}'.format(name, client.ip))

    @classmethod
    def stop_service(cls, name, client, timeout=5):
        """
        Stop a service
        :param name: Name of the service to stop
        :type name: str
        :param client: Client on which to stop the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param timeout: Timeout within to verify the service status (in seconds)
        :type timeout: int
        :return: None
        :rtype: NoneType
        """
        if cls.get_service_status(name, client) == 'inactive':
            return

        name = cls._get_name(name, client)
        timeout = timeout if timeout > 0 else 5
        try:
            client.run(['systemctl', 'stop', '{0}.service'.format(name)])
            counter = 0
            while counter < timeout * 4:
                if cls.get_service_status(name=name, client=client) == 'inactive':
                    return
                time.sleep(0.25)
                counter += 1
        except CalledProcessError as cpe:
            logger.exception('Stop {0} failed, {1}'.format(name, cpe.output))
            raise
        raise RuntimeError('Did not manage to stop service {0} on node with IP {1}'.format(name, client.ip))

    @classmethod
    def restart_service(cls, name, client, timeout=5):
        """
        Restart a service
        :param name: Name of the service to restart
        :type name: str
        :param client: Client on which to restart the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param timeout: Timeout within to verify the service status (in seconds)
        :type timeout: int
        :return: None
        :rtype: NoneType
        """
        try:
            # When service files have been adjusted, a reload is required for these changes to take effect
            client.run(['systemctl', 'daemon-reload'])
        except CalledProcessError:
            pass

        name = cls._get_name(name, client)
        timeout = timeout if timeout > 0 else 5
        try:
            client.run(['systemctl', 'restart', '{0}.service'.format(name)])
            counter = 0
            while counter < timeout * 4:
                if cls.get_service_status(name=name, client=client) == 'active':
                    return
                time.sleep(0.25)
                counter += 1
        except CalledProcessError as cpe:
            logger.exception('Restart {0} failed, {1}'.format(name, cpe.output))
            raise
        raise RuntimeError('Did not manage to restart service {0} on node with IP {1}'.format(name, client.ip))

    @classmethod
    def has_service(cls, name, client):
        """
        Verify existence of a service
        :param name: Name of the service to verify
        :type name: str
        :param client: Client on which to check for the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: Whether the service exists
        :rtype: bool
        """
        try:
            cls._get_name(name, client, log=False)
        except ValueError:
            return False
        return True

    @classmethod
    def get_service_pid(cls, name, client):
        """
        Retrieve the PID of a service
        :param name: Name of the service to retrieve the PID for
        :type name: str
        :param client: Client on which to retrieve the PID for the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: The PID of the service or 0 if no PID found
        :rtype: int
        """
        pid = 0
        name = cls._get_name(name, client)
        if cls.get_service_status(name, client) == 'active':
            output = client.run(['systemctl', 'show', name, '--property=MainPID']).split('=')
            if len(output) == 2:
                pid = output[1]
                if not pid.isdigit():
                    pid = 0
        return int(pid)

    @classmethod
    def send_signal(cls, name, signal, client):
        """
        Send a signal to a service
        :param name: Name of the service to send a signal
        :type name: str
        :param signal: Signal to pass on to the service
        :type signal: int
        :param client: Client on which to send a signal to the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: None
        :rtype: NoneType
        """
        name = cls._get_name(name, client)
        pid = cls.get_service_pid(name, client)
        if pid == 0:
            raise RuntimeError('Could not determine PID to send signal to')
        client.run(['kill', '-s', signal, pid])

    @classmethod
    def list_services(cls, client):
        """
        List all created services on a system
        :param client: Client on which to list all the services
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: List of all services which have been created at some point
        :rtype: generator
        """
        for service_info in client.run(['systemctl', 'list-unit-files', '--type=service', '--no-legend', '--no-pager']).splitlines():
            yield '.'.join(service_info.split(' ')[0].split('.')[:-1])

    @classmethod
    def monitor_services(cls):
        """
        Monitor the local OVS services
        :return: None
        :rtype: NoneType
        """
        try:
            previous_output = None
            while True:
                # Gather service states
                running_services = {}
                non_running_services = {}
                longest_service_name = 0
                for service_name in check_output('systemctl list-unit-files --type=service --no-legend --no-pager | grep "ovs-" | tr -s " " | cut -d " " -f 1', shell=True).splitlines():
                    try:
                        service_state = check_output('systemctl is-active {0}'.format(service_name), shell=True).strip()
                    except CalledProcessError as cpe:
                        service_state = cpe.output.strip()

                    service_name = service_name.replace('.service', '')
                    if service_state == 'active':
                        service_pid = check_output('systemctl show {0} --property=MainPID'.format(service_name), shell=True).strip().split('=')[1]
                        running_services[service_name] = (service_state, service_pid)
                    else:
                        non_running_services[service_name] = service_state

                    if len(service_name) > longest_service_name:
                        longest_service_name = len(service_name)

                # Put service states in list
                output = ['OVS running processes',
                          '=====================\n']
                for service_name in sorted(running_services, key=lambda service: ExtensionsToolbox.advanced_sort(service, '_')):
                    output.append('{0} {1} {2}  {3}'.format(service_name, ' ' * (longest_service_name - len(service_name)), running_services[service_name][0], running_services[service_name][1]))

                output.extend(['\n\nOVS non-running processes',
                               '=========================\n'])
                for service_name in sorted(non_running_services, key=lambda service: ExtensionsToolbox.advanced_sort(service, '_')):
                    output.append('{0} {1} {2}'.format(service_name, ' ' * (longest_service_name - len(service_name)), non_running_services[service_name]))

                # Print service states (only if changes)
                if previous_output != output:
                    print '\x1b[2J\x1b[H'
                    for line in output:
                        print line
                    previous_output = list(output)
                time.sleep(1)
        except KeyboardInterrupt:
            pass

    @classmethod
    def register_service(cls, node_name, service_metadata):
        """
        Register the metadata of the service to the configuration management
        :param node_name: Name of the node on which the service is running
        :type node_name: str
        :param service_metadata: Metadata of the service
        :type service_metadata: dict
        :return: None
        :rtype: NoneType
        """
        service_name = service_metadata['SERVICE_NAME']
        Configuration.set(key=cls.SERVICE_CONFIG_KEY.format(node_name, ExtensionsToolbox.remove_prefix(service_name, 'ovs-')),
                          value=service_metadata)

    @classmethod
    def unregister_service(cls, node_name, service_name):
        """
        Un-register the metadata of a service from the configuration management
        :param node_name: Name of the node on which to un-register the service
        :type node_name: str
        :param service_name: Name of the service to clean from the configuration management
        :type service_name: str
        :return: None
        :rtype: NoneType
        """
        Configuration.delete(key=cls.SERVICE_CONFIG_KEY.format(node_name, ExtensionsToolbox.remove_prefix(service_name, 'ovs-')))

    @classmethod
    def is_rabbitmq_running(cls, client):
        """
        Check if rabbitmq is correctly running
        :param client: Client on which to check the rabbitmq process
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: The PID of the process and a bool indicating everything runs as expected
        :rtype: tuple
        """
        rabbitmq_running = False
        rabbitmq_pid_ctl = -1
        rabbitmq_pid_sm = -1
        output = client.run(['rabbitmqctl', 'status'], allow_nonzero=True)
        if output:
            match = re.search('\{pid,(?P<pid>\d+?)\}', output)
            if match is not None:
                match_groups = match.groupdict()
                if 'pid' in match_groups:
                    rabbitmq_running = True
                    rabbitmq_pid_ctl = match_groups['pid']

        if cls.has_service('rabbitmq-server', client) and cls.get_service_status('rabbitmq-server', client) == 'active':
            rabbitmq_running = True
            rabbitmq_pid_sm = cls.get_service_pid('rabbitmq-server', client)

        same_process = rabbitmq_pid_ctl == rabbitmq_pid_sm
        logger.debug('Rabbitmq is reported {0}running, pids: {1} and {2}'.format('' if rabbitmq_running else 'not ',
                                                                                          rabbitmq_pid_ctl,
                                                                                          rabbitmq_pid_sm))
        return rabbitmq_running, same_process

    @classmethod
    def extract_from_service_file(cls, name, client, entries=None):
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
        if cls.has_service(name=name, client=client) is False:
            return []

        try:
            name = cls._get_name(name=name, client=client)
            contents = client.file_read('/lib/systemd/system/{0}.service'.format(name)).splitlines()
        except Exception:
            logger.exception('Failure to retrieve contents for service {0} on node with IP {1}'.format(name, client.ip))
            return []

        if entries is None:
            return contents

        return_value = []
        for line in contents:
            for entry in entries:
                if entry in line:
                    return_value.append(line)
        return return_value
