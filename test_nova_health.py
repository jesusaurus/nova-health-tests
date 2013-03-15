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


logging.basicConfig(format='%(levelname)s\t%(name)s\t%(message)s')
logger = logging.getLogger('nova_health_tests')
logger.setLevel(logging.INFO)
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


class Nova_health_tests(testtools.TestCase):

    INSTANCE_NAME = "nova_test"
    DEFAULT_FLAVOR = "standard.xsmall"
    DEFAULT_IMAGE = "Ubuntu Precise 12.04 LTS Server 64-bit 20121026 (b)"

    def setUp(self):
        super(Nova_health_tests, self).setUp()

        username = os.environ['OS_USERNAME']
        password = os.environ['OS_PASSWORD']
        tenant = os.environ['OS_TENANT_NAME']
        auth_url = os.environ['OS_AUTH_URL']

        Nova_health_tests.DEFAULT_FLAVOR = "m1.tiny"
        Nova_health_tests.DEFAULT_IMAGE = "quantal"

        self.nova = client.Client(username=username,
                                  api_key=password,
                                  project_id=tenant,
                                  auth_url=auth_url,
                                  service_type="compute")

    def tearDown(self):
        super(Nova_health_tests, self).tearDown()
        self.cleanup()

    def test_security_group(self):
	
	user_data_file = "/tmp/portListener.sh"
	file = open(user_data_file, 'w')
	file.write('#!/bin/bash\n')
	file.write('nc -l -p 50000\n')
	file.close()
	self.assertTrue(os.path.exists(user_data_file))
        flavor = self.nova.flavors.find(name=Nova_health_tests.DEFAULT_FLAVOR)
        image = self.nova.images.find(name=Nova_health_tests.DEFAULT_IMAGE)

        server_id = self.nova.servers.create(Nova_health_tests.INSTANCE_NAME,
                                      image=image,
				      userdata=user_data_file,
                                      flavor=flavor).id
        newserver = poll_until(lambda: self.nova.servers.get(server_id),
                               lambda inst: inst.status != 'BUILD',
                               sleep_time=2)

        self.assertEquals("ACTIVE", newserver.status)
        network = newserver.networks["private"][0]
        logger.info('Telnet to %s:%s', network, 50000)
        telnet_client = telnetlib.Telnet(network, 50000, 500)


    def cleanup(self):
        '''Remove any instances with a matching name then exit.'''
        previous = re.compile('^' + Nova_health_tests.INSTANCE_NAME)
        exit = False
        for server in self.nova.servers.list():
            if previous.match(server.name):
                logger.warning("Detected active instance from another run, "
                               "deleting %s", server.id)
                self.delete(server.id)

    def delete(self, server_id):

        try:
            logger.info('Deleting server: {0}'.format(server_id))
            self.nova.servers.delete(server_id)
        except Exception as e:
            logger.exception('Encountered an Exception: {0}'.format(e))
            raise e
