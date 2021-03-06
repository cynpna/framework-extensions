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
Upstart module
"""

import re
import time
from subprocess import CalledProcessError, check_output
from ovs_extensions.generic.toolbox import ExtensionsToolbox


class Upstart(object):
    """
    Contains all logic related to Upstart services
    """
    def __init__(self, system, configuration, run_file_dir, monitor_prefixes, service_config_key, config_template_dir, logger):
        """
        Init method
        """
        self._logger = logger
        self._system = system
        self._run_file_dir = run_file_dir
        self._configuration = configuration
        self._monitor_prefixes = monitor_prefixes
        self.service_config_key = service_config_key
        self._config_template_dir = config_template_dir

    @classmethod
    def _service_exists(cls, name, client, path):
        if path is None:
            path = '/etc/init/'
        file_to_check = '{0}{1}.conf'.format(path, name)
        return client.file_exists(file_to_check)

    def _get_name(self, name, client, path=None, log=True):
        """
        Make sure that for e.g. 'ovs-workers' the given service name can be either 'ovs-workers' as just 'workers'
        """
        if self._service_exists(name, client, path):
            return name
        if client.file_exists('/etc/init.d/{0}'.format(name)):
            return name
        name = 'ovs-{0}'.format(name)
        if self._service_exists(name, client, path):
            return name
        if log is True:
            self._logger.info('Service {0} could not be found.'.format(name))
        raise ValueError('Service {0} could not be found.'.format(name))

    def add_service(self, name, client, params=None, target_name=None, startup_dependency=None, delay_registration=False, path=None):
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
        :param path: path to add the service to
        :type path: str
        :return: Parameters used by the service
        :rtype: dict
        """
        if params is None:
            params = {}
        if path is None:
            path = self._config_template_dir.format('upstart')
        else:
            path = path.format('upstart')
        service_name = self._get_name(name, client, path)

        template_file = '{0}/{1}.service'.format(path, service_name)

        if not client.file_exists(template_file):
            # Given template doesn't exist so we are probably using system init scripts
            return

        if target_name is not None:
            service_name = target_name

        params.update({'SERVICE_NAME': ExtensionsToolbox.remove_prefix(service_name, 'ovs-'),
                       'RUN_FILE_DIR': self._run_file_dir,
                       'STARTUP_DEPENDENCY': '' if startup_dependency is None else 'started {0}'.format(startup_dependency)})
        template_content = client.file_read(template_file)
        for key, value in params.iteritems():
            template_content = template_content.replace('<{0}>'.format(key), str(value))
        client.file_write('/etc/init/{0}.conf'.format(service_name), template_content)

        if delay_registration is False:
            self.register_service(service_metadata=params, node_name=self._system.get_my_machine_id(client))
        return params

    def regenerate_service(self, name, client, target_name):
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
        configuration_key = self.service_config_key.format(self._system.get_my_machine_id(client), ExtensionsToolbox.remove_prefix(target_name, 'ovs-'))
        # If the entry is stored in arakoon, it means the service file was previously made
        if not self._configuration.exists(configuration_key):
            raise RuntimeError('Service {0} was not previously added and cannot be regenerated.'.format(target_name))
        # Rewrite the service file
        service_params = self._configuration.get(configuration_key)
        startup_dependency = service_params['STARTUP_DEPENDENCY']
        if startup_dependency == '':
            startup_dependency = None
        else:
            startup_dependency = '.'.join(startup_dependency.split('.')[:-1])  # Remove .service from startup dependency
        output = self.add_service(name=name,
                                  client=client,
                                  params=service_params,
                                  target_name=target_name,
                                  startup_dependency=startup_dependency,
                                  delay_registration=True)
        if output is None:
            raise RuntimeError('Regenerating files for service {0} has failed'.format(target_name))

    def get_service_status(self, name, client):
        """
        Retrieve the status of a service
        :param name: Name of the service to retrieve the status of
        :type name: str
        :param client: Client on which to retrieve the status
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: The status of the service
        :rtype: str
        """
        try:
            name = self._get_name(name, client)
            output = client.run(['service', name, 'status'], allow_nonzero=True)
            # Special cases (especially old SysV ones)
            if 'rabbitmq' in name:
                status = re.search('\{pid,\d+?\}', output) is not None
                if status is True:
                    return 'active'
                return 'inactive'
            # Normal cases - or if the above code didn't yield an outcome
            if 'start/running' in output or 'is running' in output:
                return 'active'
            if 'stop' in output or 'not running' in output:
                return 'inactive'
            return output
        except CalledProcessError as ex:
            self._logger.exception('Get {0}.service status failed: {1}'.format(name, ex))
            raise Exception('Retrieving status for service "{0}" failed'.format(name))

    def remove_service(self, name, client, delay_unregistration=False):
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
        name = self._get_name(name, client)
        run_file_name = '{0}/{1}.version'.format(self._run_file_dir, ExtensionsToolbox.remove_prefix(name, 'ovs-'))
        if client.file_exists(run_file_name):
            client.file_delete(run_file_name)
        client.file_delete('/etc/init/{0}.conf'.format(name))

        if delay_unregistration is False:
            self.unregister_service(service_name=name, node_name=self._system.get_my_machine_id(client))

    def start_service(self, name, client, timeout=5):
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
        if self.get_service_status(name, client) == 'active':
            return

        name = self._get_name(name, client)
        timeout = timeout if timeout > 0 else 5
        try:
            client.run(['service', name, 'start'])
            counter = 0
            while counter < timeout * 4:
                if self.get_service_status(name=name, client=client) == 'active':
                    return
                time.sleep(0.25)
                counter += 1
        except CalledProcessError as cpe:
            self._logger.exception('Start {0} failed, {1}'.format(name, cpe.output))
            raise
        raise RuntimeError('Did not manage to start service {0} on node with IP {1}'.format(name, client.ip))

    def stop_service(self, name, client, timeout=5):
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
        if self.get_service_status(name, client) == 'inactive':
            return

        name = self._get_name(name, client)
        timeout = timeout if timeout > 0 else 5
        try:
            client.run(['service', name, 'stop'])
            counter = 0
            while counter < timeout * 4:
                if self.get_service_status(name=name, client=client) == 'inactive':
                    return
                time.sleep(0.25)
                counter += 1
        except CalledProcessError as cpe:
            self._logger.exception('Stop {0} failed, {1}'.format(name, cpe.output))
            raise
        raise RuntimeError('Did not manage to stop service {0} on node with IP {1}'.format(name, client.ip))

    def restart_service(self, name, client, timeout=5):
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
        self.stop_service(name, client, timeout)
        self.start_service(name, client, timeout)

    def has_service(self, name, client):
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
            self._get_name(name, client, log=False)
        except ValueError:
            return False
        return True

    def get_service_pid(self, name, client):
        """
        Retrieve the PID of a service
        :param name: Name of the service to retrieve the PID for
        :type name: str
        :param client: Client on which to retrieve the PID for the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :return: The PID of the service or 0 if no PID found
        :rtype: int
        """
        name = self._get_name(name, client)
        if self.get_service_status(name, client) == 'active':
            output = client.run(['service', name, 'status'])
            if output:
                # Special cases (especially old SysV ones)
                if 'rabbitmq' in name:
                    match = re.search('\{pid,(?P<pid>\d+?)\}', output)
                else:
                    # Normal cases - or if the above code didn't yield an outcome
                    match = re.search('start/running, process (?P<pid>\d+)', output)
                if match is not None:
                    match_groups = match.groupdict()
                    if 'pid' in match_groups:
                        return match_groups['pid']
        return -1

    def send_signal(self, name, signal, client):
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
        name = self._get_name(name, client)
        pid = self.get_service_pid(name, client)
        if pid == -1:
            raise RuntimeError('Could not determine PID to send signal to')
        client.run(['kill', '-s', signal, pid])

    @classmethod
    def list_services(cls, client, add_status_info=False):
        """
        List all created services on a system
        :param client: Client on which to list all the services
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :param add_status_info: Add status information of service in the output
        :type add_status_info: bool
        :return: List of all services which have been created at some point
        :rtype: generator
        """
        _ = add_status_info
        for filename in client.dir_list('/etc/init'):
            if filename.endswith('.conf'):
                yield filename.replace('.conf', '')

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
                for service_info in check_output('initctl list', shell=True).splitlines():
                    if not service_info.startswith('ovs-'):
                        continue
                    service_info = service_info.split(',')[0].strip()
                    service_name = service_info.split()[0].strip()
                    service_state = service_info.split()[1].strip()
                    if service_state == "start/running":
                        running_services[service_name] = service_state
                    else:
                        non_running_services[service_name] = service_state

                    if len(service_name) > longest_service_name:
                        longest_service_name = len(service_name)

                # Put service states in list
                output = ['OVS running processes',
                          '=====================\n']
                for service_name in sorted(running_services, key=lambda service: ExtensionsToolbox.advanced_sort(service, '_')):
                    output.append('{0} {1} {2}'.format(service_name, ' ' * (longest_service_name - len(service_name)), running_services[service_name]))

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

    def register_service(self, node_name, service_metadata):
        """
        Register the metadata of the service to the configuration management
        :param node_name: Name of the node on which the service is running
        :type node_name: str
        :param service_metadata: Metadata of the service
        :type service_metadata: dict
        :return: None
        """
        service_name = service_metadata['SERVICE_NAME']
        self._configuration.set(key=self.service_config_key.format(node_name, ExtensionsToolbox.remove_prefix(service_name, 'ovs-')),
                                value=service_metadata)

    def unregister_service(self, node_name, service_name):
        """
        Un-register the metadata of a service from the configuration management
        :param service_name: Name of the service to clean from the configuration management
        :type service_name: str
        :param node_name: Name of the node on which to un-register the service
        :type node_name: str
        :return: None
        """
        self._configuration.delete(key=self.service_config_key.format(node_name, ExtensionsToolbox.remove_prefix(service_name, 'ovs-')))

    def is_rabbitmq_running(self, client):
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

        if self.has_service('rabbitmq-server', client) and self.get_service_status('rabbitmq-server', client) == 'active':
            rabbitmq_running = True
            rabbitmq_pid_sm = self.get_service_pid('rabbitmq-server', client)

        same_process = rabbitmq_pid_ctl == rabbitmq_pid_sm
        self._logger.debug('Rabbitmq is reported {0}running, pids: {1} and {2}'.format('' if rabbitmq_running else 'not ',
                                                                                       rabbitmq_pid_ctl,
                                                                                       rabbitmq_pid_sm))
        return rabbitmq_running, same_process

    def extract_from_service_file(self, name, client, entries=None):
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
        if self.has_service(name=name, client=client) is False:
            return []

        try:
            name = self._get_name(name=name, client=client)
            contents = client.file_read('/etc/init/{0}.conf'.format(name)).splitlines()
        except Exception:
            self._logger.exception('Failure to retrieve contents for service {0} on node with IP {1}'.format(name, client.ip))
            return []

        if entries is None:
            return contents

        return_value = []
        for line in contents:
            for entry in entries:
                if entry in line:
                    return_value.append(line)
        return return_value

    def get_service_fd(self, name, client):
        raise NotImplementedError('Get_service_fd has not yet been implemented')

    def get_service_start_time(self, name, client):
        """
        Retrieves the start time of the service
        :param name: Name of the service to retrieve the PID for
        :type name: str
        :param client: Client on which to retrieve the PID for the service
        :type client: ovs_extensions.generic.sshclient.SSHClient
        :raises ValueError when no PID could be found for the given process
        :return: A string representing the datetime of when the service was started eg Mon Jan 1 3:30:00 2018
        :rtype: str
        """
        pid = self.get_service_pid(name, client)
        if pid in [0, -1]:
            raise ValueError('No PID could be found for service {0} on node with IP {1}'.format(name, client.ip))
        return client.run(['ps', '-o', 'lstart', '-p', pid]).strip().splitlines()[-1]
