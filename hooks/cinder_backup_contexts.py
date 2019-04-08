# Copyright 2016 Canonical Ltd
#
# Licensed under the Apache License, Version 2.0 (the "License");
# you may not use this file except in compliance with the License.
# You may obtain a copy of the License at
#
#  http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.

import os

from charmhelpers.core.hookenv import (
    service_name,
    is_relation_made,
)
from charmhelpers.contrib.openstack.context import (
    OSContextGenerator,
)
from charmhelpers.contrib.openstack.utils import (
    get_os_codename_package,
    CompareOpenStackReleases,
)


class CephBackupSubordinateContext(OSContextGenerator):
    interfaces = ['ceph-cinder']

    def __call__(self):
        """Used to generate template context to be added to cinder.conf in the
        presence of a ceph relation.
        """
        if not is_relation_made('ceph', 'key'):
            return {}

        release = get_os_codename_package('cinder-common')
        if CompareOpenStackReleases(release) < "icehouse":
            raise Exception("Unsupported version of Openstack")

        service = service_name()
        if CompareOpenStackReleases(release) >= "stein":
            backup_driver = 'cinder.backup.drivers.ceph.CephBackupDriver'
        else:
            backup_driver = 'cinder.backup.drivers.ceph'
        return {
            "cinder": {
                "/etc/cinder/cinder.conf": {
                    "sections": {
                        'DEFAULT': [
                            ('backup_driver', backup_driver),
                            ('backup_ceph_conf',
                                os.path.join('/var/lib/charm',
                                             service, 'ceph.conf')),
                            ('backup_ceph_pool', service),
                            ('backup_ceph_user', service),
                        ]
                    }
                }
            }
        }
