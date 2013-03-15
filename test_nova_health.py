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
from nose.tools import nottest

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

    INSTANCE_NAME = "nova_test"
    SECGROUP_NAME = "secgroup_test"

    def setUp(self):
        super(Nova_health_tests, self).setUp()

        username = os.environ['OS_USERNAME']
        password = os.environ['OS_PASSWORD']
        tenant = os.environ['OS_TENANT_NAME']
        auth_url = os.environ['OS_AUTH_URL']

        self.image = os.environ['DEFAULT_IMAGE']
        self.flavor = os.environ['DEFAULT_FLAVOR']

        self.nova = client.Client(username=username,
                                  api_key=password,
                                  project_id=tenant,
                                  auth_url=auth_url,
                                  service_type="compute")
	
	
	self.cleanup()

    def tearDown(self):
        super(Nova_health_tests, self).tearDown()
        self.cleanup()

    def test_create_image(self):

        # Download image
        #image_file_location = '/tmp/cirros.img'
        image_url = 'https://launchpad.net/cirros/trunk/0.3.0/+download/cirros-0.3.0-i386-disk.img'
        image = urllib2.urlopen(image_url)
        #output = open(image_file_location, 'rb')
        #output.write(image.read())
        #output.close()
	cmd = ['glance', 'image-create', '--name', 'My Test Image', '--disk-format=raw', '--container-format=bare']
        subprocess.call(cmd, stdin=image)

    def test_security_group(self):

        open_port = 50000
        close_port = 50001

        # create script to start listener
        user_data = StringIO.StringIO()
        user_data.write('#!/bin/bash\n')
        user_data.write('nc -l -p {0}\n'.format(open_port))
        content = user_data.getvalue()
        user_data.close()

        # boot instance
        flavor = self.nova.flavors.find(name=self.flavor)
        image = self.nova.images.find(name=self.image)
        server_id = self.nova.servers.create(Nova_health_tests.INSTANCE_NAME,
                                             image=image,
                                             userdata=content,
                                             flavor=flavor).id
        newserver = poll_until(lambda: self.nova.servers.get(server_id),
                               lambda inst: inst.status != 'BUILD',
                               sleep_time=2)
        self.assertEquals('ACTIVE', newserver.status)

        # create sec group + rule
        secgroup = self.nova.security_groups.create(Nova_health_tests
                                                    .SECGROUP_NAME,
                                                    'Test security group')
        self.nova.security_group_rules.create(secgroup.id, 'tcp',
                                              open_port,
                                              open_port, '0.0.0.0/0')
        self.nova.servers.add_security_group(server_id,
                                             Nova_health_tests.SECGROUP_NAME)

        network = newserver.networks['private'][0]
        logger.info('Telnet to %s:%s', network, open_port)
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
                logger.info("Deleting instance %s", server.id)
                self.nova.servers.remove_security_group(server.id,
                                                        Nova_health_tests
                                                        .SECGROUP_NAME)
		self.nova.servers.delete(server.id)

        # Remove any security group with a matching name.
        previous = re.compile('^' + Nova_health_tests.SECGROUP_NAME)
        for secgroup in self.nova.security_groups.list():
            if previous.match(secgroup.name):
                logger.info("Deleting security group %s", secgroup.name)
                self.nova.security_groups.delete(secgroup.id)

