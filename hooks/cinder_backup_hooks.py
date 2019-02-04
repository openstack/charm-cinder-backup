#!/usr/bin/env python3
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

import os
import sys
import json

from cinder_backup_utils import (
    register_configs,
    restart_map,
    set_ceph_env_variables,
    PACKAGES,
    REQUIRED_INTERFACES,
    VERSION_PACKAGE,
)
from cinder_backup_contexts import (
    CephBackupSubordinateContext
)
from charmhelpers.core.hookenv import (
    config,
    Hooks,
    UnregisteredHookError,
    service_name,
    relation_set,
    relation_ids,
    log,
)
from charmhelpers.fetch import apt_install, apt_update
from charmhelpers.core.host import (
    restart_on_change,
    service_restart,
)
from charmhelpers.contrib.openstack.utils import (
    set_os_workload_status,
    os_application_version_set,
    set_unit_paused,
    set_unit_upgrading,
    clear_unit_paused,
    clear_unit_upgrading,
)
from charmhelpers.contrib.storage.linux.ceph import (
    delete_keyring,
    ensure_ceph_keyring,
    is_request_complete,
    CephBrokerRq,
    send_request_if_needed,
)
from charmhelpers.payload.execd import execd_preinstall

hooks = Hooks()
CONFIGS = register_configs()


@hooks.hook('install')
def install():
    execd_preinstall()
    apt_update(fatal=True)
    apt_install(PACKAGES, fatal=True)


@hooks.hook('ceph-relation-joined')
def ceph_joined():
    if not os.path.isdir('/etc/ceph'):
        os.mkdir('/etc/ceph')


def get_ceph_request():
    service = service_name()
    rq = CephBrokerRq()
    replicas = config('ceph-osd-replication-count')
    rq.add_op_create_pool(name=service, replica_count=replicas)
    return rq


@hooks.hook('ceph-relation-changed')
@restart_on_change(restart_map())
def ceph_changed():
    if 'ceph' not in CONFIGS.complete_contexts():
        log('ceph relation incomplete. Peer not ready?')
        return

    service = service_name()
    if not ensure_ceph_keyring(service=service,
                               user='cinder', group='cinder'):
        log('Could not create ceph keyring: peer not ready?')
        return

    if is_request_complete(get_ceph_request()):
        log('Request complete')
        CONFIGS.write_all()
        set_ceph_env_variables(service=service)
        for rid in relation_ids('backup-backend'):
            backup_backend_joined(rid)

        # Ensure that cinder services are restarted since only now can we
        # guarantee that ceph resources are ready. Note that the order of
        # restart is important here.
        for svc in ['cinder-volume', 'cinder-backup']:
            service_restart(svc)

    else:
        send_request_if_needed(get_ceph_request())


@hooks.hook('ceph-relation-broken')
def ceph_broken():
    service = service_name()
    delete_keyring(service=service)
    CONFIGS.write_all()


@hooks.hook('config-changed')
@restart_on_change(restart_map())
def write_and_restart():
    CONFIGS.write_all()


@hooks.hook('backup-backend-relation-joined')
def backup_backend_joined(rel_id=None):
    if 'ceph' not in CONFIGS.complete_contexts():
        log('ceph relation incomplete. Peer not ready?')
    else:
        ctxt = CephBackupSubordinateContext()()
        relation_set(
            relation_id=rel_id,
            backend_name=service_name(),
            subordinate_configuration=json.dumps(ctxt)
        )

        # NOTE(hopem): This currently only applies when using the ceph driver.
        #              In future, if/when support is added for other drivers,
        #              this will need to be conditional on whether the
        #              configured driver is stateless or not.
        relation_set(relation_id=rel_id, stateless=True)


@hooks.hook('backup-backend-relation-changed')
def backup_backend_changed():
    # NOTE(jamespage) recall backup_backend as this only ever
    # changes post initial creation if the cinder charm is upgraded to a new
    # version of openstack.
    backup_backend_joined()


@hooks.hook('upgrade-charm')
@restart_on_change(restart_map())
def upgrade_charm():
    if 'ceph' in CONFIGS.complete_contexts():
        CONFIGS.write_all()
        set_ceph_env_variables(service=service_name())
        for rid in relation_ids('backup-backend'):
            backup_backend_joined(rid)


@hooks.hook('pre-series-upgrade')
def pre_series_upgrade():
    log("Running prepare series upgrade hook", "INFO")
    # In order to indicate the step of the series upgrade process for
    # administrators and automated scripts, the charm sets the paused and
    # upgrading states.
    set_unit_paused()
    set_unit_upgrading()


@hooks.hook('post-series-upgrade')
def post_series_upgrade():
    log("Running complete series upgrade hook", "INFO")
    # In order to indicate the step of the series upgrade process for
    # administrators and automated scripts, the charm clears the paused and
    # upgrading states.
    clear_unit_paused()
    clear_unit_upgrading()


if __name__ == '__main__':
    try:
        hooks.execute(sys.argv)
    except UnregisteredHookError as e:
        log('Unknown hook {} - skipping.'.format(e))
    set_os_workload_status(CONFIGS, REQUIRED_INTERFACES)
    os_application_version_set(VERSION_PACKAGE)
