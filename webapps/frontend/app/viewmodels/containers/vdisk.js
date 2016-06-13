// Copyright (C) 2016 iNuron NV
//
// This file is part of Open vStorage Open Source Edition (OSE),
// as available from
//
//      http://www.openvstorage.org and
//      http://www.openvstorage.com.
//
// This file is free software; you can redistribute it and/or modify it
// under the terms of the GNU Affero General Public License v3 (GNU AGPLv3)
// as published by the Free Software Foundation, in version 3 as it comes
// in the LICENSE.txt file of the Open vStorage OSE distribution.
//
// Open vStorage is distributed in the hope that it will be useful,
// but WITHOUT ANY WARRANTY of any kind.
/*global define */
define([
    'jquery', 'knockout',
    'ovs/generic', 'ovs/api', 'ovs/shared'
], function($, ko, generic, api, shared) {
    "use strict";
    return function(guid) {
        var self = this;

        // Variables
        self.shared = shared;

        // Handles
        self.loadHandle              = undefined;
        self.loadConfig              = undefined;
        self.loadParentConfig        = undefined;
        self.loadStorageRouterHandle = undefined;

        // External dependencies
        self.dtlTargets    = ko.observableArray([]);
        self.storageRouter = ko.observable();
        self.vMachine      = ko.observable();
        self.vpool         = ko.observable();

        // Observables
        self.backendRead         = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatBytes });
        self.backendWritten      = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatBytes });
        self.bandwidthSaved      = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatBytes });
        self.cacheHits           = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.cacheMisses         = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.cacheStrategies     = ko.observableArray(['on_read', 'on_write', 'none']);
        self.cacheStrategy       = ko.observable('on_read');
        self.dedupeMode          = ko.observable();
        self.dedupeModes         = ko.observableArray([{name: 'dedupe', disabled: false}, {name: 'non_dedupe', disabled: false}]);
        self.dtlEnabled          = ko.observable(true);
        self.dtlMode             = ko.observable();
        self.dtlStatus           = ko.observable();
        self.dtlTarget           = ko.observableArray([]);
        self.guid                = ko.observable(guid);
        self.iops                = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.loaded              = ko.observable(false);
        self.loading             = ko.observable(false);
        self.loadingConfig       = ko.observable(false);
        self.name                = ko.observable();
        self.namespace           = ko.observable();
        self.oldConfiguration    = ko.observable();
        self.order               = ko.observable(0);
        self.parentConfiguration = ko.observable();
        self.readCacheLimit      = ko.observable().extend({numeric: {min: 1, max: 10240, allowUndefined: true}});
        self.readSpeed           = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatSpeed });
        self.scoSize             = ko.observable(4);
        self.scoSizes            = ko.observableArray([4, 8, 16, 32, 64, 128]);
        self.size                = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatBytes });
        self.snapshots           = ko.observableArray([]);
        self.storageRouterGuid   = ko.observable();
        self.storedData          = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatBytes });
        self.totalCacheHits      = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatNumber });
        self.vMachineGuid        = ko.observable();
        self.vpoolGuid           = ko.observable();
        self.writeSpeed          = ko.observable().extend({ smooth: {} }).extend({ format: generic.formatSpeed });
        self.writeBuffer         = ko.observable(128).extend({numeric: {min: 128, max: 10240}});

        // Computed
        self.cacheRatio = ko.computed(function() {
            if (self.cacheHits() === undefined || self.cacheMisses() === undefined) {
                return undefined;
            }
            var total = (self.cacheHits.raw() || 0) + (self.cacheMisses.raw() || 0);
            if (total === 0) {
                total = 1;
            }
            return generic.formatRatio((self.cacheHits.raw() || 0) / total * 100);
        });
        self.dtlModes = ko.computed(function() {
            return [
                {name: 'no_sync', disabled: false},
                {name: 'a_sync', disabled: self.dtlTargets().length === 0},
                {name: 'sync', disabled: self.dtlTargets().length === 0}
            ];
        });
        self.dtlModeChange = ko.computed({
            read: function() {
                if (self.dtlTargets().length === 0) {
                    self.dtlMode('no_sync');
                    return {name: self.dtlMode(), disabled: true};
                }
                return {name: self.dtlMode(), disabled: false};
            },
            write: function(mode) {
                if (mode === 'no_sync') {
                    self.dtlEnabled(false);
                    self.dtlTarget([]);
                } else {
                    self.dtlEnabled(true);
                    if (self.dtlTargets().length === 0) {
                        self.dtlTarget([]);
                        $.each(self.dtlModes(), function(index, item) {
                            item.disabled = true;
                        })
                    } else if (self.dtlTarget().length === 0) {
                        self.dtlTarget([self.dtlTargets()[0]]);
                    }
                }
                self.dtlMode(mode.name);
            }
        });
        self.configuration = ko.computed({
            read: function() {
                var targets = self.dtlTarget().slice();
                targets.sort();
                return {
                    sco_size: self.scoSize(),
                    dtl_mode: self.dtlMode(),
                    dedupe_mode: self.dedupeMode() !== undefined ? self.dedupeMode().name : undefined,
                    write_buffer: self.writeBuffer(),
                    dtl_target: targets,
                    cache_strategy: self.cacheStrategy(),
                    readcache_limit: self.readCacheLimit() || null
                }
            },
            write: function(configData) {
                self.writeBuffer(Math.round(configData.write_buffer));
                self.scoSize(configData.sco_size);
                self.dtlMode(configData.dtl_mode);
                self.dedupeMode({name: configData.dedupe_mode, disabled: false});
                self.dtlTarget(configData.dtl_target.slice());
                self.cacheStrategy(configData.cache_strategy);
                self.readCacheLimit(configData.readcache_limit);
            }
        });
        self.scoSize.subscribe(function(size) {
            if (size < 128) {
                self.writeBuffer.min = 128;
            } else {
                self.writeBuffer.min = 256;
            }
            self.writeBuffer(self.writeBuffer());
        });
        self.configChanged = ko.computed(function() {
            var changed = false;
            if (self.oldConfiguration() !== undefined) {
                $.each(self.oldConfiguration(), function (key, _) {
                    if (!self.configuration().hasOwnProperty(key)) {
                        changed = true;
                        return false;
                    }
                    if ((self.configuration()[key] instanceof Array && !self.configuration()[key].equals(self.oldConfiguration()[key])) ||
                        (!(self.configuration()[key] instanceof Array) && self.configuration()[key] !== self.oldConfiguration()[key])) {
                        changed = true;
                        return false;
                    }
                });
            }
            return changed;
        });

        // Functions
        self.fillData = function(data) {
            generic.trySet(self.name, data, 'name');
            generic.trySet(self.order, data, 'order');
            if (data.hasOwnProperty('snapshots')) {
                var snapshots = [];
                $.each(data.snapshots, function(index, snapshot) {
                    if (snapshot.in_backend) {
                        snapshots.push(snapshot);
                    }
                });
                self.snapshots(snapshots);
            }
            generic.trySet(self.size, data, 'size');
            generic.trySet(self.vpoolGuid, data, 'vpool_guid');
            generic.trySet(self.vMachineGuid, data, 'vmachine_guid');
            generic.trySet(self.storageRouterGuid, data, 'storagerouter_guid');
            if (data.hasOwnProperty('info')) {
                self.storedData(data.info.stored);
                self.dtlStatus(data.info.failover_mode.toLowerCase() || 'unknown');
                self.namespace(data.info.namespace);
            }
            if (data.hasOwnProperty('statistics')) {
                var stats = data.statistics;
                self.iops(stats['4k_operations_ps']);
                self.cacheHits(stats.cache_hits_ps);
                self.cacheMisses(stats.cache_misses_ps);
                self.totalCacheHits(stats.cache_hits);
                self.readSpeed(stats.data_read_ps);
                self.writeSpeed(stats.data_written_ps);
                self.backendWritten(stats.backend_data_written);
                self.backendRead(stats.backend_data_read);
                self.bandwidthSaved(Math.max(0, stats.data_read - stats.backend_data_read));
            }

            self.snapshots.sort(function(a, b) {
                // Sorting based on newest first
                return b.timestamp - a.timestamp;
            });

            self.loaded(true);
            self.loading(false);
        };
        self.load = function() {
            return $.Deferred(function(deferred) {
                self.loading(true);
                if (generic.xhrCompleted(self.loadHandle)) {
                    self.loadHandle = api.get('vdisks/' + self.guid())
                        .done(function(data) {
                            self.fillData(data);
                            deferred.resolve();
                        })
                        .fail(deferred.reject)
                        .always(function() {
                            self.loading(false);
                        });
                } else {
                    deferred.reject();
                }
            }).promise();
        };
        self.loadAllConfigurations = function() {
            self.loadingConfig(true);
            return $.Deferred(function (deferred) {
                self.loadParentConfiguration()
                    .then(function() {
                        return self.loadConfiguration(false);
                    })
                    .always(function() {
                        self.loadingConfig(false);
                        deferred.resolve();
                    });
            }).promise();
        };
        self.loadParentConfiguration = function() {
            return $.Deferred(function(deferred) {
                self.loadParentConfig = api.get('vpools/' + self.vpoolGuid() + '/get_configuration')
                    .then(self.shared.tasks.wait)
                    .done(function(data) {
                        if (self.parentConfiguration() === undefined) {
                            self.parentConfiguration(data);
                        }
                        deferred.resolve();
                    })
                    .fail(deferred.reject);
            }).promise();
        };
        self.loadConfiguration = function(reload) {
            return $.Deferred(function(deferred) {
                self.loadConfig = api.get('vdisks/' + self.guid() + '/get_config_params')
                    .then(self.shared.tasks.wait)
                    .done(function(data) {
                        if (data.hasOwnProperty('metadata_cache_size')) {
                            delete data['metadata_cache_size'];
                        }
                        self.dtlEnabled(data.dtl_mode !== 'no_sync');
                        if (data.dedupe_mode !== undefined && data.dedupe_mode === 'non_dedupe') {
                            $.each(self.dedupeModes(), function (i, key) {
                                if (key.name === 'dedupe') {
                                    self.dedupeModes()[i].disabled = true;
                                    return false;
                                }
                            });
                        }
                        self.configuration(data);
                        data = self.configuration(); // Pass through the getter/setter for possible cleanups
                        if (self.oldConfiguration() === undefined || reload === true) {
                            self.oldConfiguration($.extend({}, data)); // Used to make comparison to check for changes
                            $.each(self.oldConfiguration(), function (key, _) {
                                if (key === 'write_buffer') {
                                    var oldConfig = self.oldConfiguration();
                                    oldConfig.write_buffer = Math.round(self.oldConfiguration().write_buffer);
                                    self.oldConfiguration(oldConfig);
                                }
                            });
                        }
                        deferred.resolve();
                    })
                    .fail(deferred.reject);
            }).promise();
        };
    };
});
