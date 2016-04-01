# Copyright 2016 iNuron NV
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#     http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

"""
RoleList module
"""
from ovs.dal.datalist import DataList
from ovs.dal.hybrids.role import Role


class RoleList(object):
    """
    This RoleList class contains various lists regarding to the Role class
    """

    @staticmethod
    def get_roles():
        """
        Returns a list of all Roles
        """
        return DataList(Role, {'type': DataList.where_operator.AND,
                               'items': []})

    @staticmethod
    def get_role_by_code(code):
        """
        Returns a single Role for the given code. Returns None if no Role was found
        """
        roles = DataList(Role, {'type': DataList.where_operator.AND,
                                'items': [('code', DataList.operator.EQUALS, code)]})
        if len(roles) == 1:
            return roles[0]
        return None

    @staticmethod
    def get_roles_by_codes(codes):
        """
        Returns a list of Roles for a list of codes
        """
        return DataList(Role, {'type': DataList.where_operator.AND,
                               'items': [('code', DataList.operator.IN, codes)]})
