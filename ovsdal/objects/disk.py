from ovsdal.dataobject import DataObject


class Disk(DataObject):
    _name = 'disk'  # Name of this object
    _blueprint = {'name'             : None,  # All persistent stored fields, with default value
                  'description'      : 'Test disk',
                  'size'             : 0,
                  'parentdiskid'     : None,
                  'storagepoolid'    : None,
                  'volumedriverid'   : 1,
                  'machineid'        : 1,
                  'pmachineid'       : 3,
                  'status'           : 'ATTACHED',
                  'type'             : 'DSSVOL',
                  'serialnr'         : 'ADEF194FDE',
                  'retentionpolicyid': None,
                  'snapshotpolicyid' : None,
                  'devicename'       : '123456789.vmdk',
                  'tags'             : None,
                  'replicationguid'  : None,
                  'environmentguid'  : None,
                  'cloudspaceguid'   : None,
                  'autobackup'       : False}
    _objectexpiry = 300  # Timeout in seconds of the main object cache
    _expiry = {'used_size': 5,  # Timeout in seconds of individual RO properties
               'snapshots': 10}

    @property
    def used_size(self):
        def get_data():
            # Simulate fetching real data
            from random import randint
            return randint(0, self._data['size'])
        return self._backend_property(get_data)

    @property
    def snapshots(self):
        def get_data():
            # Simulate fetching real data
            from random import randint
            snapshots = []
            for i in xrange(0, randint(0, 10)):
                snapshots.append({'consistent': randint(0, 1) == 1, 'id': i})
            return snapshots
        return self._backend_property(get_data)
