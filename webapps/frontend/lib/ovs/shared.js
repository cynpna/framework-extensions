// Copyright 2016 iNuron NV
//
// Licensed under the Apache License, Version 2.0 (the "License");
// you may not use this file except in compliance with the License.
// You may obtain a copy of the License at
//
//     http://www.apache.org/licenses/LICENSE-2.0
//
// Unless required by applicable law or agreed to in writing, software
// distributed under the License is distributed on an "AS IS" BASIS,
// WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
// See the License for the specific language governing permissions and
// limitations under the License.
/*global define */
define(['knockout'], function(ko){
    "use strict";
    var singleton = function() {
        return {
            messaging      : undefined,
            tasks          : undefined,
            authentication : undefined,
            registration   : ko.observable({
                registered: false,
                remaining: null
            }),
            defaultLanguage: 'en-US',
            language       : 'en-US',
            mode           : ko.observable('full'),
            routing        : undefined,
            footerData     : ko.observable(ko.observable()),
            nodes          : undefined,
            identification : ko.observable(),
            user           : {
                username: ko.observable(),
                guid    : ko.observable(),
                roles   : ko.observableArray([])
            },
            hooks          : {
                dashboards: []
            }
        };
    };
    return singleton();
});
