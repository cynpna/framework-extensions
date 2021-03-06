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
SSHClient module
Used for remote or local command execution
"""

import os
import re
import grp
import pwd
import glob
import json
import select
import socket
import getpass
import logging
import paramiko
import tempfile
import warnings
import unicodedata
import subprocess
from paramiko import AuthenticationException
from threading import RLock
from functools import wraps
from subprocess import CalledProcessError, PIPE, Popen, check_output
from ovs_extensions.constants import is_unittest_mode
from ovs_extensions.generic.remote import remote
from ovs_extensions.generic.tests.sshclient_mock import MockedSSHClient


if not hasattr(select, 'poll'):
    subprocess._has_poll = False  # Damn 'monkey patching'
# Disable paramiko warning
warnings.filterwarnings(action='ignore',
                        message='.*CTR mode needs counter parameter.*',
                        category=FutureWarning)


def connected():
    """
    Makes sure a call is executed against a connected client if required
    """

    def wrapper(f):
        """
        Wrapper function
        :param f: Function to wrap
        """
        @wraps(f)
        def inner_function(self, *args, **kwargs):
            """
            Wrapped function
            :param self
            """
            try:
                if self._client and not self.is_connected():
                    self._connect()
                return f(self, *args, **kwargs)
            except AttributeError as ex:
                if "'NoneType' object has no attribute 'open_session'" in str(ex):
                    self._connect()  # Reconnect
                    return f(self, *args, **kwargs)
                raise
        return inner_function

    return wrapper


def mocked(mock_function):
    """
    Mock decorator
    """
    def wrapper(f):
        """
        Wrapper function
        """
        @wraps(f)
        def inner_function(client, *args, **kwargs):
            # type: (SSHClient, *any, **any) -> any
            """
            Wrapper to be able to add the original function to the wrapped function
            """
            if client._mocked:
                client.original_function = f
                return mock_function(client, *args, **kwargs)
            return f(client, *args, **kwargs)
        return inner_function
    return wrapper


class UnableToConnectException(Exception):
    """
    Custom exception thrown when client cannot connect to remote side
    """
    pass


class NotAuthenticatedException(Exception):
    """
    Custom exception thrown when client cannot connect to remote side because SSH keys have not been exchanged
    """
    pass


class CalledProcessTimeout(CalledProcessError):
    """
    Custom exception thrown when a command is aborted due to timeout
    """
    pass


class TimeOutException(Exception):
    """
    Custom exception thrown when a connection could not be established within the timeout frame
    """
    pass


class SSHClient(object):
    """
    Remote/local client
    """
    IP_REGEX = re.compile('^(((25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?)\.){3}(25[0-5]|2[0-4][0-9]|[01]?[0-9][0-9]?))$')
    REFERENCE_ATTR = 'ovs_ref_counter'

    _logger = logging.getLogger(__name__)

    _raise_exceptions = {}  # Used by unit tests
    _mocked = is_unittest_mode()  # Only evaluated ONCE. Use enable/disable mocking functions
    client_cache = {}

    def __init__(self, endpoint, username='ovs', password=None, cached=True, timeout=None):
        # type: (str, str, str, bool, float) -> None
        """
        Initializes an SSHClient
        Please note that the underlying (cached) Paramiko instance is not thread safe!
        When using the client in a multithreaded use-case. Use the cached=False to avoid any racing between threads
        Possible issues that can happen when you don't:
        - The underlying Paramiko session will never get activated anymore (a deactivation of another thread leads to the deadlock)
        - The underlying Paramiko connection would be closed by garbage collection (a patch has been implemented to avoid, but still worth mentioning)
        The downside to using a non-cached instance is that the connection needs to happen again: this can take between 0.1sec up to 1sec
        :param endpoint: Ip address to connect to / storagerouter
        :type endpoint: basestring | ovs.dal.hybrids.storagerouter.StorageRouter
        :param username: Name of the user to connect as
        :type username: str
        :param password: Password to authenticate the user as. Can be None when ssh keys are in place.
        :type password: str
        :param cached: Cache this SSHClient instance
        :type cached: bool
        :param timeout: An optional timeout (in seconds) for the TCP connect
        :type timeout: float
        """
        if isinstance(endpoint, basestring):
            ip = endpoint
            if not re.findall(SSHClient.IP_REGEX, ip):
                raise ValueError('Incorrect IP {0} specified'.format(ip))
        else:
            raise ValueError('The endpoint parameter should be an IP address')

        self.ip = ip
        self._client = None
        self.local_ips = self.get_local_ip_addresses()
        self.is_local = self.ip in self.local_ips
        self.password = password
        self.timeout = timeout
        self._unittest_mode = is_unittest_mode()
        self._client_lock = RLock()

        current_user = self.get_current_user()
        if username is None:
            self.username = current_user
        else:
            self.username = username
            if username != current_user:
                self.is_local = False  # If specified user differs from current executing user, we always use the paramiko SSHClient

        if is_unittest_mode():
            self.is_local = True
            if self.ip in self._raise_exceptions:
                raise_info = self._raise_exceptions[self.ip]
                if self.username in raise_info['users']:
                    raise raise_info['exception']

        if not self.is_local:
            key = None
            create_new = True
            if cached:
                key = '{0}@{1}'.format(self.ip, self.username)
                if key in SSHClient.client_cache:
                    create_new = False
                    self._client = SSHClient.client_cache[key]

            if create_new:
                client = paramiko.SSHClient()
                client.set_missing_host_key_policy(paramiko.AutoAddPolicy())
                if cached:
                    SSHClient.client_cache[key] = client
                self._client = client

        if self._client:
            # Increment the ref counter to avoid closing the connection
            if not hasattr(self._client, self.REFERENCE_ATTR):
                setattr(self._client, self.REFERENCE_ATTR, 0)
            self._client.ovs_ref_counter += 1  # GIL will be locking this

        self._connect()

    @classmethod
    def enable_mock(cls):
        # type: () -> None
        """
        Enable the sshclient to only use mocked calls
        """
        cls._mocked = True

    @classmethod
    def disable_mock(cls):
        # type: () -> None
        """
        Disable the sshclient mocking
        """
        cls._mocked = False

    @staticmethod
    def get_local_ip_addresses():
        # type: () -> List[str]
        """
        Retrieve the local ip addresses
        :return: List with all ip adresses
        :rtype: List[str]
        """
        command = "ip a | grep 'inet ' | sed 's/\s\s*/ /g' | cut -d ' ' -f 3 | cut -d '/' -f 1"
        return [lip.strip() for lip in check_output(command, shell=True).strip().splitlines()]

    @staticmethod
    def get_current_user():
        # type: () -> str
        """
        Retrieve the current user
        :return: The name of the current user
        :rtype: str
        """
        # Reads the user-related environment variables
        return getpass.getuser()

    def __del__(self):
        """
        Class destructor
        """
        try:
            if not self.is_local:
                self._disconnect()
        except Exception:
            pass  # Absorb destructor exceptions

    def is_connected(self):
        """
        Check whether the client is still connected
        :return: True when the connection is still active else False
        :rtype: bool
        """
        if self._client is None:
            return False
        try:
            transport = self._client.get_transport()
            if transport is None:
                return False
            transport.send_ignore()
            return True
        except EOFError:
            # Connection is closed
            return False

    def _connect(self):
        """
        Connects to the remote end
        :raises: TimeOutException: When the initially set timeout has been reached
        :raises: UnableToConnectException: When unable to connect because of 'No route to host' or 'Unable to connect'
        :raises: socket.error: When unable to connect but for different reasons than UnableToConnectException
        :raises: NotAuthenticatedException: When authentication has failed
        """
        if self.is_local:
            return

        try:
            try:
                self._client.connect(self.ip, username=self.username, password=self.password, timeout=self.timeout)
            except:
                try:
                    self._client.close()
                except:
                    pass
                raise
        except socket.timeout as ex:
            message = str(ex)
            self._logger.error(message)
            raise TimeOutException(message)
        except socket.error as ex:
            message = str(ex)
            self._logger.error(message)
            if 'No route to host' in message or 'Unable to connect' in message:
                raise UnableToConnectException(message)
            raise
        except AuthenticationException:
            raise NotAuthenticatedException('Authentication failed')

    def _disconnect(self):
        """
        Disconnects from the remote end
        :return: None
        :rtype: NoneType
        """
        if self.is_local:
            return
        with self._client_lock:
            # Check if it is safe to disconnect
            self._client.ovs_ref_counter -= 1
            if self._client.ovs_ref_counter == 0:  # When this is not 0 that means that other SSHClients are using this reference
                self._client.close()

    @classmethod
    def _clean(cls):
        """
        Clean everything up related to the unittests
        """
        cls._raise_exceptions = {}

    @staticmethod
    def shell_safe(argument):
        """
        Makes sure that the given path/string is escaped and safe for shell
        :param argument: Argument to make safe for shell
        """
        return "'{0}'".format(argument.replace(r"'", r"'\''"))

    @staticmethod
    def _clean_text(text):
        if type(text) is list:
            text = '\n'.join(line.rstrip() for line in text)
        try:
            # This strip is absolutely necessary. Without it, channel.communicate() is never executed (odd but true)
            cleaned = text.strip()
            # I ? unicode
            if not isinstance(text, unicode):
                cleaned = unicode(cleaned.decode('utf-8', 'replace'))
            for old, new in {u'\u2018': "'",
                             u'\u2019': "'",
                             u'\u201a': "'",
                             u'\u201e': '"',
                             u'\u201c': '"',
                             u'\u25cf': '*'}.iteritems():
                cleaned = cleaned.replace(old, new)
            cleaned = unicodedata.normalize('NFKD', cleaned)
            cleaned = cleaned.encode('ascii', 'ignore')
            return cleaned
        except UnicodeDecodeError:
            SSHClient._logger.error('UnicodeDecodeError with output: {0}'.format(text))
            raise

    @connected()
    @mocked(MockedSSHClient.run)
    def run(self, command, debug=False, suppress_logging=False, allow_nonzero=False, allow_insecure=False, return_stderr=False, return_exit_code=False, timeout=None):
        """
        Executes a shell command
        :param suppress_logging: Do not log anything
        :type suppress_logging: bool
        :param command: Command to execute
        :type command: list or str
        :param debug: Extended logging
        :type debug: bool
        :param allow_nonzero: Allow non-zero exit code
        :type allow_nonzero: bool
        :param allow_insecure: Allow string commands (which might be improperly escaped)
        :type allow_insecure: bool
        :param return_stderr: Return stderr
        :type return_stderr: bool
        :param return_exit_code: Return exit code of the command
        :type return_exit_code: bool
        :param timeout: Timeout after which the command should be aborted (in seconds)
        :type timeout: int
        :return: The command's stdout or tuple for stdout and stderr
        :rtype: str or tuple(str, str)
        """
        if not isinstance(command, list) and not allow_insecure:
            raise RuntimeError('The given command must be a list, or the allow_insecure flag must be set')
        if isinstance(command, list):
            command = ' '.join([self.shell_safe(str(entry)) for entry in command])
        original_command = command
        if self.is_local:
            stderr = None
            try:
                try:
                    if timeout is not None:
                        command = "'timeout' '{0}' {1}".format(timeout, command)
                    channel = Popen(command, stdout=PIPE, stderr=PIPE, shell=True)
                except OSError as ose:
                    raise CalledProcessError(1, original_command, str(ose))
                stdout, stderr = channel.communicate()
                stdout = self._clean_text(stdout)
                stderr = self._clean_text(stderr)
                exit_code = channel.returncode
                if exit_code == 124:
                    raise CalledProcessTimeout(exit_code, original_command, 'Timeout during command')
                if exit_code != 0 and not allow_nonzero:  # Raise same error as check_output
                    raise CalledProcessError(exit_code, original_command, stdout)
                if debug:
                    self._logger.debug('stdout: {0}'.format(stdout))
                    self._logger.debug('stderr: {0}'.format(stderr))
                return_value = [stdout]
                # Order matters for backwards compatibility
                if return_stderr:
                    return_value.append(stderr)
                if return_exit_code:
                    return_value.append(exit_code)
                # Backwards compatibility
                if len(return_value) == 1:
                    return return_value[0]
                return tuple(return_value)
            except CalledProcessError as cpe:
                if not suppress_logging:
                    self._logger.error('Command "{0}" failed with output "{1}"{2}'.format(
                        original_command, cpe.output, '' if stderr is None else ' and error "{0}"'.format(stderr)
                    ))
                raise
        else:
            _, stdout, stderr = self._client.exec_command(command, timeout=timeout)  # stdin, stdout, stderr
            try:
                output = self._clean_text(stdout.readlines())
                error = self._clean_text(stderr.readlines())
                exit_code = stdout.channel.recv_exit_status()
            except socket.timeout:
                raise CalledProcessTimeout(124, original_command, 'Timeout during command')
            if exit_code != 0 and not allow_nonzero:  # Raise same error as check_output
                if not suppress_logging:
                    self._logger.error('Command "{0}" failed with output "{1}" and error "{2}"'.format(command, output, error))
                raise CalledProcessError(exit_code, command, output)
            return_value = [output]
            # Order matters for backwards compatibility
            if return_stderr:
                return_value.append(error)
            if return_exit_code:
                return_value.append(exit_code)
            # Backwards compatibility
            if len(return_value) == 1:
                return return_value[0]
            return tuple(return_value)

    @mocked(MockedSSHClient.dir_create)
    def dir_create(self, directories):
        """
        Ensures a directory exists on the remote end
        :param directories: Directories to create
        """
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            if self.is_local:
                if not os.path.exists(directory):
                    os.makedirs(directory)
            else:
                self.run(['mkdir', '-p', directory])

    @mocked(MockedSSHClient.dir_delete)
    def dir_delete(self, directories, follow_symlinks=False):
        # type: (Union[str, List[str]], bool) -> None
        """
        Remove a directory (or multiple directories) from the remote filesystem recursively
        :param directories: Single directory or list of directories to delete
        :type directories: Union[str, List[str]]
        :param follow_symlinks: Boolean to indicate if symlinks should be followed and thus be deleted too
        :type follow_symlinks: bool
        """
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            real_path = self.file_read_link(directory)
            if real_path and follow_symlinks:
                self.file_unlink(directory.rstrip('/'))
                self.dir_delete(real_path)
            else:
                if self.is_local:
                    if os.path.exists(directory):
                        for dirpath, dirnames, filenames in os.walk(directory, topdown=False, followlinks=follow_symlinks):
                            for filename in filenames:
                                os.remove('/'.join([dirpath, filename]))
                            for sub_directory in dirnames:
                                os.rmdir('/'.join([dirpath, sub_directory]))
                        os.rmdir(directory)
                else:
                    if self.dir_exists(directory):
                        self.run(['rm', '-rf', directory])

    @mocked(MockedSSHClient.dir_exists)
    def dir_exists(self, directory):
        # type: (str) -> bool
        """
        Checks if a directory exists on a remote host
        :param directory: Directory to check for existence
        :type directory: str
        :rtype: bool
        """
        if self.is_local:
            return os.path.isdir(directory)
        else:
            command = """import os, json
