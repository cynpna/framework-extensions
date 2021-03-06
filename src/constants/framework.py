# Copyright (C) 2018 iNuron NV
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
Shared strings
"""

import os

FRAMEWORK_BASE = os.path.join(os.path.sep, 'ovs', 'framework')

### Remote config
REMOTE_CONFIG_BACKEND_BASE = os.path.join(FRAMEWORK_BASE, 'used_configs', 'alba_backends')          # /ovs/framework/used_configs/alba_backends
REMOTE_CONFIG_BACKEND_CONFIG = os.path.join(REMOTE_CONFIG_BACKEND_BASE, '{0}', 'abm_config')        # /ovs/framework/used_configs/alba_backends/{0}/abm_config
REMOTE_CONFIG_BACKEND_INI = os.path.join(REMOTE_CONFIG_BACKEND_BASE, '{0}', 'abm_config.ini')       # /ovs/framework/used_configs/alba_backends/{0}/abm_config.ini

### NBD related config paths
NBD = os.path.join(FRAMEWORK_BASE, 'nbdnodes')                                                      # /ovs/framework/nbdnodes
NBD_ID = os.path.join(NBD, '{0}')                                                                   # /ovs/framework/nbdnodes/{0}


### SCRUBBER related config paths

SCRUB_KEY = os.path.join(FRAMEWORK_BASE, 'jobs', 'scrub')                                           # /ovs/framework/jobs/scrub
SCRUB_JOB = os.path.join(SCRUB_KEY, '{0}', 'job_info')                                              # /ovs/framework/jobs/scrub/{0}/job_info

PLUGINS_BASE = os.path.join(FRAMEWORK_BASE, 'plugins')
PLUGINS_INSTALLED = os.path.join(PLUGINS_BASE, 'installed')                                         # /ovs/framework/plugins/installed
PLUGINS_ALBA_CONFIG = os.path.join(PLUGINS_BASE, 'alba', 'config')                                  # /ovs/framework/plugins/alba/config