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
Wrapper class for the storagedriver client of the voldrv team
"""
import os
import copy
import json
from ovs.extensions.db.arakoon.arakooninstaller import ArakoonClusterConfig
from ovs.extensions.generic.configuration import Configuration
from ovs.extensions.generic.remote import remote
from ovs.log.log_handler import LogHandler
from volumedriver.storagerouter import storagerouterclient

# Import below classes so the rest of the framework can always import from this module:
# * We can inject mocks easier without having to make changes everywhere
# * We can handle backwards compatibility better
# noinspection PyUnresolvedReferences

from volumedriver.storagerouter.storagerouterclient import \
    ClusterContact, ClusterNodeConfig, \
    DTLConfig, DTLConfigMode, DTLMode, Logger, \
    MaxRedirectsExceededException, MDSMetaDataBackendConfig,  MDSNodeConfig, \
    ObjectNotFoundException as SRCObjectNotFoundException, \
    ReadCacheBehaviour, ReadCacheMode, SnapshotNotFoundException, \
    Role, Statistics, VolumeInfo
try:
    from volumedriver.storagerouter.storagerouterclient import VolumeRestartInProgressException
except ImportError:
    from ovs.extensions.storageserver.tests.mockups import VolumeRestartInProgressException

if os.environ.get('RUNNING_UNITTESTS') == 'True':
    from ovs.extensions.storageserver.tests.mockups import \
        ArakoonNodeConfig, ClusterRegistry, LocalStorageRouterClient, \
        MDSClient, ObjectRegistryClient as ORClient, StorageRouterClient, \
        FileSystemMetaDataClient
else:
    from volumedriver.storagerouter.storagerouterclient import \
        ArakoonNodeConfig, ClusterRegistry, LocalStorageRouterClient, \
        MDSClient, ObjectRegistryClient as ORClient, StorageRouterClient
    try:
        from volumedriver.storagerouter.storagerouterclient import FileSystemMetaDataClient
    except ImportError:
        FileSystemMetaDataClient = None


client_vpool_cache = {}
oclient_vpool_cache = {}
crclient_vpool_cache = {}
fsmclient_vpool_cache = {}
mdsclient_service_cache = {}


class FeatureNotAvailableException(Exception):
    """
    Raised when feature is not yet available
    """
    pass


# noinspection PyArgumentList
class StorageDriverClient(object):
    """
    Client to access storagedriver client
    """
    storagerouterclient.Logger.setupLogging(LogHandler.load_path('storagerouterclient'))
    # noinspection PyArgumentList
    storagerouterclient.Logger.enableLogging()

    VOLDRV_DTL_SYNC = 'Synchronous'
    VOLDRV_DTL_ASYNC = 'Asynchronous'
    VOLDRV_DTL_MANUAL_MODE = 'Manual'
    VOLDRV_DTL_AUTOMATIC_MODE = 'Automatic'
    VOLDRV_DTL_TRANSPORT_TCP = 'TCP'
    VOLDRV_DTL_TRANSPORT_RSOCKET = 'RSocket'

    FRAMEWORK_DTL_SYNC = 'sync'
    FRAMEWORK_DTL_ASYNC = 'a_sync'
    FRAMEWORK_DTL_NO_SYNC = 'no_sync'
    FRAMEWORK_DTL_TRANSPORT_TCP = 'tcp'
    FRAMEWORK_DTL_TRANSPORT_RSOCKET = 'rdma'

    VDISK_DTL_MODE_MAP = {FRAMEWORK_DTL_SYNC: DTLMode.SYNCHRONOUS,
                          FRAMEWORK_DTL_ASYNC: DTLMode.ASYNCHRONOUS,
                          FRAMEWORK_DTL_NO_SYNC: None}
    VPOOL_DTL_MODE_MAP = {FRAMEWORK_DTL_SYNC: VOLDRV_DTL_SYNC,
                          FRAMEWORK_DTL_ASYNC: VOLDRV_DTL_ASYNC,
                          FRAMEWORK_DTL_NO_SYNC: None}
    VPOOL_DTL_TRANSPORT_MAP = {FRAMEWORK_DTL_TRANSPORT_TCP: VOLDRV_DTL_TRANSPORT_TCP,
                               FRAMEWORK_DTL_TRANSPORT_RSOCKET: VOLDRV_DTL_TRANSPORT_RSOCKET}
    REVERSE_DTL_MODE_MAP = {VOLDRV_DTL_SYNC: FRAMEWORK_DTL_SYNC,
                            VOLDRV_DTL_ASYNC: FRAMEWORK_DTL_ASYNC,
                            DTLMode.SYNCHRONOUS: FRAMEWORK_DTL_SYNC,
                            DTLMode.ASYNCHRONOUS: FRAMEWORK_DTL_ASYNC}
    REVERSE_DTL_TRANSPORT_MAP = {VOLDRV_DTL_TRANSPORT_TCP: FRAMEWORK_DTL_TRANSPORT_TCP,
                                 VOLDRV_DTL_TRANSPORT_RSOCKET: FRAMEWORK_DTL_TRANSPORT_RSOCKET}
    CLUSTER_SIZES = [4, 8, 16, 32, 64]
    TLOG_MULTIPLIER_MAP = {4: 16,
                           8: 8,
                           16: 4,
                           32: 2,
                           64: 1,
                           128: 1}

    DTL_STATUS = {'': 0,
                  'ok_sync': 10,
                  'ok_standalone': 20,
                  'catch_up': 30,
                  'checkup_required': 30,
                  'degraded': 40}
    EMPTY_STATISTICS = staticmethod(lambda: Statistics())
    EMPTY_INFO = staticmethod(lambda: VolumeInfo())
    STAT_SUMS = {'operations': ['write_operations', 'read_operations'],
                 'cache_hits': ['sco_cache_hits', 'cluster_cache_hits'],
                 'cache_misses': ['sco_cache_misses'],
                 '4k_operations': ['4k_read_operations', '4k_write_operations'],
                 '4k_unaligned_operations': ['4k_unaligned_read_operations', '4k_unaligned_write_operations'],
                 'data_transferred': ['data_written', 'data_read']}

    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def load(vpool, excluded_storagedrivers=None):
        """
        Initializes the wrapper for a given vpool
        :param vpool: vPool for which the StorageRouterClient needs to be loaded
        :type vpool: vPool
        :param excluded_storagedrivers: A list of storagedrivers that cannot be used as a client
        :type excluded_storagedrivers: list or None
        """
        if excluded_storagedrivers is None:
            excluded_storagedrivers = []
        key = vpool.identifier
        if key not in client_vpool_cache:
            cluster_contacts = []
            for storagedriver in vpool.storagedrivers[:3]:
                if storagedriver not in excluded_storagedrivers:
                    cluster_contacts.append(ClusterContact(str(storagedriver.cluster_ip), storagedriver.ports['xmlrpc']))
            client = StorageRouterClient(str(vpool.guid), cluster_contacts)
            client_vpool_cache[key] = client
        return client_vpool_cache[key]


class ObjectRegistryClient(object):
    """
    Client to access the object registry
    """
    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def load(vpool):
        """
        Initializes the wrapper for a given vpool
        :param vpool: vPool for which the ObjectRegistryClient needs to be loaded
        """
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            return ORClient(str(vpool.guid), None, None)

        key = vpool.identifier
        if key not in oclient_vpool_cache:
            arakoon_node_configs = []
            arakoon_cluster_name = str(Configuration.get('/ovs/framework/arakoon_clusters|voldrv'))
            config = ArakoonClusterConfig(cluster_id=arakoon_cluster_name)
            for node in config.nodes:
                arakoon_node_configs.append(ArakoonNodeConfig(str(node.name), str(node.ip), node.client_port))
            client = ORClient(str(vpool.guid), str(arakoon_cluster_name), arakoon_node_configs)
            oclient_vpool_cache[key] = client
        return oclient_vpool_cache[key]


class MetadataServerClient(object):
    """
    Builds a MDSClient
    """
    _logger = LogHandler.get('extensions', name='storagedriver')
    storagerouterclient.Logger.setupLogging(LogHandler.load_path('storagerouterclient'))
    # noinspection PyArgumentList
    storagerouterclient.Logger.enableLogging()

    MDS_ROLE = type('MDSRole', (), {'MASTER': Role.Master,
                                    'SLAVE': Role.Slave})

    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def load(service):
        """
        Loads a MDSClient
        :param service: Service for which the MDSClient needs to be loaded
        """
        if service.storagerouter is None:
            raise ValueError('MDS service {0} does not have a Storage Router linked to it'.format(service.name))

        key = service.guid
        if key not in mdsclient_service_cache:
            try:
                # noinspection PyArgumentList
                client = MDSClient(MDSNodeConfig(address=str(service.storagerouter.ip), port=service.ports[0]))
                mdsclient_service_cache[key] = client
            except RuntimeError as ex:
                MetadataServerClient._logger.error('Error loading MDSClient on {0}: {1}'.format(service.storagerouter.ip, ex))
                return None
        return mdsclient_service_cache[key]


class ClusterRegistryClient(object):
    """
    Builds a CRClient
    """
    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def load(vpool):
        """
        Initializes the wrapper for a given vpool
        :param vpool: vPool for which the ClusterRegistryClient needs to be loaded
        """
        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            return ClusterRegistry(str(vpool.guid), None, None)

        key = vpool.identifier
        if key not in crclient_vpool_cache:
            arakoon_cluster_name = str(Configuration.get('/ovs/framework/arakoon_clusters|voldrv'))
            config = ArakoonClusterConfig(cluster_id=arakoon_cluster_name)
            arakoon_node_configs = []
            for node in config.nodes:
                arakoon_node_configs.append(ArakoonNodeConfig(str(node.name), str(node.ip), node.client_port))
            client = ClusterRegistry(str(vpool.guid), arakoon_cluster_name, arakoon_node_configs)
            crclient_vpool_cache[key] = client
        return crclient_vpool_cache[key]


class FSMetaDataClient(object):
    """
    Builds a FileSystemMetaDataClient
    """
    def __init__(self):
        """
        Dummy init method
        """
        pass

    @staticmethod
    def load(vpool):
        """
        Initializes the wrapper for a given vPool
        :param vpool: vPool for which the FileSystemMetaDataClient needs to be loaded
        """
        if FileSystemMetaDataClient is None:
            raise FeatureNotAvailableException()

        if os.environ.get('RUNNING_UNITTESTS') == 'True':
            return FileSystemMetaDataClient(str(vpool.guid), None, None)

        key = vpool.identifier
        if key not in fsmclient_vpool_cache:
            arakoon_cluster_name = str(Configuration.get('/ovs/framework/arakoon_clusters|voldrv'))
            config = ArakoonClusterConfig(cluster_id=arakoon_cluster_name)
            arakoon_node_configs = []
            for node in config.nodes:
                arakoon_node_configs.append(ArakoonNodeConfig(str(node.name), str(node.ip), node.client_port))
            client = FileSystemMetaDataClient(str(vpool.guid), arakoon_cluster_name, arakoon_node_configs)
            fsmclient_vpool_cache[key] = client
        return fsmclient_vpool_cache[key]


class StorageDriverConfiguration(object):
    """
    StorageDriver configuration class
    """

    def __init__(self, config_type, vpool_guid, storagedriver_id):
        """
        Initializes the class
        """
        if config_type != 'storagedriver':
            raise RuntimeError('Invalid configuration type. Allowed: storagedriver')

        storagerouterclient.Logger.setupLogging(LogHandler.load_path('storagerouterclient'))
        # noinspection PyArgumentList
        storagerouterclient.Logger.enableLogging()

        self._logger = LogHandler.get('extensions', name='storagedriver')
        self.config_type = config_type
        self.configuration = {}
        self.key = '/ovs/vpools/{0}/hosts/{1}/config'.format(vpool_guid, storagedriver_id)
        self.remote_path = Configuration.get_configuration_path(self.key).strip('/')
        self.is_new = True
        self.dirty_entries = []

    def load(self):
        """
        Loads the configuration from a given file, optionally a remote one
        """
        self.configuration = {}
        if Configuration.exists(self.key):
            self.is_new = False
            self.configuration = json.loads(Configuration.get(self.key, raw=True))
        else:
            self._logger.debug('Could not find config {0}, a new one will be created'.format(self.key))
        self.dirty_entries = []

    def save(self, client=None, force_reload=False):
        """
        Saves the configuration to a given file, optionally a remote one
        :param client: If provided, save remote configuration
        :type client: ovs.extensions.generic.sshclient.SSHClient
        :param force_reload: Make sure the 'update_configuration' gets triggered. Should be used when configuration changes have been applied from 'outside'
        :type force_reload: bool
        :return: Changes to the configuration
        :rtype: list
        """
        changes = []
        Configuration.set(self.key, json.dumps(self.configuration, indent=4), raw=True)

        # No changes detected in the configuration management
        if len(self.dirty_entries) == 0 and force_reload is False:
            self._logger.debug('No need to apply changes, nothing changed')
            self.is_new = False
            return changes

        # Retrieve the changes from volumedriver
        self._logger.info('Applying local storagedriver configuration changes{0}'.format('' if client is None else ' on {0}'.format(client.ip)))
        reloaded = False
        try:
            if client is None:
                changes = LocalStorageRouterClient(self.remote_path).update_configuration(self.remote_path)
            else:
                with remote(client.ip, [LocalStorageRouterClient]) as rem:
                    changes = copy.deepcopy(rem.LocalStorageRouterClient(self.remote_path).update_configuration(self.remote_path))
            reloaded = True
        except Exception as ex:
            if 'ClusterNotReachableException' not in str(ex):
                raise

        # No changes
        if len(changes) == 0:
            if reloaded is True:
                if len(self.dirty_entries) > 0:
                    self._logger.warning('Following changes were not applied: {0}'.format(', '.join(self.dirty_entries)))
            else:
                self._logger.warning('Changes were not applied since StorageDriver is unavailable')
            self.is_new = False
            self.dirty_entries = []
            return changes

        # Verify the output of the changes and log them
        for change in changes:
            if not isinstance(change, dict):
                raise RuntimeError('Unexpected update_configuration output')
            if 'param_name' not in change or 'old_value' not in change or 'new_value' not in change:
                raise RuntimeError('Unexpected update_configuration output. Expected different keys, but got {0}'.format(', '.join(change.keys())))

            param_name = change['param_name']
            if force_reload is False:
                if param_name not in self.dirty_entries:
                    raise RuntimeError('Unexpected configuration change: {0}'.format(param_name))
                self.dirty_entries.remove(param_name)
            self._logger.info('Changed {0} from "{1}" to "{2}"'.format(param_name, change['old_value'], change['new_value']))
        self._logger.info('Changes applied')
        if len(self.dirty_entries) > 0:
            self._logger.warning('Following changes were not applied: {0}'.format(', '.join(self.dirty_entries)))
        self.is_new = False
        self.dirty_entries = []
        return changes

    def __getattr__(self, item):
        from ovs.extensions.generic.toolbox import ExtensionsToolbox

        if item.startswith('configure_'):
            section = ExtensionsToolbox.remove_prefix(item, 'configure_')
            return lambda **kwargs: self._add(section, **kwargs)
        if item.startswith('clear_'):
            section = ExtensionsToolbox.remove_prefix(item, 'clear_')
            return lambda: self._delete(section)

    def _add(self, section, **kwargs):
        """
        Configures a section
        """
        for item, value in kwargs.iteritems():
            if section not in self.configuration:
                self.configuration[section] = {}
            if item not in self.configuration[section] or self.configuration[section][item] != value:
                self.dirty_entries.append(item)
            self.configuration[section][item] = value

    def _delete(self, section):
        """
        Removes a section from the configuration
        """
        if section in self.configuration:
            del self.configuration[section]