print json.dumps(os.path.isdir('{0}'))""".format(directory)
            return json.loads(self.run(['python', '-c', """{0}""".format(command)]))

    @mocked(MockedSSHClient.dir_chmod)
    def dir_chmod(self, directories, mode, recursive=False):
        # type: (Union[str, List[str]], any, bool) -> None
        """
        Chmod a or multiple directories
        :param directories: Directories to chmod
        :param mode: Mode to chmod
        :param recursive: Chmod the directories recursively or not
        :return: None
        """
        if not isinstance(mode, int):
            raise ValueError('Mode should be an integer')

        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            if self.is_local:
                os.chmod(directory, mode)
                if recursive:
                    for root, dirs, _ in os.walk(directory):
                        for sub_dir in dirs:
                            os.chmod('/'.join([root, sub_dir]), mode)
            else:
                command = ['chmod', oct(mode), directory]
                if recursive:
                    command.insert(1, '-R')
                self.run(command)

    @mocked(MockedSSHClient.dir_chown)
    def dir_chown(self, directories, user, group, recursive=False):
        # type: (Union[str, List[str]], str, str, bool) -> None
        """
        Chown a or multiple directories
        :param directories: Directories to chown
        :param user: User to assign to directories
        :param group: Group to assign to directories
        :param recursive: Chown the directories recursively or not
        :return: None
        """

        all_users = [user_info[0] for user_info in pwd.getpwall()]
        all_groups = [group_info[0] for group_info in grp.getgrall()]

        if user not in all_users:
            raise ValueError('User "{0}" is unknown on the system'.format(user))
        if group not in all_groups:
            raise ValueError('Group "{0}" is unknown on the system'.format(group))

        uid = pwd.getpwnam(user)[2]
        gid = grp.getgrnam(group)[2]
        if isinstance(directories, basestring):
            directories = [directories]
        for directory in directories:
            if self.is_local:
                os.chown(directory, uid, gid)
                if recursive:
                    for root, dirs, _ in os.walk(directory):
                        for sub_dir in dirs:
                            os.chown('/'.join([root, sub_dir]), uid, gid)
            else:
                command = ['chown', '{0}:{1}'.format(user, group), directory]
                if recursive:
                    command.insert(1, '-R')
                self.run(command)

    @mocked(MockedSSHClient.dir_list)
    def dir_list(self, directory):
        """
        List contents of a directory on a remote host
        :param directory: Directory to list
        """
        if self.is_local:
            return os.listdir(directory)
        else:
            command = """import os, json
