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
Disk module
"""

import re
import json
import time
import uuid
from subprocess import check_output, CalledProcessError
from ovs_extensions.generic.filemutex import file_mutex
from ovs_extensions.generic.sshclient import SSHClient
from ovs_extensions.log.logger import Logger


class LSBLKEntry(object):
    """
    Represent an entry that LSBLK json output returns
    Keys returned:
    {u'fstype', u'kname', u'log-sec', u'maj:min', u'model', u'mountpoint', u'rota', u'serial', u'size', u'state', u'type'}
    """
    class EntryTypes(object):
        ROM = 'rom'
        DISK = 'disk'
        PARTITION = 'partition'
        TYPES = frozenset([ROM, DISK, PARTITION])

    class FSTypes(object):
        EXT4 = 'ext4'
        SWAP = 'swap'
        TYPES = frozenset([EXT4, SWAP])

    KEYS_TO_CHANGE = [('log-sec', 'log_sec'), ('maj:min', 'maj_min')]
    # Rota has be converted twice. Initial value is either '0' or '1'. The integer value can be used to determine
    # if it is positive, not the string value (bool('0') -> True). Order matters within this list (left to right)
    KEYS_TO_CONVERT = [('log_sec', int), ('size', int), ('rota', int), ('rota', bool)]

    def __init__(self, fstype, kname, log_sec, maj_min, model, mountpoint, rota, serial, size, state, type):
        # type: (str, str, int, str, str ,str, str, str, str, str, str) -> None
        """
        Initialize a LSBLK entry
        :param fstype: Filesystem type (eg 'ext4')
        :type fstype: str
        :param kname: Name of the block device (eg 'sda')
        :type kname: str
        :param log_sec: Logical sector size (eg '512'). This container will convert it to an integer
        :type: log_sec: int
        :param maj_min: Major and minor device number (eg '8:0')
        :param model: Model of the block device (eg 'QEMU_HARDDISK', None if the block device is a partition)
        :param mountpoint: Mountpoint of the block device (eg '/mnt/hdd1', None if not mounted)
        :param rota: Rotational device (eg '1'). This container will convert it to a boolean
        :param serial: Serial number of the device (eg 'b78f6fae-9c4d-11e6-9', None if partition or no serial on the drive)
        :param size: Size of the device in bytes (eg '10735321088'). This container will convert it to an integer
        :param state: State of the device (eg 'running', None if partition)
        :param type: Type of the device (eg 'disk' or 'part')
        """
        self.fstype = fstype
        self.kname = kname
        self.log_sec = int(log_sec)
        self.maj_min= maj_min
        self.model = model
        self.mountpoint = mountpoint
        self.rota = bool(int(rota))  # Can be '0' or '1'
        self.serial = serial
        self.size = int(size)
        self.state = state
        self.type = type

    def split_device_number(self):
        # type: () -> Tuple[str, str]
        """
        Retrieve the split device number
        :return: The split device number. Tuple with major and minor device number
        :rtype: Tuple[str, str]
        """
        return self.maj_min.split(':')

    @classmethod
    def from_lsblk_output(cls, device_output):
        # type: (dict) -> LSBLKEntry
        """
        Retrieve a new LSBLKEntry object from the direct output of the LSBLK output
        This can only be used to represent objects from the 'block_devices' section of the output
        :param device_output: Output for the device
        :type device_output: dict
        :return: The new LSBLKEntry
        :rtype: LSBLKEntry
        """
        # Copy since certain keys will be changed
        device_output_copy = device_output.copy()
        for old_key, new_key in cls.KEYS_TO_CHANGE:
            device_output_copy[new_key] = device_output_copy.pop(old_key)
        # Change the type of certain entries
        for key, new_type in cls.KEYS_TO_CONVERT:
            device_output_copy[key] = new_type(device_output_copy[key])
        return cls(**device_output_copy)


class Partition(object):
    """
    Partition Model
    """
    def __init__(self, size, state, offset, aliases, filesystem, mountpoint):
        # type: (int, str, int, List[str], str, str) -> None
        """
        Initialize a new partition model
        :param size: Size of the partition
        :param state: State of the partition
        :param offset: Offset of the partition
        :param aliases: Aliases of the partition
        :param filesystem: Filesystem of the partition (if any)
        :param mountpoint: Mountpoint of the partition (if any)
        """
        self.size = size
        self.state = state
        self.offset = offset
        self.aliases = aliases
        self.filesystem = filesystem
        self.mountpoint = mountpoint


class Disk(object):
    """
    Disk model
    """
    class DiskStates(object):
        """
        Container class for the possible states of a disk
        """
        OK = 'OK'
        MISSING = 'MISSING'
        FAILURE = 'FAILURE'
        STATES = frozenset([OK, MISSING, FAILURE])

    def __init__(self, name, state, aliases, is_ssd, model, size, serial, partitions=None):
        # type: (str, str, List[str], bool, str, int, str, List[Partition]) -> None
        """
        Model a disk object
        :param name: Name of the disk eg sda
        :param state: The state of the disk
        :param aliases:
        :param is_ssd:
        :param model:
        :param size:
        :param serial:
        :param partitions:
        """
        super(Disk, self).__init__()
        if partitions is None:
            partitions = []
        self.name = name
        self.state = state
        self.aliases = aliases
        self.is_ssd = is_ssd
        self.model = model
        self.size = size
        self.serial = serial
        self.partitions = partitions

    def add_partition_model(self, partition):
        # type: (Partition) -> List[Partition]
        """
        Add a partition to the object
        :param partition: The partition to add
        :type partition: Partition
        :return: All partitions
        :rtype: List[Partition]
        """
        self.partitions.append(partition)
        return self.partitions

    @classmethod
    def convert_lsblk_state(cls, entry):
        # type: (LSBLKEntry) -> str
        """
        Converts the LSBLKEntry state to the one from Disk
        :param entry: The LSBLKEntry object to build the disk from
        :type entry: LSBLKEntry
        :return: The converted state
        :rtype: str
        """
        if entry.state == 'running' or entry.split_device_number()[0] != '8':
            converted_state = cls.DiskStates.OK
        else:
            converted_state = cls.DiskStates.FAILURE
        return converted_state

    @classmethod
    def from_lsblk_entry(cls, entry, aliases):
        # type: (LSBLKEntry, List[str]) -> Disk
        """
        Build a Disk object from the LSBLKEntry
        These disk objects are more familiar to the Framework and its managers than the LSBLKEntry object
        :param entry: The LSBLKEntry object to build the disk from
        :type entry: LSBLKEntry
        :param aliases: Aliases for the disk
        :type aliases: List[str]
        :return: The new Disk
        :rtype: Disk
        """
        converted_state = cls.convert_lsblk_state(entry)
        disk = cls(name=entry.kname,
                   state=converted_state,
                   aliases=aliases,
                   is_ssd=not entry.rota,
                   model=entry.model,
                   size=entry.size,
                   serial=entry.serial)
        return disk


class DiskTools(object):
    """
    This class contains various helper methods wrt Disk maintenance
    """
    logger = Logger('ovs_extensions')  # Instantiated by classes inheriting from this 1

    def __init__(self):
        raise Exception('Cannot instantiate, completely static class')

    @classmethod
    def create_partition(cls, disk_alias, disk_size, partition_start, partition_size):
        """
        Creates a partition
        :param disk_alias: Path of the disk device
        :type disk_alias: str
        :param disk_size: Total size of disk
        :type disk_size: int
        :param partition_start: Start of partition in bytes
        :type partition_start: int
        :param partition_size: Size of partition in bytes
        :type partition_size: int
        :return: None
        """
        # Verify current label type and add GPT label if none present
        disk_alias = disk_alias.replace(r"'", r"'\''")
        try:
            command = "parted '{0}' print | grep 'Partition Table'".format(disk_alias)
            cls.logger.info('Checking partition label-type with command: {0}'.format(command))
            label_type = check_output(command, shell=True).strip().split(': ')[1]
        except CalledProcessError:
            label_type = 'error'
        if label_type in ('error', 'unknown'):
            try:
                cls.logger.info('Adding GPT label and trying to create partition again')
                check_output("parted '{0}' -s mklabel gpt".format(disk_alias), shell=True)
                label_type = 'gpt'
            except Exception:
                cls.logger.error('Error during label creation')
                raise

        # Determine command to use based upon label type
        start = int(round(float(partition_start) / disk_size * 100))
        end = int(round(float(partition_size) / disk_size * 100)) + start
        if end > 100:
            end = 100

        if label_type == 'gpt':
            command = "parted '{0}' -a optimal -s mkpart '{1}' '{2}%' '{3}%'".format(disk_alias, uuid.uuid4(), start, end)
        elif label_type == 'msdos':
            command = "parted '{0}' -a optimal -s mkpart primary ext4 '{1}%' '{2}%'".format(disk_alias, start, end)
        elif label_type == 'bsd':
            command = "parted '{0}' -a optimal -s mkpart ext4 '{1}%' '{2}%'".format(disk_alias, start, end)
        else:
            raise ValueError('Unsupported label-type detected: {0}'.format(label_type))

        # Create partition
        cls.logger.info('Label type detected: {0}'.format(label_type))
        cls.logger.info('Command to create partition: {0}'.format(command))
        check_output(command, shell=True)

    @classmethod
    def make_fs(cls, partition_alias):
        """
        Creates a filesystem
        :param partition_alias: Path of the partition
        :type partition_alias: str
        :return: None
        """
        try:
            check_output("mkfs.ext4 -q '{0}'".format(partition_alias.replace(r"'", r"'\''")), shell=True)
        except Exception:
            cls.logger.error('Error during filesystem creation')
            raise

    @classmethod
    def add_fstab(cls, partition_aliases, mountpoint, filesystem):
        """
        Add entry to /etc/fstab for mountpoint
        :param partition_aliases: Possible aliases of the partition to add
        :type partition_aliases: list
        :param mountpoint: Mountpoint on which device is mounted
        :type mountpoint: str
        :param filesystem: Filesystem used
        :type filesystem: str
        :return: None
        """
        if len(partition_aliases) == 0:
            raise ValueError('No partition aliases provided')

        with open('/etc/fstab', 'r') as fstab_file:
            lines = [line.strip() for line in fstab_file.readlines()]

        osmanager = cls._get_os_manager()
        used_path = None
        used_index = None
        mount_line = None
        for device_alias in partition_aliases:
            for index, line in enumerate(lines):
                if line.startswith('#'):
                    continue
                if line.startswith(device_alias) and re.match('^{0}\s+'.format(re.escape(device_alias)), line):
                    used_path = device_alias
                    used_index = index
                if len(line.split()) == 6 and line.split()[1] == mountpoint:  # Example line: 'UUID=40d99523-a1e7-4374-84f2-85b5d14b516e  /  swap  sw  0  0'
                    mount_line = line
            if used_path is not None:
                break

        if used_path is None:  # Partition not yet present with any of its possible aliases
            lines.append(osmanager.get_fstab_entry(partition_aliases[0], mountpoint, filesystem))
        else:  # Partition present, update information
            lines.pop(used_index)
            lines.insert(used_index, osmanager.get_fstab_entry(used_path, mountpoint, filesystem))

        if mount_line is not None:  # Mount point already in use by another device (potentially same device, but other device_path)
            lines.remove(mount_line)

        with file_mutex('ovs-fstab-lock'):
            with open('/etc/fstab', 'w') as fstab_file:
                fstab_file.write('{0}\n'.format('\n'.join(lines)))

    @staticmethod
    def mountpoint_exists(mountpoint):
        """
        Verify whether a mount point exists by browsing /etc/fstab
        :param mountpoint: Mount point to check
        :type mountpoint: str
        :return: True if mount point exists, False otherwise
        :rtype: bool
        """
        with open('/etc/fstab', 'r') as fstab_file:
            for line in fstab_file.readlines():
                if re.search('\s+{0}\s+'.format(re.escape(mountpoint)), line):
                    return True
        return False

    @classmethod
    def mount(cls, mountpoint):
        """
        Mount a partition
        :param mountpoint: Mount point on which to mount the partition
        :type mountpoint: str
        :return: None
        """
        try:
            mountpoint = mountpoint.replace(r"'", r"'\''")
            check_output("mkdir -p '{0}'".format(mountpoint), shell=True)
            check_output("mount '{0}'".format(mountpoint), shell=True)
        except Exception:
            cls.logger.exception('Error during mount')
            raise

    @classmethod
    def umount(cls, mountpoint):
        """
        Unmount a partition
        :param mountpoint: Mount point to un-mount
        :type mountpoint: str
        :return: None
        """
        try:
            check_output("umount '{0}'".format(mountpoint.replace(r"'", r"'\''")), shell=True)
        except Exception:
            cls.logger.exception('Unable to umount mount point {0}'.format(mountpoint))

    @classmethod
    def _get_os_manager(cls):
        raise NotImplementedError()

    @classmethod
    def retrieve_alias_mappings(cls, ssh_client=None):
        # type: (SSHClient) -> Tuple[dict, dict]
        """
        Retrieve the alias mapping. Both ways
        :return: Tuple with both dict mappings
        :rtype: Tuple[dict, dict]
        """
        ssh_client = ssh_client or SSHClient('127.0.0.1', username='root')
        name_alias_mapping = {}
        alias_name_mapping = {}
        for path_type in ssh_client.dir_list(directory='/dev/disk'):
            if path_type in ['by-uuid', 'by-partuuid']:  # UUIDs can change after creating a filesystem on a partition
                continue
            directory = '/dev/disk/{0}'.format(path_type)
            for symlink in ssh_client.dir_list(directory=directory):
                symlink_path = '{0}/{1}'.format(directory, symlink)
                link = ssh_client.file_read_link(path=symlink_path)
                if link not in name_alias_mapping:
                    name_alias_mapping[link] = []
                name_alias_mapping[link].append(symlink_path)
                alias_name_mapping[symlink_path] = link
        return name_alias_mapping, alias_name_mapping

    @classmethod
    def model_devices(cls, ssh_client=None, name_alias_mapping=None, alias_name_mapping=None):
        # type: (Optional[SSHClient], Optional[dict], Optional[dict]) -> List[Disk]
        """
        Model all disks that are currently on this machine
        :param name_alias_mapping: The name to alias mapping (Optional)
        :param alias_name_mapping: The alias to names mapping (Optional)
        :return: A list of modeled disks
        :rtype: List[Disk]
        """
        ssh_client = ssh_client or SSHClient('127.0.0.1', username='root')
        params = [name_alias_mapping, alias_name_mapping]
        if any(param is not None for param in params) and not all(param is not None for param in params):
            raise ValueError('Both mappings must be supplied if supplying any.')
        if not name_alias_mapping and not alias_name_mapping:
            name_alias_mapping, alias_name_mapping = cls.retrieve_alias_mappings(ssh_client)

        block_devices = cls._model_block_devices(ssh_client)
        cls.logger.info('Starting to iterate over disks')
        configuration = {}
        parsed_devices = []
        for device_entry in block_devices:  # type: LSBLKEntry
            if device_entry.type == LSBLKEntry.EntryTypes.ROM:
                continue

            # If this returns, it means its a device and not a partition
            is_device = cls.is_device(device_entry.kname, ssh_client)
            friendly_path = '/dev/{0}'.format(device_entry.kname)
            system_aliases = sorted(name_alias_mapping.get(friendly_path, [friendly_path]))
            device_is_also_partition = False
            device_state = 'OK'
            if is_device:
                disk = Disk.from_lsblk_entry(device_entry, system_aliases)
                configuration[device_entry.kname] = disk
                device_state = disk.state
                # LVM, RAID1, ... have the tendency to be a device with a partition on it, but the partition is not reported by 'lsblk'
                device_is_also_partition = bool(device_entry.mountpoint)
                parsed_devices.append({'name': disk.name, 'state': device_state})
            if not is_device or device_is_also_partition is True:
                current_device_name = None
                current_device_state = None
                if device_is_also_partition is True:
                    offset = 0
                    current_device_name = device_entry.kname
                    current_device_state = device_state
                else:
                    offset = 0
                    # Check from which block device the partition is from
                    # @todo might be more sane to go back until the disk is found since lsblk outputs them in order
                    for device_info in reversed(parsed_devices):
                        try:
                            current_device_name = device_info['name']
                            current_device_state = device_info['state']
                            starting_block = int(ssh_client.file_read('/sys/block/{0}/{1}/start'.format(current_device_name, device_entry.kname)))
                            offset = starting_block * device_entry.log_sec
                            break
                        except Exception:
                            pass
                if current_device_name is None:
                    raise RuntimeError('Failed to retrieve the device information for current partition')
                partition = Partition(size=device_entry.size,
                                      # Device state is either None or converted to OK or FAILURE at this point
                                      state=current_device_state or 'FAILURE',
                                      offset=offset,
                                      aliases=system_aliases,
                                      filesystem=device_entry.fstype,
                                      mountpoint=device_entry.mountpoint)
                if device_entry.mountpoint and device_entry.fstype != LSBLKEntry.FSTypes.SWAP:
                    if not cls.mountpoint_usable(device_entry.mountpoint):
                        partition.state = 'FAILURE'
                associated_disk = configuration[current_device_name]  # type: Disk
                associated_disk.add_partition_model(partition)

        return configuration.values()

    @classmethod
    def is_device(cls, device_name, ssh_client):
        # type: (str, SSHClient) -> bool
        """
        Determine if the LSBLKEntry maps to a device or a partition
        :param device_name: Name of the device
        :type device_name: str
        :param ssh_client: SSHClient instance
        :type ssh_client: SSHClient
        :return: True if device
        :rtype: bool
        """
        # If this returns a different path, it means its a device and not a partition
        return bool(ssh_client.file_read_link('/sys/block/{0}'.format(device_name)))

    @classmethod
    def _model_block_devices(cls, ssh_client):
        # type: (SSHClient) -> List[LSBLKEntry]
        """
        Models the block devices found on the system
                :param ssh_client: SSHClient instance
        :type ssh_client: SSHClient
        :return: List of block devices
        :rtype: List[LSBLKEntry]
        """
        # Parse 'lsblk' output
        # --exclude 1 for RAM devices, 2 for floppy devices, 11 for CD-ROM devices, 43 for nbd devices (See https://www.kernel.org/doc/html/v4.15/admin-guide/devices.html)
        command = ['lsblk', '--json', '--bytes', '--noheadings', '--exclude', '1,2,11,43']
        output = '--output=KNAME,SIZE,MODEL,STATE,MAJ:MIN,FSTYPE,TYPE,ROTA,MOUNTPOINT,LOG-SEC{0}'
        cls.logger.info(command + [output.format(',SERIAL')])
        try:
            devices = json.loads(ssh_client.run(command + [output.format(',SERIAL')]).splitlines())  # type: dict
        except Exception:
            devices = json.loads(ssh_client.run(command + [output.format('')]).splitlines())  # type: dict
        block_devices = devices.get('blockdevices', [])  # type: list
        return [LSBLKEntry.from_lsblk_output(device) for device in block_devices]

    @classmethod
    def mountpoint_usable(cls, mountpoint, ssh_client=None):
        # type: (str) -> bool
        """
        See if the mountpoint is usable
        :param mountpoint: Mountpoint to test
        :return: True if the mountpoint is usable
        :rtype: bool
        """
        ssh_client = ssh_client or SSHClient('127.0.0.1', username='root')
        try:
            filename = '{0}/{1}'.format(mountpoint, str(time.time()))
            ssh_client.run(['touch', filename])
            ssh_client.run(['rm', filename])
            return True
        except Exception:
            return False
