# -*- coding: UTF-8 -*-
#  Copyright (C) 2016 iNuron NV
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
Test module for the Extensions
"""

import unittest
from ovs_extensions.generic.toolbox import ExtensionsToolbox

class ExtensionsToolboxTest(unittest.TestCase):

    def test_filter_dict_for_none(self):
        d = {'a': 'a',
             'b': {'b1': 'b1',
                   'b2': None},
             'c': None,
             'd': {'d1': {'d11': {'d111': 'd111'}}},
             'e': {'e1': None}}

        result_dict = {'a': 'a',
                       'b': {'b1': 'b1'},
                       'd': {'d1': {'d11': {'d111': 'd111'}}}}
        filtered_dict = ExtensionsToolbox.filter_dict_for_none(d)
        self.assertEquals(filtered_dict, result_dict)