print json.dumps(os.listdir('{0}'))""".format(directory)
            return json.loads(self.run(['python', '-c', """{0}""".format(command)]))

    @mocked(MockedSSHClient.symlink)
    def symlink(self, links):
        """
        Create symlink
        :param links: Dictionary containing the absolute path of the files and their link which needs to be created
        :return: None
        """
        if self.is_local:
            for link_name, source in links.iteritems():
                os.symlink(source, link_name)
        else:
            for link_name, source in links.iteritems():
                self.run(['ln', '-s', source, link_name])

    @mocked(MockedSSHClient.file_create)
    def file_create(self, filenames):
        """
        Create a or multiple files
        :param filenames: Files to create
        :return: None
        """
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            if not filename.startswith('/'):
                raise ValueError('Absolute path required for filename {0}'.format(filename))

            if self.is_local:
                if not self.dir_exists(directory=os.path.dirname(filename)):
                    self.dir_create(os.path.dirname(filename))
                if not os.path.exists(filename):
                    open(filename, 'a').close()
            else:
                directory = os.path.dirname(filename)
                self.dir_create(directory)
                self.run(['touch', filename])

    @mocked(MockedSSHClient.file_delete)
    def file_delete(self, filenames):
        """
        Remove a file (or multiple files) from the remote filesystem
        :param filenames: File names to delete
        """
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            if self.is_local:
                if '*' in filename:
                    for fn in glob.glob(filename):
                        os.remove(fn)
                else:
                    if os.path.isfile(filename):
                        os.remove(filename)
            else:
                if '*' in filename:
                    command = """import glob, json
