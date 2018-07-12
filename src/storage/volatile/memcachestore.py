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
Memcache store module
"""

import re
import ujson
import memcache
from functools import wraps
from threading import Lock


def locked():
    """
    Locking decorator.
    """
    def wrap(f):
        """
        Returns a wrapped function
        """
        @wraps(f)
        def new_function(self, *args, **kwargs):
            """
            Executes the decorated function in a locked context
            """
            lock = kwargs.get('lock', True)
            if 'lock' in kwargs:
                del kwargs['lock']
            if lock:
                with self._lock:
                    return f(self, *args, **kwargs)
            else:
                return f(self, *args, **kwargs)
        return new_function
    return wrap


class MemcacheStore(object):
    """
    Memcache client wrapper:
    * stringifies the keys
    """

    COMPRESSION_THRESHOLD = 1 * 1024 * 1024

    def __init__(self, nodes):
        """
        Initializes the client
        """
        self._nodes = nodes
        self._client = memcache.Client(self._nodes, cache_cas=True, socket_timeout=0.5)
        self._lock = Lock()
        self._validate = True

    def _get(self, action, key, default=None):
        """
        Retrieves a certain value for a given key (get or gets)
        """
        key = MemcacheStore._clean_key(key)
        if action == 'get':
            data = self._client.get(key)
        else:
            data = self._client.gets(key)
        if data is None:
            # Cache miss
            return default
        data = ujson.loads(data)
        if self._validate:
            if data['key'] == key:
                return data['value']
            error = 'Invalid data received'
            raise RuntimeError(error)
        else:
            return data

    @locked()
    def get(self, key, default=None):
        """
        Retrieves a certain value for a given key (get)
        """
        return self._get('get', key, default=default)

    @locked()
    def gets(self, key, default=None):
        """
        Retrieves a certain value for a given key (gets)
        """
        return self._get('gets', key, default=default)

    def _set(self, action, key, value, time=0):
        """
        Sets the value for a key to a given value
        """
        key = MemcacheStore._clean_key(key)
        if self._validate:
            data = {'value': value,
                    'key': key}
        else:
            data = value
        data = ujson.dumps(data)
        if action == 'set':
            return self._client.set(key, data, time, min_compress_len=MemcacheStore.COMPRESSION_THRESHOLD)
        return self._client.cas(key, data, time, min_compress_len=MemcacheStore.COMPRESSION_THRESHOLD)

    @locked()
    def set(self, key, value, time=0):
        """
        Sets the value for a key to a given value (set)
        """
        return self._set('set', key, value, time=time)

    @locked()
    def cas(self, key, value, time=0):
        """
        Sets the value for a key to a given value (cas)
        """
        return self._set('cas', key, value, time=time)

    @locked()
    def add(self, key, value, time=0):
        """
        Adds a given key to the store, expecting the key does not exists yet
        """
        key = MemcacheStore._clean_key(key)
        if self._validate:
            data = {'value': value,
                    'key': key}
        else:
            data = value
        data = ujson.dumps(data)
        return self._client.add(key, data, time)

    @locked()
    def incr(self, key, delta=1):
        """
        Increments the value of the key, expecting it exists
        """
        if self._validate:
            value = self.get(key, lock=False)
            if value is not None:
                value += delta
            else:
                value = 1
            self.set(key, value, 60, lock=False)
            return True
        else:
            return self._client.incr(MemcacheStore._clean_key(key), delta)

    @locked()
    def delete(self, key):
        """
        Deletes a given key from the store
        """
        return self._client.delete(MemcacheStore._clean_key(key))

    @staticmethod
    def _clean_key(key):
        return re.sub('[^\x21-\x7e\x80-\xff]', '', str(key))
