Cinder Backup Service
-------------------------------

Overview
========

This charm provides a Cinder Backup component as part of OpenStack Cinder service.
It is intended to be used alongside the other OpenStack components, even though it must
have relation set up with core Cinder service.

The below deployment instructions assume that a Ceph cluster and the Cinder
service are pre-existing.

To deploy:

    juju deploy --channel <channel> cinder-backup
    juju add-relation cinder-backup:backup-backend cinder:backup-backend
    juju add-relation cinder-backup:ceph ceph-mon:client

Configuration
=============
