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

import cinder_backup_contexts as contexts

from test_utils import (
    CharmTestCase
)

TO_PATCH = [
    'is_relation_made',
    'service_name',
    'get_os_codename_package'
]


class TestCinderBackupContext(CharmTestCase):

    def setUp(self):
        super(TestCinderBackupContext, self).setUp(contexts, TO_PATCH)

    def test_backup_context(self):
        self.get_os_codename_package.return_value = 'icehouse'
        self.service_name.return_value = 'cinder-backup-ut'
        ctxt = contexts.CephBackupSubordinateContext()()
        exp = {'cinder': {'/etc/cinder/cinder.conf':
                          {'sections': {'DEFAULT':
                                        [('backup_driver',
                                          'cinder.backup.drivers.ceph'),
                                         ('backup_ceph_conf',
                                          '/var/lib/charm/'
                                          'cinder-backup-ut/ceph.conf'),
                                         ('backup_ceph_pool',
                                          'cinder-backup-ut'),
                                         ('backup_ceph_user',
                                          'cinder-backup-ut')]}}}}
        self.assertEqual(ctxt, exp)
        self.get_os_codename_package.return_value = 'stein'
        exp = {'cinder': {'/etc/cinder/cinder.conf':
                          {'sections': {'DEFAULT':
                                        [('backup_driver',
                                          'cinder.backup.drivers.ceph.'
                                          'CephBackupDriver'),
                                         ('backup_ceph_conf',
                                          '/var/lib/charm/'
                                          'cinder-backup-ut/ceph.conf'),
                                         ('backup_ceph_pool',
                                          'cinder-backup-ut'),
                                         ('backup_ceph_user',
                                          'cinder-backup-ut')]}}}}
        self.assertEqual(contexts.CephBackupSubordinateContext()(), exp)

    def test_backup_context_unsupported(self):
        self.get_os_codename_package.return_value = 'havana'
        self.assertRaises(Exception, contexts.CephBackupSubordinateContext())