print json.dumps(glob.glob('{0}'))""".format(filename)
                    for fn in json.loads(self.run(['python', '-c', """{0}""".format(command)])):
                        self.run(['rm', '-f', fn])
                else:
                    if self.file_exists(filename):
                        self.run(['rm', '-f', filename])

    @mocked(MockedSSHClient.file_unlink)
    def file_unlink(self, path):
        """
        Unlink a file
        :param path: Path of the file to unlink
        :return: None
        """
        if self.is_local:
            if os.path.islink(path):
                os.unlink(path)
        else:
            self.run(['unlink', path])

    @mocked(MockedSSHClient.file_read_link)
    def file_read_link(self, path):
        """
        Read the symlink of the specified path
        :param path: Path of the symlink
        :return: None
        """
        path = path.rstrip('/')
        if self.is_local:
            if os.path.islink(path):
                return os.path.realpath(path)
        else:
            command = """import os, json
if os.path.islink('{0}'):
    print json.dumps(os.path.realpath('{0}'))""".format(path)
            try:
                return json.loads(self.run(['python', '-c', """{0}""".format(command)]))
            except ValueError:
                pass

    @mocked(MockedSSHClient.file_read)
    def file_read(self, filename):
        """
        Load a file from the remote end
        :param filename: File to read
        """
        if self.is_local:
            with open(filename, 'r') as the_file:
                return the_file.read()
        else:
            return self.run(['cat', filename])

    @connected()
    @mocked(MockedSSHClient.file_write)
    def file_write(self, filename, contents):
        """
        Writes into a file to the remote end
        :param filename: File to write
        :param contents: Contents to write to the file
        """
        temp_filename = '{0}~'.format(filename)
        if self.is_local:
            if os.path.isfile(filename):
                # Use .run([cp -pf ...]) here, to make sure owner and other rights are preserved
                self.run(['cp', '-pf', filename, temp_filename])
            with open(temp_filename, 'w') as the_file:
                the_file.write(contents)
                the_file.flush()
                os.fsync(the_file)
            os.rename(temp_filename, filename)
        else:
            handle, local_temp_filename = tempfile.mkstemp()
            with open(local_temp_filename, 'w') as the_file:
                the_file.write(contents)
                the_file.flush()
                os.fsync(the_file)
            os.close(handle)
            try:
                if self.file_exists(filename):
                    self.run(['cp', '-pf', filename, temp_filename])
                sftp = self._client.open_sftp()
                sftp.put(local_temp_filename, temp_filename)
                sftp.close()
                self.run(['mv', '-f', temp_filename, filename])
            finally:
                os.remove(local_temp_filename)

    @connected()
    @mocked(MockedSSHClient.file_upload)
    def file_upload(self, remote_filename, local_filename):
        """
        Uploads a file to a remote end
        :param remote_filename: Name of the file on the remote location
        :param local_filename: Name of the file locally
        """
        temp_remote_filename = '{0}~'.format(remote_filename)
        if self.is_local:
            self.run(['cp', '-f', local_filename, temp_remote_filename])
            self.run(['mv', '-f', temp_remote_filename, remote_filename])
        else:
            sftp = self._client.open_sftp()
            sftp.put(local_filename, temp_remote_filename)
            sftp.close()
            self.run(['mv', '-f', temp_remote_filename, remote_filename])

    @mocked(MockedSSHClient.file_exists)
    def file_exists(self, filename):
        """
        Checks if a file exists on a remote host
        :param filename: File to check for existence
        """
        if self.is_local:
            return os.path.isfile(filename)
        else:
            command = """import os, json
