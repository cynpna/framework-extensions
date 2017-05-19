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
OS Factory module
"""
import logging
from subprocess import check_output
from ovs_extensions.os.interfaces.centos import Centos
from ovs_extensions.os.interfaces.ubuntu import Ubuntu

logger = logging.getLogger(__name__)


class OSFactory(object):
    """
    Factory class returning specialized classes
    """

    @classmethod
    def get_manager(cls):
        """
        Returns an os manager
        """
        if not hasattr(OSFactory, 'manager') or OSFactory.manager is None:
            try:
                dist_info = check_output('cat /etc/os-release', shell=True)
                if 'Ubuntu' in dist_info:
                    OSFactory.manager = Ubuntu
                elif 'CentOS Linux' in dist_info:
                    OSFactory.manager = Centos
            except Exception as ex:
                logger.exception('Error loading OSManager: {0}'.format(ex))
                raise

        if OSFactory.manager is None:
            raise RuntimeError('Unknown OSManager')

        return OSFactory.manager