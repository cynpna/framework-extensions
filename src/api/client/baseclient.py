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
Module for the OVS API client
"""
import base64
import urllib
import hashlib
import logging
import requests
from requests.packages.urllib3 import disable_warnings
from requests.packages.urllib3.exceptions import InsecurePlatformWarning, InsecureRequestWarning, SNIMissingWarning
from ovs_extensions.api.exceptions import HttpException, HttpForbiddenException, HttpNotFoundException
# noinspection PyUnresolvedReferences
from ovs_extensions.api.exceptions import HttpForbiddenException as ForbiddenException  # Backwards compatibility
# noinspection PyUnresolvedReferences
from ovs_extensions.api.exceptions import HttpNotFoundException as NotFoundException  # Backwards compatibility
from ovs_extensions.generic.toolbox import ExtensionsToolbox


class BaseClient(object):
    """
    Basic API client
    - Supports Authorization with tokens
    - Caches tokens
    """
    disable_warnings(InsecurePlatformWarning)
    disable_warnings(InsecureRequestWarning)
    disable_warnings(SNIMissingWarning)

    _logger = logging.getLogger(__name__)

    def __init__(self, ip, port, credentials=None, verify=False, version='*', raw_response=False, cache_store=None):
        """
        Initializes the object with credentials and connection information
        :param ip: IP to which to connect
        :type ip: str
        :param port: Port on which to connect
        :type port: int
        :param credentials: Credentials to connect
        :type credentials: tuple
        :param verify: Additional verification
        :type verify: bool
        :param version: API version
        :type version: object
        :param raw_response: Retrieve the raw response value
        :type raw_response: bool
        :param cache_store: Store in which to keep the generated token for the client instance
        :type cache_store: any
        :return: None
        :rtype: NoneType
        """
        if credentials is not None and len(credentials) != 2:
            raise RuntimeError('Credentials should be None (no authentication) or a tuple containing client_id and client_secret (authenticated)')
        self.ip = ip
        self.port = port
        self.client_id = credentials[0] if credentials is not None else None
        self.client_secret = credentials[1] if credentials is not None else None
        self._url = 'https://{0}:{1}/api'.format(ip, port)
        self._key = hashlib.sha256('{0}{1}{2}{3}'.format(self.ip, self.port, self.client_id, self.client_secret)).hexdigest()
        self._token = None
        self._verify = verify
        self._version = version
        self._raw_response = raw_response
        self._volatile_client = cache_store

    def _connect(self):
        """
        Authenticates to the api
        """
        headers = {'Accept': 'application/json',
                   'Authorization': 'Basic {0}'.format(base64.b64encode('{0}:{1}'.format(self.client_id, self.client_secret)).strip())}
        raw_response = requests.post(url='{0}/oauth2/token/'.format(self._url),
                                     data={'grant_type': 'client_credentials'},
                                     headers=headers,
                                     verify=self._verify)

        try:
            response = self._process(response=raw_response, overrule_raw=True)
        except RuntimeError:
            if self._raw_response is True:
                return raw_response
            raise
        if len(response.keys()) in [1, 2] and 'error' in response:
            error = RuntimeError(response['error'])
            error.status_code = raw_response.status_code
            raise error
        self._token = response['access_token']

    def _build_headers(self):
        """
        Builds the request headers
        :return: The request headers
        :rtype: dict
        """
        headers = {'Accept': 'application/json; version={0}'.format(self._version),
                   'Content-Type': 'application/json'}
        if self._token is not None:
            headers['Authorization'] = 'Bearer {0}'.format(self._token)
        return headers

    @classmethod
    def _build_url_params(cls, params=None):
        """
        Build the URL params
        :param params: URL parameters
        :type params: str
        :return: The url params
        :rtype: string
        """
        url_params = ''
        if params:
            url_params = '?{0}'.format(urllib.urlencode(params))
        return url_params

    def _cache_token(self):
        """
        Caches the JWT
        :return: None
        :rtype: NoneType
        """
        if self._volatile_client is not None:
            self._volatile_client.set(self._key, self._token, 300)

    def _prepare(self, **kwargs):
        """
        Prepares the call:
        * Authentication, if required
        * Preparing headers, returning them
        """
        if self.client_id is not None and self._token is None:
            self._connect()

        headers = self._build_headers()
        params = self._build_url_params(kwargs.get('params'))
        url = '{0}{{0}}{1}'.format(self._url, params)
        self._cache_token()  # Volatile cache might have expired or the key is gone

        return headers, url

    def _process(self, response, overrule_raw=False):
        """
        Processes a call result
        """
        if self._raw_response is True and overrule_raw is False:
            return response

        status_code = response.status_code
        parsed_output = None
        try:
            parsed_output = response.json()
        except:
            pass

        if 200 <= status_code < 300:
            return parsed_output
        else:
            message = None
            if parsed_output is not None:
                if 'error_description' in parsed_output:
                    message = parsed_output['error_description']
                if 'error' in parsed_output:
                    if message is None:
                        message = parsed_output['error']
                    else:
                        message += ' ({0})'.format(parsed_output['error'])
            else:
                messages = {401: 'No access to the requested API',
                            403: 'No access to the requested API',
                            404: 'The requested API could not be found',
                            405: 'Requested method not allowed',
                            406: 'The request was unacceptable',
                            426: 'Upgrade is needed',
                            429: 'Rate limit was hit',
                            500: 'Internal server error'}
                if status_code in messages:
                    message = messages[status_code]
            if message is None:
                message = 'Unknown error'
            if status_code in [401, 403]:
                raise HttpForbiddenException(message, '')
            elif status_code == 404:
                raise HttpNotFoundException(message, '')
            else:
                raise HttpException(status_code, message)

    def _call(self, api, params, fct, timeout=None, **kwargs):
        if not api.endswith('/'):
            api = '{0}/'.format(api)
        if not api.startswith('/'):
            api = '/{0}'.format(api)
        if self._volatile_client is not None:
            self._token = self._volatile_client.get(self._key)
        first_connect = self._token is None
        headers, url = self._prepare(params=params)
        try:
            return self._process(fct(url=url.format(api), headers=headers, verify=self._verify, timeout=timeout, **kwargs))
        except HttpForbiddenException:
            if self._volatile_client is not None:
                self._volatile_client.delete(self._key)
            if first_connect is True:  # First connect, so no token was present yet, so no need to try twice without token
                raise
            self._token = None
            headers, url = self._prepare(params=params)
            return self._process(fct(url=url.format(api), headers=headers, verify=self._verify, **kwargs))
        except Exception:
            if self._volatile_client is not None:
                self._volatile_client.delete(self._key)
            raise

    @classmethod
    def get_instance(cls, connection_info, cache_store=None, version=6):
        """
        Retrieve an OVSClient instance to the connection information passed
        :param connection_info: Connection information, includes: 'host', 'port', 'client_id', 'client_secret'
        :type connection_info: dict
        :param cache_store: Store in which to keep the generated token for the client
        :type cache_store: object
        :param version: Version for the API
        :type version: int
        :return: An instance of the OVSClient class
        :rtype: ovs_extensions.api.client.OVSClient
        """
        ExtensionsToolbox.verify_required_params(actual_params=connection_info,
                                                 required_params={'host': (str, ExtensionsToolbox.regex_ip),
                                                                  'port': (int, {'min': 1, 'max': 65535}),
                                                                  'client_id': (str, None),
                                                                  'client_secret': (str, None),
                                                                  'local': (bool, None, False)})
        return cls(ip=connection_info['host'],
                   port=connection_info['port'],
                   credentials=(connection_info['client_id'], connection_info['client_secret']),
                   version=version,
                   cache_store=cache_store)

    def get(self, api, params=None):
        """
        Executes a GET call
        :param api: Specification to fill out in the URL, eg: /vpools/<vpool_guid>/shrink_vpool
        :param params: Additional query parameters as comma separated list, eg: {'contents':'dynamic1,dynamic2,-dynamic3,_relations,-relation1'}
        :type params: dict
        """
        return self._call(api=api, params=params, fct=requests.get)

    def post(self, api, data=None, params=None):
        """
        Executes a POST call
        :param api: Specification to fill out in the URL, eg: /vpools/<vpool_guid>/shrink_vpool
        :param data: Data to post
        :param params: Additional query parameters, eg: _dynamics
        """
        return self._call(api=api, params=params, fct=requests.post, data=data)

    def put(self, api, data=None, params=None):
        """
        Executes a PUT call
        :param api: Specification to fill out in the URL, eg: /vpools/<vpool_guid>/shrink_vpool
        :param data: Data to put
        :param params: Additional query parameters, eg: _dynamics
        """
        return self._call(api=api, params=params, fct=requests.put, data=data)

    def patch(self, api, data=None, params=None):
        """
        Executes a PATCH call
        :param api: Specification to fill out in the URL, eg: /vpools/<vpool_guid>/shrink_vpool
        :param data: Data to patch
        :param params: Additional query parameters, eg: _dynamics
        """
        return self._call(api=api, params=params, fct=requests.patch, data=data)

    def delete(self, api, params=None):
        """
        Executes a DELETE call
        :param api: Specification to fill out in the URL, eg: /vpools/<vpool_guid>/
        :param params: Additional query parameters, eg: _dynamics
        """
        return self._call(api=api, params=params, fct=requests.delete)