print json.dumps(os.path.isfile('{0}'))""".format(filename)
            return json.loads(self.run(['python', '-c', """{0}""".format(command)]))

    @mocked(MockedSSHClient.file_chmod)
    def file_chmod(self, filename, mode):
        """
        Sets the mode of a remote file
        :param filename: File to chmod
        :param mode: Mode to give to file, eg: 0744
        """
        self.run(['chmod', oct(mode), filename])

    @mocked(MockedSSHClient.file_chown)
    def file_chown(self, filenames, user, group):
        """
        Sets the ownership of a remote file
        :param filenames: Files to chown
        :param user: User to set
        :param group: Group to set
        :return: None
        """
        all_users = [user_info[0] for user_info in pwd.getpwall()]
        all_groups = [group_info[0] for group_info in grp.getgrall()]

        if user not in all_users:
            raise ValueError('User "{0}" is unknown on the system'.format(user))
        if group not in all_groups:
            raise ValueError('Group "{0}" is unknown on the system'.format(group))

        uid = pwd.getpwnam(user)[2]
        gid = grp.getgrnam(group)[2]
        if isinstance(filenames, basestring):
            filenames = [filenames]
        for filename in filenames:
            if not self.file_exists(filename=filename):
                continue
            if self.is_local:
                os.chown(filename, uid, gid)
            else:
                self.run(['chown', '{0}:{1}'.format(user, group), filename])

    @mocked(MockedSSHClient.file_list)
    def file_list(self, directory, abs_path=False, recursive=False):
        """
        List all files in directory
        WARNING: If executed recursively while not locally, this can take quite some time

        :param directory: Directory to list the files in
        :param abs_path: Return the absolute path of the files or only the file names
        :param recursive: Loop through the directories recursively
        :return: List of files in directory
        """
        all_files = []
        if self.is_local:
            for root, dirs, files in os.walk(directory):
                for file_name in files:
                    if abs_path:
                        all_files.append('/'.join([root, file_name]))
                    else:
                        all_files.append(file_name)
                if not recursive:
                    break
        else:
            with remote(self.ip, [os], 'root') as rem:
                for root, dirs, files in rem.os.walk(directory):
                    for file_name in files:
                        if abs_path:
                            all_files.append('/'.join([root, file_name]))
                        else:
                            all_files.append(file_name)
                    if not recursive:
                        break
        return all_files

    @mocked(MockedSSHClient.file_move)
    def file_move(self, source_file_name, destination_file_name):
        """
        Move a file
        :param source_file_name: Absolute path of the file to move
        :type source_file_name: str
        :param destination_file_name: Location to move to (Can be (new) filename or directory)
        :type destination_file_name: str
        :raises: ValueError - When source file does not exists
        :return: None
        :rtype: NoneType
        """
        if not source_file_name.startswith('/'):
            raise ValueError('Source should start with a "/"')
        if not destination_file_name.startswith('/'):
            raise ValueError('Destination should start with a "/"')
        if not self.file_exists(filename=source_file_name):
            raise ValueError('Source file {0} does not exist'.format(source_file_name))

        while '//' in source_file_name:
            source_file_name.replace('//', '/')
        while '//' in destination_file_name:
            destination_file_name.replace('//', '/')

        if self.dir_exists(directory=destination_file_name):
            target_dir = destination_file_name
            # If destination is a directory, we use file name of source
            destination_file_name = os.path.join(destination_file_name, os.path.basename(source_file_name))
        else:
            target_dir = os.path.dirname(destination_file_name)

        if not self.dir_exists(directory=target_dir):
            self.dir_create(directories=target_dir)

        if self.is_local:
            return os.rename(source_file_name, destination_file_name)
        else:
            command = """import os, json
