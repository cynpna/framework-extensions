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
Centos OS module
"""

from subprocess import CalledProcessError
from subprocess import check_output
from ovs_extensions.generic.configuration import Configuration
from ovs_extensions.generic.system import System


class Centos(object):
    """
    Contains all logic related to Centos specific
    """

    @staticmethod
    def get_path(binary_name):
        """
        Retrieve the absolute path for binary
        :param binary_name: Binary to get path for
        :return: Path
        """
        machine_id = System.get_my_machine_id()
        config_location = '/ovs/framework/hosts/{0}/paths|{1}'.format(machine_id, binary_name)
        if not Configuration.exists(config_location):
            try:
                path = check_output("which '{0}'".format(binary_name.replace(r"'", r"'\''")), shell=True).strip()
                Configuration.set(config_location, path)
            except CalledProcessError:
                return None
        else:
            path = Configuration.get(config_location)
        return path

    @staticmethod
    def get_fstab_entry(device, mp, filesystem='ext4'):
        """
        Retrieve fstab entry for mountpoint
        :param device: Device in fstab
        :param mp: Mountpoint
        :param filesystem: Filesystem of entry
        :return: Fstab entry
        """
        return '{0}    {1}         {2}    defaults,nofail,noatime,discard    0    2'.format(device, mp, filesystem)

    @staticmethod
    def get_ssh_service_name():
        """
        Retrieve SSH service name
        :return: SSH service name
        """
        return 'sshd'

    @staticmethod
    def get_openstack_web_service_name():
        """
        Retrieve openstack webservice name
        :return: Openstack webservice name
        """
        return 'httpd'

    @staticmethod
    def get_openstack_cinder_service_name():
        """
        Retrieve openstack cinder service name
        :return: Openstack cinder service name
        """
        return 'openstack-cinder-volume'

    @staticmethod
    def get_openstack_services():
        """
        Retrieve openstack services
        :return: Openstack services
        """
        return ['openstack-nova-compute', 'openstack-cinder-volume', 'openstack-cinder-api']

    @staticmethod
    def get_openstack_users():
        """
        Retrieve openstack users
        :return: Openstack users
        """
        return ['qemu', 'cinder', 'nova']

    @staticmethod
    def get_openstack_package_base_path():
        """
        Retrieve openstack package base path
        :return: Openstack package base path
        """
        return '/usr/lib/python2.7/site-packages'
