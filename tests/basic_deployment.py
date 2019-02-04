#!/usr/bin/env python
#
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

""" Basic cinder-backup functional test. """
import amulet
import json
import time

from charmhelpers.contrib.openstack.amulet.deployment import (
    OpenStackAmuletDeployment
)

from charmhelpers.contrib.openstack.amulet.utils import (
    OpenStackAmuletUtils,
    DEBUG,
)

# Use DEBUG to turn on debug logging
u = OpenStackAmuletUtils(DEBUG)


class CinderBackupBasicDeployment(OpenStackAmuletDeployment):
    """Amulet tests on a basic cinder-backup deployment."""

    def __init__(self, series=None, openstack=None, source=None, git=False,
                 stable=False):
        """Deploy the entire test environment."""
        super(CinderBackupBasicDeployment, self).__init__(series, openstack,
                                                          source, stable)
        self.git = git
        self._add_services()
        self._add_relations()
        self._configure_services()
        self._deploy()

        u.log.info('Waiting on extended status checks...')

        # XXX: cinder-backup workload status ignored until it grows support
        #      https://bugs.launchpad.net/bugs/1604580
        exclude_services = ['cinder-backup']
        self._auto_wait_for_status(exclude_services=exclude_services)

        self.d.sentry.wait()
        self._initialize_tests()

    def _add_services(self):
        """Add the services that we're testing, where cinder-backup is
        local, and the rest of the services are from lp branches that
        are compatible with the local charm (e.g. stable or next).
        """
        # Note: cinder-backup becomes a cinder subordinate unit.
        this_service = {'name': 'cinder-backup'}
        other_services = [
            {'name': 'percona-cluster'},
            {'name': 'keystone'},
            {'name': 'rabbitmq-server'},
            {'name': 'ceph-mon', 'units': 3},
            {'name': 'ceph-osd', 'units': 3,
             'storage': {'osd-devices': 'cinder,10G'}},
            {'name': 'cinder'},
            {'name': 'cinder-ceph'},
        ]
        super(CinderBackupBasicDeployment, self)._add_services(this_service,
                                                               other_services)

    def _add_relations(self):
        """Add all of the relations for the services."""

        relations = {
            'cinder-backup:ceph': 'ceph-mon:client',
            'cinder-ceph:ceph': 'ceph-mon:client',
            'ceph-osd:mon': 'ceph-mon:osd',
            'cinder:storage-backend': 'cinder-ceph:storage-backend',
            'cinder:backup-backend': 'cinder-backup:backup-backend',
            'keystone:shared-db': 'percona-cluster:shared-db',
            'cinder:shared-db': 'percona-cluster:shared-db',
            'cinder:identity-service': 'keystone:identity-service',
            'cinder:amqp': 'rabbitmq-server:amqp',
        }
        super(CinderBackupBasicDeployment, self)._add_relations(relations)

    def _configure_services(self):
        """Configure all of the services."""
        keystone_config = {
            'admin-password': 'openstack',
            'admin-token': 'ubuntutesting'
        }
        pxc_config = {
            'innodb-buffer-pool-size': '256M',
            'max-connections': 1000,
        }
        cinder_config = {
            'block-device': 'None',
            'glance-api-version': '2'
        }
        ceph_config = {
            'monitor-count': '3',
            'auth-supported': 'none',
        }

        cinder_ceph_config = {
            'ceph-osd-replication-count': '3',
        }
        configs = {
            'keystone': keystone_config,
            'percona-cluster': pxc_config,
            'cinder': cinder_config,
            'ceph-mon': ceph_config,
            'cinder-ceph': cinder_ceph_config,
            'cinder-backup': cinder_ceph_config,
        }
        super(CinderBackupBasicDeployment, self)._configure_services(configs)

    def _initialize_tests(self):
        """Perform final initialization before tests get run."""
        # Access the sentries for inspecting service units
        self.pxc_sentry = self.d.sentry['percona-cluster'][0]
        self.keystone_sentry = self.d.sentry['keystone'][0]
        self.rabbitmq_sentry = self.d.sentry['rabbitmq-server'][0]
        self.cinder_sentry = self.d.sentry['cinder'][0]
        self.ceph0_sentry = self.d.sentry['ceph-mon'][0]
        self.ceph1_sentry = self.d.sentry['ceph-mon'][1]
        self.ceph2_sentry = self.d.sentry['ceph-mon'][2]
        self.ceph_osd0_sentry = self.d.sentry['ceph-osd'][0]
        self.ceph_osd1_sentry = self.d.sentry['ceph-osd'][1]
        self.ceph_osd2_sentry = self.d.sentry['ceph-osd'][2]
        self.cinder_backup_sentry = self.d.sentry['cinder-backup'][0]
        u.log.debug('openstack release val: {}'.format(
            self._get_openstack_release()))
        u.log.debug('openstack release str: {}'.format(
            self._get_openstack_release_string()))

        # Authenticate admin with keystone
        self.keystone_session, self.keystone = u.get_default_keystone_session(
            self.keystone_sentry,
            openstack_release=self._get_openstack_release())

        # Authenticate admin with cinder endpoint
        if self._get_openstack_release() >= self.xenial_pike:
            api_version = 2
        else:
            api_version = 1
        self.cinder = u.authenticate_cinder_admin(self.keystone, api_version)

    def test_102_services(self):
        """Verify the expected services are running on the service units."""
        if self._get_openstack_release() >= self.xenial_ocata:
            cinder_services = ['apache2',
                               'cinder-scheduler',
                               'cinder-volume']
        else:
            cinder_services = ['cinder-api',
                               'cinder-scheduler',
                               'cinder-volume']
        services = {
            self.cinder_sentry: cinder_services,
        }

        ret = u.validate_services_by_name(services)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_112_service_catalog(self):
        """Verify that the service catalog endpoint data"""
        u.log.debug('Checking keystone service catalog...')
        endpoint_vol = {'adminURL': u.valid_url,
                        'region': 'RegionOne',
                        'publicURL': u.valid_url,
                        'internalURL': u.valid_url}
        endpoint_id = {'adminURL': u.valid_url,
                       'region': 'RegionOne',
                       'publicURL': u.valid_url,
                       'internalURL': u.valid_url}
        if self._get_openstack_release() >= self.trusty_icehouse:
            endpoint_vol['id'] = u.not_null
            endpoint_id['id'] = u.not_null

        if self._get_openstack_release() >= self.xenial_pike:
            # Pike and later
            expected = {'identity': [endpoint_id],
                        'volumev2': [endpoint_id]}
        else:
            # Ocata and prior
            expected = {'identity': [endpoint_id],
                        'volume': [endpoint_id]}
        actual = self.keystone.service_catalog.get_endpoints()

        ret = u.validate_svc_catalog_endpoint_data(
            expected,
            actual,
            openstack_release=self._get_openstack_release())
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

    def test_114_cinder_endpoint(self):
        """Verify the cinder endpoint data."""
        u.log.debug('Checking cinder endpoint...')
        endpoints = self.keystone.endpoints.list()
        admin_port = internal_port = public_port = '8776'
        if self._get_openstack_release() >= self.xenial_queens:
            expected = {
                'id': u.not_null,
                'region': 'RegionOne',
                'region_id': 'RegionOne',
                'url': u.valid_url,
                'interface': u.not_null,
                'service_id': u.not_null}
            ret = u.validate_v3_endpoint_data(
                endpoints,
                admin_port,
                internal_port,
                public_port,
                expected,
                6)
        else:
            expected = {
                'id': u.not_null,
                'region': 'RegionOne',
                'adminurl': u.valid_url,
                'internalurl': u.valid_url,
                'publicurl': u.valid_url,
                'service_id': u.not_null}
            ret = u.validate_v2_endpoint_data(
                endpoints,
                admin_port,
                internal_port,
                public_port,
                expected)
        if ret:
            amulet.raise_status(amulet.FAIL,
                                msg='cinder endpoint: {}'.format(ret))

    def validate_broker_req(self, unit, relation, expected):
        rel_data = json.loads(unit.relation(
            relation[0],
            relation[1])['broker_req'])
        if rel_data['api-version'] != expected['api-version']:
            return "Broker request api mismatch"
        for index in range(0, len(rel_data['ops'])):
            actual_op = rel_data['ops'][index]
            expected_op = expected['ops'][index]
            for key in ['op', 'name', 'replicas']:
                if actual_op[key] == expected_op[key]:
                    u.log.debug("OK op {} key {}".format(index, key))
                else:
                    return "Mismatch, op: {} key: {}".format(index, key)
        return None

    def get_broker_request(self):
        client_unit = self.cinder_backup_sentry
        broker_req = json.loads(client_unit.relation(
            'ceph',
            'ceph-mon:client')['broker_req'])
        return broker_req

    def get_broker_response(self):
        broker_request = self.get_broker_request()
        u.log.debug('Broker request: {}'.format(broker_request))

        response_key = "broker-rsp-{}-{}".format(
            self.cinder_backup_sentry.info['service'],
            self.cinder_backup_sentry.info['unit']
        )
        u.log.debug('Checking response_key: {}'.format(response_key))

        ceph_sentrys = [self.ceph0_sentry,
                        self.ceph1_sentry,
                        self.ceph2_sentry]
        for sentry in ceph_sentrys:
            relation_data = sentry.relation('client', 'cinder-backup:ceph')
            if relation_data.get(response_key):
                broker_response = json.loads(relation_data[response_key])
                if (broker_request['request-id'] ==
                        broker_response['request-id']):
                    u.log.debug('broker_response: {}'.format(broker_response))
                    return broker_response

    def test_200_cinderbackup_ceph_ceph_relation(self):
        u.log.debug('Checking cinder-backup:ceph to ceph:client '
                    'relation data...')
        unit = self.cinder_backup_sentry
        relation = ['ceph', 'ceph-mon:client']

        req = {
            "api-version": 1,
            "ops": [{"replicas": 3,
                     "name": "cinder-backup",
                     "op": "create-pool"}]
        }
        expected = {
            'private-address': u.valid_ip,
            'broker_req': u.not_null,
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder-backup ceph-mon', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)
        ret = self.validate_broker_req(unit, relation, req)
        if ret:
            msg = u.relation_error('cinder-backup ceph-mon', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_201_ceph_cinderbackup_ceph_relation(self):
        u.log.debug('Checking ceph-mon:client to cinder-backup:ceph '
                    'relation data...')
        ceph_unit = self.ceph0_sentry
        relation = ['client', 'cinder-backup:ceph']
        expected = {
            'key': u.not_null,
            'private-address': u.valid_ip,
            'ceph-public-address': u.valid_ip,
            'auth': 'none',
        }
        ret = u.validate_relation_data(ceph_unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder cinder-backup backup-backend', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_202_cinderbackup_cinder_backend_relation(self):
        u.log.debug('Checking cinder-backup:backup-backend to '
                    'cinder:backup-backend relation data...')
        unit = self.cinder_backup_sentry
        relation = ['backup-backend', 'cinder:backup-backend']

        sub = ('{"cinder": {"/etc/cinder/cinder.conf": {"sections": '
               '{"DEFAULT": ['
               '["backup_driver", "cinder.backup.drivers.ceph"], '
               '["backup_ceph_conf", '
               '"/var/lib/charm/cinder-backup/ceph.conf"], '
               '["backup_ceph_pool", "cinder-backup"], '
               '["backup_ceph_user", "cinder-backup"]]}}}}')
        expected = {
            'subordinate_configuration': sub,
            'private-address': u.valid_ip,
            'backend_name': 'cinder-backup'
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder cinder-backup backup-backend', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_203_cinder_cinderbackup_backend_relation(self):
        u.log.debug('Checking cinder:backup-backend to '
                    'cinder-backup:backup-backend relation data...')
        unit = self.cinder_sentry
        relation = ['backup-backend', 'cinder-backup:backup-backend']

        expected = {
            'private-address': u.valid_ip,
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder cinder-backup backup-backend', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_204_mysql_cinder_db_relation(self):
        """Verify the mysql:glance shared-db relation data"""
        u.log.debug('Checking mysql:cinder db relation data...')
        unit = self.pxc_sentry
        relation = ['shared-db', 'cinder:shared-db']
        expected = {
            'private-address': u.valid_ip,
            'db_host': u.valid_ip
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('mysql shared-db', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_205_cinder_mysql_db_relation(self):
        """Verify the cinder:mysql shared-db relation data"""
        u.log.debug('Checking cinder:mysql db relation data...')
        unit = self.cinder_sentry
        relation = ['shared-db', 'percona-cluster:shared-db']
        expected = {
            'private-address': u.valid_ip,
            'hostname': u.valid_ip,
            'username': 'cinder',
            'database': 'cinder'
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder shared-db', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_206_keystone_cinder_id_relation(self):
        """Verify the keystone:cinder identity-service relation data"""
        u.log.debug('Checking keystone:cinder id relation data...')
        unit = self.keystone_sentry
        relation = ['identity-service',
                    'cinder:identity-service']
        expected = {
            'service_protocol': 'http',
            'service_tenant': 'services',
            'admin_token': 'ubuntutesting',
            'service_password': u.not_null,
            'service_port': '5000',
            'auth_port': '35357',
            'auth_protocol': 'http',
            'private-address': u.valid_ip,
            'auth_host': u.valid_ip,
            'service_username': 'cinder_cinderv2',
            'service_tenant_id': u.not_null,
            'service_host': u.valid_ip
        }
        if self._get_openstack_release() >= self.xenial_pike:
            expected['service_username'] = 'cinderv2_cinderv3'
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('identity-service cinder', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_207_cinder_keystone_id_relation(self):
        """Verify the cinder:keystone identity-service relation data"""
        u.log.debug('Checking cinder:keystone id relation data...')
        unit = self.cinder_sentry
        relation = ['identity-service',
                    'keystone:identity-service']
        if self._get_openstack_release() < self.xenial_pike:
            expected = {
                'cinder_service': 'cinder',
                'cinder_region': 'RegionOne',
                'cinder_public_url': u.valid_url,
                'cinder_internal_url': u.valid_url,
                'cinder_admin_url': u.valid_url,
                'private-address': u.valid_ip
            }
        else:
            expected = {
                'cinderv2_service': 'cinderv2',
                'cinderv2_region': 'RegionOne',
                'cinderv2_public_url': u.valid_url,
                'cinderv2_internal_url': u.valid_url,
                'cinderv2_admin_url': u.valid_url,
                'cinderv3_service': 'cinderv3',
                'cinderv3_region': 'RegionOne',
                'cinderv3_public_url': u.valid_url,
                'cinderv3_internal_url': u.valid_url,
                'cinderv3_admin_url': u.valid_url,
                'private-address': u.valid_ip
            }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder identity-service', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_208_rabbitmq_cinder_amqp_relation(self):
        """Verify the rabbitmq-server:cinder amqp relation data"""
        u.log.debug('Checking rmq:cinder amqp relation data...')
        unit = self.rabbitmq_sentry
        relation = ['amqp', 'cinder:amqp']
        expected = {
            'private-address': u.valid_ip,
            'password': u.not_null,
            'hostname': u.valid_ip
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('amqp cinder', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_209_cinder_rabbitmq_amqp_relation(self):
        """Verify the cinder:rabbitmq-server amqp relation data"""
        u.log.debug('Checking cinder:rmq amqp relation data...')
        unit = self.cinder_sentry
        relation = ['amqp', 'rabbitmq-server:amqp']
        expected = {
            'private-address': u.valid_ip,
            'vhost': 'openstack',
            'username': u.not_null
        }
        ret = u.validate_relation_data(unit, relation, expected)
        if ret:
            msg = u.relation_error('cinder amqp', ret)
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_300_cinder_config(self):
        """Verify the data in the cinder.conf file."""
        u.log.debug('Checking cinder config file data...')
        unit = self.cinder_sentry
        conf = '/etc/cinder/cinder.conf'
        unit_mq = self.rabbitmq_sentry
        rel_mq_ci = unit_mq.relation('amqp', 'cinder:amqp')

        expected = {
            'DEFAULT': {
                'use_syslog': 'False',
                'debug': 'False',
                'verbose': 'False',
                'iscsi_helper': 'tgtadm',
                'volume_group': 'cinder-volumes',
                'auth_strategy': 'keystone',
                'volumes_dir': '/var/lib/cinder/volumes',
                'enabled_backends': 'cinder-ceph',
                'backup_driver': 'cinder.backup.drivers.ceph',
                'backup_ceph_pool': 'cinder-backup',
                'backup_ceph_user': 'cinder-backup'
            },
            'cinder-ceph': {
                'volume_backend_name': 'cinder-ceph',
                'volume_driver': 'cinder.volume.drivers.rbd.RBDDriver',
                'rbd_pool': 'cinder-ceph',
                'rbd_user': 'cinder-ceph'
            },
        }

        expected_rmq = {
            'rabbit_userid': 'cinder',
            'rabbit_virtual_host': 'openstack',
            'rabbit_password': rel_mq_ci['password'],
            'rabbit_host': rel_mq_ci['hostname'],
        }

        if self._get_openstack_release() >= self.trusty_kilo:
            # Kilo or later
            expected['oslo_messaging_rabbit'] = expected_rmq
        else:
            # Juno or earlier
            expected['DEFAULT'].update(expected_rmq)

        if self._get_openstack_release() >= self.xenial_ocata:
            expected['DEFAULT'].pop('volumes_dir')
            expected['DEFAULT'].pop('volume_group')
            expected['DEFAULT'].pop('enabled_backends')

        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "cinder config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_301_cinder_ceph_config(self):
        """Verify the data in the ceph.conf file."""
        u.log.debug('Checking cinder ceph config file data...')

        # NOTE(beisner): disabled pending lp#1468511 landing in the cinder
        # charm to resolve leading spaces in the ceph.conf template.  That
        # is necessary as configparser treats lines with leading spaces as
        # continuation lines, and this test fails.
        u.log.warn('Disabled due to bug lp 1468511')
        return

        unit = self.cinder_sentry
        conf = '/etc/ceph/ceph.conf'
        expected = {
            'global': {
                'auth_supported': 'none',
                'keyring': '/etc/ceph/$cluster.$name.keyring',
                'mon host': u.not_null,
                'log to syslog': 'false'
            }
        }
        for section, pairs in expected.iteritems():
            ret = u.validate_config_data(unit, conf, section, pairs)
            if ret:
                message = "cinder ceph config error: {}".format(ret)
                amulet.raise_status(amulet.FAIL, msg=message)

    def test_400_cinder_api_connection(self):
        """Simple api call to check service is up and responding"""
        u.log.debug('Checking basic cinder api functionality...')
        check = list(self.cinder.volumes.list())
        u.log.debug('Cinder api check (volumes.list): {}'.format(check))
        assert(check == [])

    def test_401_check_broker_reponse(self):
        u.log.debug('Checking broker response')
        broker_response = self.get_broker_response()
        if not broker_response or broker_response['exit-code'] != 0:
            msg = ('Broker request invalid'
                   ' or failed: {}'.format(broker_response))
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_402_create_delete_volume(self):
        """Create a cinder volume and delete it."""
        u.log.debug('Creating, checking and deleting cinder volume...')
        vol_new = u.create_cinder_volume(self.cinder)
        vol_id = vol_new.id
        u.delete_resource(self.cinder.volumes, vol_id, msg="cinder volume")

    def test_409_ceph_check_osd_pools(self):
        """Check osd pools on all ceph units, expect them to be
        identical, and expect specific pools to be present."""
        u.log.debug('Checking pools on ceph units...')

        expected_pools = self.get_ceph_expected_pools()

        # Override expected pools
        if 'glance' in expected_pools:
            expected_pools.remove('glance')

        if 'cinder' in expected_pools:
            expected_pools.remove('cinder')

        if 'cinder-backup' not in expected_pools:
            expected_pools.append('cinder-backup')

        if 'cinder-ceph' not in expected_pools:
            expected_pools.append('cinder-ceph')

        results = []
        sentries = [
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]

        # Check for presence of expected pools on each unit
        u.log.debug('Expected pools: {}'.format(expected_pools))
        for sentry_unit in sentries:
            pools = u.get_ceph_pools(sentry_unit)
            results.append(pools)

            for expected_pool in expected_pools:
                if expected_pool not in pools:
                    msg = ('{} does not have pool: '
                           '{}'.format(sentry_unit.info['unit_name'],
                                       expected_pool))
                    amulet.raise_status(amulet.FAIL, msg=msg)
            u.log.debug('{} has (at least) the expected '
                        'pools.'.format(sentry_unit.info['unit_name']))

        # Check that all units returned the same pool name:id data
        ret = u.validate_list_of_identical_dicts(results)
        if ret:
            u.log.debug('Pool list results: {}'.format(results))
            msg = ('{}; Pool list results are not identical on all '
                   'ceph units.'.format(ret))
            amulet.raise_status(amulet.FAIL, msg=msg)
        else:
            u.log.debug('Pool list on all ceph units produced the '
                        'same results (OK).')

    def backup_volume(self, cinder, volume, bak_name="demo-bak"):
        """Create cinder volume backup. Wait for the new backup status to reach
        the expected status, validate and return a resource pointer.

        :param volume: volume to be backed up
        :param bak_name: cinder volume backup display name
        :returns: cinder backup pointer
        """
        try:
            bak_new = cinder.backups.create(volume.id, name=bak_name)
            bak_id = bak_new.id
        except Exception as e:
            msg = 'Failed to create backup: {}'.format(e)
            amulet.raise_status(amulet.FAIL, msg=msg)

        # Wait for backup to reach available status
        ret = u.resource_reaches_status(cinder.backups, bak_id,
                                        expected_stat="available",
                                        msg="Backup status wait")

        if not ret:
            msg = 'Cinder backup failed to reach expected state.'
            amulet.raise_status(amulet.FAIL, msg=msg)

        return bak_new

    def restore_volume(self, cinder, backup):
        """Restore cinder volume from backup.

        :param backup: backup to restore from
        """
        try:
            cinder.restores.restore(backup.id)
        except Exception as e:
            msg = 'Failed to restore volume: {}'.format(e)
            amulet.raise_status(amulet.FAIL, msg=msg)

        # Wait for backup to reach available status
        ret = u.resource_reaches_status(cinder.backups, backup.id,
                                        expected_stat="available",
                                        msg="Backup status wait")

        if not ret:
            msg = 'Cinder backup failed to reach expected state.'
            amulet.raise_status(amulet.FAIL, msg=msg)

    def test_410_cinder_vol_create_backup_delete_restore_pool_inspect(self):
        """Create, backup, delete, restore a ceph-backed cinder volume, and
        inspect ceph cinder pool object count as the volume is created
        and deleted."""
        sentry_unit = self.ceph0_sentry
        obj_count_samples = []
        pool_size_samples = []
        pools = u.get_ceph_pools(self.ceph0_sentry)
        expected_pool = 'cinder-ceph'
        cinder_ceph_pool = pools[expected_pool]

        # Check ceph cinder pool object count, disk space usage and pool name
        u.log.debug('Checking ceph cinder pool original samples...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(
            sentry_unit, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        if pool_name != expected_pool:
            msg = ('Ceph pool {} unexpected name (actual, expected): '
                   '{}. {}'.format(cinder_ceph_pool,
                                   pool_name, expected_pool))
            amulet.raise_status(amulet.FAIL, msg=msg)

        # Create ceph-backed cinder volume
        cinder_vol = u.create_cinder_volume(self.cinder)
        # Backup the volume
        vol_backup = self.backup_volume(self.cinder, cinder_vol)
        # Delete the volume
        u.delete_resource(self.cinder.volumes, cinder_vol, msg="cinder volume")
        # Restore the volume
        self.restore_volume(self.cinder, vol_backup)
        # Delete the backup
        u.delete_resource(self.cinder.backups, vol_backup, msg="cinder backup")

        # Re-check ceph cinder pool object count and disk usage
        time.sleep(10)
        u.log.debug('Checking ceph cinder pool samples after volume create...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(
            sentry_unit, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        name = "demo-vol"
        vols = self.cinder.volumes.list()
        try:
            cinder_vols = [v for v in vols if v.name == name]
        except AttributeError:
            cinder_vols = [v for v in vols if v.display_name == name]
        if not cinder_vols:
            # NOTE(hopem): it appears that at some point cinder-backup stopped
            # restoring volume metadata properly so revert to default name if
            # original is not found
            name = "restore_backup_{}".format(vol_backup.id)
            try:
                cinder_vols = [v for v in vols if v.name == name]
            except AttributeError:
                cinder_vols = [v for v in vols if v.display_name == name]

        if not cinder_vols:
            try:
                msg = ("Could not find restore vol '{}' in {}"
                       .format(name, [v.name for v in vols]))
            except AttributeError:
                msg = ("Could not find restore vol '{}' in {}"
                       .format(name, [v.display_name for v in vols]))
            u.log.error(msg)
            amulet.raise_status(amulet.FAIL, msg=msg)

        cinder_vol = cinder_vols[0]

        # Delete restored cinder volume
        u.delete_resource(self.cinder.volumes, cinder_vol, msg="cinder volume")

        # Final check, ceph cinder pool object count and disk usage
        time.sleep(10)
        u.log.debug('Checking ceph cinder pool after volume delete...')
        pool_name, obj_count, kb_used = u.get_ceph_pool_sample(
            sentry_unit, cinder_ceph_pool)

        obj_count_samples.append(obj_count)
        pool_size_samples.append(kb_used)

        # Validate ceph cinder pool object count samples over time
        ret = u.validate_ceph_pool_samples(obj_count_samples,
                                           "cinder pool object count")
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)

        # Luminous (pike) ceph seems more efficient at disk usage so we cannot
        # grantee the ordering of kb_used
        if self._get_openstack_release() < self.xenial_mitaka:
            # Validate ceph cinder pool disk space usage samples over time
            ret = u.validate_ceph_pool_samples(pool_size_samples,
                                               "cinder pool disk usage")
            if ret:
                amulet.raise_status(amulet.FAIL, msg=ret)

    def test_499_ceph_cmds_exit_zero(self):
        """Check basic functionality of ceph cli commands against
        all ceph units, and the cinder-backup unit."""
        sentry_units = [
            self.cinder_backup_sentry,
            self.ceph0_sentry,
            self.ceph1_sentry,
            self.ceph2_sentry
        ]
        commands = [
            'sudo ceph health',
            'sudo ceph mds stat',
            'sudo ceph pg stat',
            'sudo ceph osd stat',
            'sudo ceph mon stat',
        ]
        ret = u.check_commands_on_units(commands, sentry_units)
        if ret:
            amulet.raise_status(amulet.FAIL, msg=ret)
