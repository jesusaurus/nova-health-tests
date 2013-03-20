#    Copyright 2012 OpenStack LLC
#
#    Licensed under the Apache License, Version 2.0 (the "License"); you may
#    not use this file except in compliance with the License. You may obtain
#    a copy of the License at
#
#         http://www.apache.org/licenses/LICENSE-2.0
#
#    Unless required by applicable law or agreed to in writing, software
#    distributed under the License is distributed on an "AS IS" BASIS, WITHOUT
#    WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied. See the
#    License for the specific language governing permissions and limitations
#    under the License.

import testtools
import time
import logging
import telnetlib
from novaclient.v1_1 import client
import re
import os
import StringIO
import urllib2
import subprocess
import ssh

logging.basicConfig(format='%(levelname)s\t%(name)s\t%(message)s')
logger = logging.getLogger('nova_health_tests')
logger.setLevel(logging.INFO)
ch = logging.StreamHandler()
logger.addHandler(ch)
MINUTE = 60


def poll_until(retriever, condition=lambda value: value,
               sleep_time=1, time_out=10 * MINUTE):
    """Retrieves object until it passes condition, then returns it.

    If time_out_limit is passed in, PollTimeOut will be raised once that
    amount of time is eclipsed.

    """
    start_time = time.time()

    obj = retriever()
    while not condition(obj):
        time.sleep(sleep_time)
        if time_out is not None and time.time() > start_time + time_out:
            raise Exception("Timeout!")
        obj = retriever()
    return obj

def check_for_exception(f, *args):
    try:
        f(*args)
        return True
    except:
        return False