print json.dumps(os.rename('{0}', '{1}'))""".format(source_file_name, destination_file_name)
            return json.loads(self.run(['python', '-c', """{0}""".format(command)]))

    @connected()
    @mocked(MockedSSHClient.path_exists)
    def path_exists(self, file_path):
        """
        Checks if a file exists on a remote host
        :param file_path: File path to check for existence
        :type file_path: str
        """
        if self.is_local:
            return os.path.exists(file_path)
        else:
            command = """import os, json
print json.dumps(os.path.exists('{0}'))""".format(file_path)
            return json.loads(self.run(['python', '-c', """{0}""".format(command)]))

    def is_mounted(self, path):
        """
        Verify whether a mount point is mounted
        :param path: Path to check
        :type path: str
        :return: True if mount point is mounted
        :rtype: bool
        """
        path = path.rstrip('/')
        if self.is_local:
            return os.path.ismount(path)

        command = """import os, json
print json.dumps(os.path.ismount('{0}'))""".format(path)
        try:
            return json.loads(self.run(['python', '-c', """{0}""".format(command)]))
        except ValueError:
            return False

    def get_hostname(self):
        """
        Gets the simple and fq domain name
        """
        short = self.run(['hostname', '-s'])
        try:
            fqdn = self.run(['hostname', '-f'])
        except:
            fqdn = short
        return short, fqdn
