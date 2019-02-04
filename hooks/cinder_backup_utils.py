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
from collections import OrderedDict

from charmhelpers.core.hookenv import (
    relation_ids,
    service_name,
)
from charmhelpers.contrib.openstack import (
    templating,
    context,
)
from charmhelpers.contrib.openstack.utils import (
    get_os_codename_package,
)
from charmhelpers.contrib.openstack.alternatives import install_alternative
from charmhelpers.core.host import mkdir


PACKAGES = [
    'ceph-common',
    'cinder-backup',
]
REQUIRED_INTERFACES = {
    'ceph': ['ceph'],
}
VERSION_PACKAGE = 'cinder-common'
CHARM_CEPH_CONF = '/var/lib/charm/{}/ceph.conf'
CEPH_CONF = '/etc/ceph/ceph.conf'
TEMPLATES = 'templates/'

# Map config files to hook contexts and services that will be associated
# with file in restart_on_changes()'s service map.
CONFIG_FILES = {}


def ceph_config_file():
    return CHARM_CEPH_CONF.format(service_name())


def register_configs():
    """Register config files with their respective contexts.

    Registration of some configs may not be required depending on
    existing of certain relations.
    """
    # if called without anything installed (eg during install hook)
    # just default to earliest supported release. configs dont get touched
    # till post-install, anyway.
    release = get_os_codename_package('cinder-common', fatal=False) or 'folsom'
    configs = templating.OSConfigRenderer(templates_dir=TEMPLATES,
                                          openstack_release=release)

    confs = []

    if relation_ids('ceph'):
        # Add charm ceph configuration to resources and
        # ensure directory actually exists
        mkdir(os.path.dirname(ceph_config_file()))
        mkdir(os.path.dirname(CEPH_CONF))
        # Install ceph config as an alternative for co-location with
        # ceph and ceph-osd charms - nova-compute ceph.conf will be
        # lower priority that both of these but thats OK
        if not os.path.exists(ceph_config_file()):
            # touch file for pre-templated generation
            open(ceph_config_file(), 'w').close()
        install_alternative(os.path.basename(CEPH_CONF),
                            CEPH_CONF, ceph_config_file())
        CONFIG_FILES[ceph_config_file()] = {
            'hook_contexts': [context.CephContext()],
            'services': ['cinder-backup'],
        }
        confs.append(ceph_config_file())

    for conf in confs:
        configs.register(conf, CONFIG_FILES[conf]['hook_contexts'])

    return configs


def restart_map():
    """Determine the correct resource map to be passed to
    charmhelpers.core.restart_on_change() based on the services configured.

    :returns: dict: A dictionary mapping config file to lists of services
                    that should be restarted when file changes.
    """
    _map = []
    for f, ctxt in CONFIG_FILES.items():
        svcs = []
        for svc in ctxt['services']:
            svcs.append(svc)
        if svcs:
            _map.append((f, svcs))
    return OrderedDict(_map)


def set_ceph_env_variables(service):
    # XXX: Horrid kludge to make cinder-backup use
    # a different ceph username than admin
    with open('/etc/environment', 'rt') as f:
        env = f.read()
    if 'CEPH_ARGS' not in env:
        with open('/etc/environment', 'at') as out:
            out.write('CEPH_ARGS="--id %s"\n' % service)
    with open('/etc/init/cinder-backup.override', 'wt') as out:
        out.write('env CEPH_ARGS="--id %s"\n' % service)