class Nova_health_tests(testtools.TestCase):

    INSTANCE_NAME = 'nova_test'
    VOLUME_NAME = 'volume_test'
    SECGROUP_NAME = 'secgroup_test'
    IMAGE_NAME = 'image_test'

    def setUp(self):
        super(Nova_health_tests, self).setUp()

        username = os.environ['OS_USERNAME']
        password = os.environ['OS_PASSWORD']
        tenant = os.environ['OS_TENANT_NAME']
        auth_url = os.environ['OS_AUTH_URL']

        self.ubuntu_image = os.environ['DEFAULT_UBUNTU_IMAGE']
        self.cirros_image = os.environ['DEFAULT_CIRROS_IMAGE']
        self.flavor = os.environ['DEFAULT_FLAVOR']

        self.nova = client.Client(username=username,
                                  api_key=password,
                                  project_id=tenant,
                                  auth_url=auth_url,
                                  service_type="compute")

        self.cinder = client.Client(username=username,
                                    api_key=password,
                                    project_id=tenant,
                                    auth_url=auth_url,
                                    service_type="volume")

        self.cleanup()

    def tearDown(self):
        super(Nova_health_tests, self).tearDown()
        self.cleanup()

    def test_create_image(self):

        logger.info("Starting create image test")
        # Download image
        logger.info("Downloading image...")
        image_url = 'https://launchpad.net/cirros/trunk/0.3.0/+download/cirros-0.3.0-i386-disk.img'
        image = urllib2.urlopen(image_url)
        cmd = ['glance', 'image-create', '--name',
               Nova_health_tests.IMAGE_NAME,
               '--disk-format=raw', '--container-format=bare']
        p = subprocess.Popen(cmd, stdout=subprocess.PIPE, stdin=image)

        logger.info("Uploading image to glance...")
        out, err = p.communicate()
        image.close()
        logger.info(out)

        if p.returncode:
            logger.info(err)
            self.fail()

        test_image = [image.name for image in self.nova.images.list()
                      if image.name == Nova_health_tests.IMAGE_NAME]

        self.assertTrue(test_image)

    def test_resize_flavor(self):
        logger.info("Starting resize flavor test")

        # boot instance
        logger.info("Booting new instance")
        small_flavor = [flavor for flavor in self.nova.flavors.list()
                        if 'small' in flavor.name]
        medium_flavor = [flavor for flavor in self.nova.flavors.list()
                        if 'medium' in flavor.name]

        image = self.nova.images.find(name=self.cirros_image)
        server_id = self.nova.servers.create(Nova_health_tests.INSTANCE_NAME,
                                             image=image,
                                             flavor=small_flavor[0].id).id
        newserver = poll_until(lambda: self.nova.servers.get(server_id),
                               lambda inst: inst.status != 'BUILD',
                               sleep_time=2)
        self.assertEquals('ACTIVE', newserver.status)
        logger.info("Booted new instance: " + server_id)

        self.nova.servers.resize(newserver.id, medium_flavor[0].id)

        resized_server = poll_until(lambda: self.nova.servers.get(server_id),
                                    lambda inst: inst.status != 'BUILD' and
                                    inst.status != 'RESIZE', sleep_time=2)
        self.assertEquals('ACTIVE', resized_server.status)
        self.assertEquals(medium_flavor[0].id, resized_server.flavor['id'])

    def test_boot_with_volume(self):
        logger.info("Starting boot instance with volume test")

        # create volume
        logger.info("Creating new volume")
        volume = self.cinder.volumes.create(1,
                                            display_name=Nova_health_tests
                                            .VOLUME_NAME)
        bdm = {'/dev/vdb': '{0}:::0'.format(volume.id)}

        # boot instance
        logger.info("Booting new instance")
        flavor = self.nova.flavors.find(name=self.flavor)
        image = self.nova.images.find(name=self.cirros_image)
        server_id = self.nova.servers.create(Nova_health_tests.INSTANCE_NAME,
                                             image=image,
                                             block_device_mapping=bdm,
                                             flavor=flavor).id
        newserver = poll_until(lambda: self.nova.servers.get(server_id),
                               lambda inst: inst.status != 'BUILD',
                               sleep_time=2)
        self.assertEquals('ACTIVE', newserver.status)
        logger.info("Booted new instance: " + server_id)

        client = ssh.SSHClient()
        client.set_missing_host_key_policy(ssh.AutoAddPolicy())
        network = newserver.networks['private'][0]
        client.connect(network, username='cirros',
                       password='cubswin:)')
        _, stdout, _ = client.exec_command('ls /dev')
        result = stdout.readlines()
        client.close()
        self.assertTrue('vdb\n' in result)

    def test_security_group(self):
        logger.info("Starting security group test")

        open_port = 50000
        close_port = 50001

        # create script to start listener
        user_data = StringIO.StringIO()
        user_data.write('#!/bin/bash\n')
        user_data.write('nc -l -p {0}\n'.format(open_port))
        content = user_data.getvalue()
        user_data.close()

        # boot instance
        logger.info("Booting new instance")
        flavor = self.nova.flavors.find(name=self.flavor)
        image = self.nova.images.find(name=self.ubuntu_image)
        server_id = self.nova.servers.create(Nova_health_tests.INSTANCE_NAME,
                                             image=image,
                                             userdata=content,
                                             flavor=flavor).id
        newserver = poll_until(lambda: self.nova.servers.get(server_id),
                               lambda inst: inst.status != 'BUILD',
                               sleep_time=2)
        self.assertEquals('ACTIVE', newserver.status)
        logger.info("Booted new instance: " + server_id)

        # create sec group + rule
        logger.info("Creating new security group + rules")
        secgroup = self.nova.security_groups.create(Nova_health_tests
                                                    .SECGROUP_NAME,
                                                    'Test security group')
        self.nova.security_group_rules.create(secgroup.id, 'tcp',
                                              open_port,
                                              open_port, '0.0.0.0/0')
        self.nova.servers.add_security_group(server_id,
                                             Nova_health_tests.SECGROUP_NAME)

        network = newserver.networks['private'][0]
        logger.info('Telnetting to %s:%s', network, open_port)
        check_sec_group = poll_until(lambda: check_for_exception(telnetlib
                                                                 .Telnet,
                                                                 network,
                                                                 open_port,
                                                                 5 * MINUTE),
                                     lambda result: result,
                                     sleep_time=2)
        self.assertTrue(check_sec_group)

        self.assertRaises(Exception, telnetlib.Telnet, network, close_port,
                          5 * MINUTE)

    def cleanup(self):
        # Remove any instances with a matching name.
        previous = re.compile('^' + Nova_health_tests.INSTANCE_NAME)
        for server in self.nova.servers.list():
            if previous.match(server.name):

                sec_group_names = [sg for sg in server.security_groups
                                   if sg['name'] == Nova_health_tests
                                   .SECGROUP_NAME]
                if sec_group_names:
                    self.nova.servers.remove_security_group(server.id,
                                                            Nova_health_tests.SECGROUP_NAME)
                logger.info("Deleting instance %s", server.id)
                self.nova.servers.delete(server.id)

        poll_until(lambda: [server for server in self.nova.servers.list()
                            if previous.match(server.name)],
                   lambda server_list: not server_list,
                   sleep_time=1)

        # Remove any security group with a matching name.
        previous = re.compile('^' + Nova_health_tests.SECGROUP_NAME)
        for secgroup in self.nova.security_groups.list():
            if previous.match(secgroup.name):
                logger.info("Deleting security group %s", secgroup.name)
                self.nova.security_groups.delete(secgroup.id)

        # Remove any image with a matching name.
        previous = re.compile('^' + Nova_health_tests.IMAGE_NAME)
        for image in self.nova.images.list():
            if previous.match(image.name):
                logger.info("Deleting image %s", image.name)
                self.nova.images.delete(image.id)

        # Remove any volume with a matching name.
        previous = re.compile('^' + Nova_health_tests.VOLUME_NAME)
        for volume in self.cinder.volumes.list():
            if previous.match(volume.display_name):
                logger.info("Deleting volume %s", volume.display_name)
                self.cinder.volumes.delete(volume.id)
