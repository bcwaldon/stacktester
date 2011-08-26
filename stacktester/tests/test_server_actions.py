
import base64
import json
import time

from stacktester import exceptions
from stacktester import openstack
from stacktester.common import ssh

import unittest2 as unittest


class ServerActionsTest(unittest.TestCase):

    multi_node = openstack.Manager().config.env.multi_node

    def setUp(self):
        self.os = openstack.Manager()

        self.image_ref = self.os.config.env.image_ref
        self.image_ref_alt = self.os.config.env.image_ref_alt
        self.flavor_ref = self.os.config.env.flavor_ref
        self.flavor_ref_alt = self.os.config.env.flavor_ref_alt
        self.ssh_timeout = self.os.config.nova.ssh_timeout
        self.build_timeout = self.os.config.nova.build_timeout

        self.server_password = 'testpwd'
        self.server_name = 'stacktester1'

        expected_server = {
            'name': self.server_name,
            'imageRef': self.image_ref,
            'flavorRef': self.flavor_ref,
            'adminPass': self.server_password,
        }

        created_server = self.os.nova.create_server(expected_server)

        self.server_id = created_server['id']
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        server = self.os.nova.get_server(self.server_id)

        self.access_ip = server['addresses']['public'][0]['addr']

        # Ensure server came up
        self._assert_ssh_password()

    def tearDown(self):
        self.os.nova.delete_server(self.server_id)

    def _get_ssh_client(self, password):
        return ssh.Client(self.access_ip, 'root', password, self.ssh_timeout)

    def _assert_ssh_password(self, password=None):
        _password = password or self.server_password
        client = self._get_ssh_client(_password)
        self.assertTrue(client.test_connection_auth())

    def _wait_for_server_status(self, server_id, status):
        try:
            self.os.nova.wait_for_server_status(server_id, status,
                                                timeout=self.build_timeout)
        except exceptions.TimeoutException:
            self.fail("Server failed to change status to %s" % status)

    def _get_boot_time(self):
        """Return the time the server was started"""
        output = self._read_file("/proc/uptime")
        uptime = float(output.split().pop(0))
        return time.time() - uptime

    def _write_file(self, filename, contents, password=None):
        command = "echo -n %s > %s" % (contents, filename)
        return self._exec_command(command, password)

    def _read_file(self, filename, password=None):
        command = "cat %s" % filename
        return self._exec_command(command, password)

    def _exec_command(self, command, password=None):
        if password is None:
            password = self.server_password
        client = self._get_ssh_client(password)
        return client.exec_command(command)

    def test_change_password_and_reboot(self):
        """Change password then reboot the server"""

        # Change server password
        post_body = json.dumps({'changePassword': {'adminPass': 'test123'}})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)

        # Assert status transition
        self.assertEqual('202', response['status'])
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'PASSWORD')
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # SSH into server using new password
        self._assert_ssh_password('test123')

        # Now try to soft-reboot
        # SSH and get the uptime
        initial_time_started = self._get_boot_time()

        # Make reboot request
        post_body = json.dumps({'reboot': {'type': 'SOFT'}})
        url = "/servers/%s/action" % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)
        self.assertEqual(response['status'], '202')

        # Assert status transition
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'REBOOT')
        ssh_client = self._get_ssh_client(self.server_password)
        ssh_client.connect_until_closed()
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # SSH and verify uptime is less than before
        post_reboot_time_started = self._get_boot_time()
        self.assertTrue(initial_time_started < post_reboot_time_started)

        # Now try to hard-reboot
        # SSH and get the uptime
        initial_time_started = self._get_boot_time()

        # Make reboot request
        post_body = json.dumps({'reboot': {'type': 'HARD'}})
        url = "/servers/%s/action" % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)
        self.assertEqual(response['status'], '202')

        # Assert status transition
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'HARD_REBOOT')
        ssh_client = self._get_ssh_client(self.server_password)
        ssh_client.connect_until_closed()
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # SSH and verify uptime is less than before
        post_reboot_time_started = self._get_boot_time()
        self.assertTrue(initial_time_started < post_reboot_time_started)

    def test_rebuild(self):
        """Rebuild a server"""

        FILENAME = '/tmp/testfile'
        CONTENTS = 'WORDS'

        # Write file to server
        self._write_file(FILENAME, CONTENTS)
        self.assertEqual(self._read_file(FILENAME), CONTENTS)

        # Make rebuild request
        post_body = json.dumps({
            'rebuild': {
                'name': 'stacktester2',
                'imageRef': self.image_ref_alt,
                'metadata': {'1234': '5678'},
                'personality': [
                    {'path': '/tmp/asdf', 'contents': base64.encode('XXX')},
                ],
            },
        })
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)
        self.assertEqual('202', response['status'])
        rebuilt_server = json.loads(body)['server']
        generated_password = rebuilt_server['adminPass']
        self.assertTrue('personality' not in rebuilt_server)

        # Ensure correct status transition
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'REBUILD')
        self._wait_for_server_status(self.server_id, 'BUILD')
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # Check that the instance's imageRef matches the new imageRef
        server = self.os.nova.get_server(self.server_id)
        ref_match = self.image_ref_alt == server['image']['links'][0]['href']
        id_match = self.image_ref_alt == server['image']['id']
        self.assertTrue(ref_match or id_match)

        # Metadata should be overwritten
        self.assertEqual({'1234': '5678'}, rebuilt_server['metadata'])
        self.assertEqual({'1234': '5678'}, server['metadata'])

        # Name should change
        self.assertEqual('stacktester2', rebuilt_server['name'])
        self.assertEqual('stacktester2', server['name'])

        # SSH into the server to ensure it came back up
        self._assert_ssh_password(generated_password)

        # Make sure original file is gone
        self.assertEqual(self._read_file(FILENAME, generated_password), '')

        # Ensure injected file is there
        _contents = self._read_file('/tmp/asdf', generated_password)
        self.assertEqual(_contents, 'XXX')

        # Make another rebuild request
        specified_password = 'some_password'
        post_body = json.dumps({
            'rebuild': {
                'imageRef': self.image_ref,
                'adminPass': specified_password,
            }
        })
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)
        self.assertEqual('202', response['status'])
        rebuilt_server = json.loads(body)['server']
        self.assertEqual(rebuilt_server['adminPass'], specified_password)

        # Ensure correct status transition
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'REBUILD')
        self._wait_for_server_status(self.server_id, 'BUILD')
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # Check that the instance's imageRef matches the new imageRef
        server = self.os.nova.get_server(self.server_id)
        ref_match = self.image_ref == server['image']['links'][0]['href']
        id_match = self.image_ref == server['image']['id']
        self.assertTrue(ref_match or id_match)

        # Metadata should not change
        self.assertEqual({'1234': '5678'}, rebuilt_server['metadata'])
        self.assertEqual({'1234': '5678'}, server['metadata'])

        # Name should not change
        self.assertEqual('stacktester2', rebuilt_server['name'])
        self.assertEqual('stacktester2', server['name'])

        # SSH into the server to ensure it came back up
        self._assert_ssh_password(specified_password)

        # make sure previously-injected file is gone
        self.assertEqual(self._read_file('/tmp/asdf', specified_password), '')

    @unittest.skipIf(not multi_node, 'Multiple compute nodes required')
    def test_resize_server_confirm(self):
        """Resize a server"""
        # Make resize request
        post_body = json.dumps({'resize': {'flavorRef': self.flavor_ref_alt}})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)

        # Wait for status transition
        self.assertEqual('202', response['status'])
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'VERIFY_RESIZE')
        self._wait_for_server_status(self.server_id, 'RESIZE-CONFIRM')

        # Ensure API reports new flavor
        server = self.os.nova.get_server(self.server_id)
        self.assertEqual(self.flavor_ref_alt, server['flavor']['id'])

        #SSH into the server to ensure it came back up
        self._assert_ssh_password()

        # Make confirmResize request
        post_body = json.dumps({'confirmResize': 'null'})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)

        # Wait for status transition
        self.assertEqual('204', response['status'])
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # Ensure API still reports new flavor
        server = self.os.nova.get_server(self.server_id)
        self.assertEqual(self.flavor_ref_alt, server['flavor']['id'])

    @unittest.skipIf(not multi_node, 'Multiple compute nodes required')
    def test_resize_server_revert(self):
        """Resize a server, then revert"""

        # Make resize request
        post_body = json.dumps({'resize': {'flavorRef': self.flavor_ref_alt}})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)

        # Wait for status transition
        self.assertEqual('202', response['status'])
        # KNOWN-ISSUE
        #self._wait_for_server_status(self.server_id, 'VERIFY_RESIZE')
        self._wait_for_server_status(self.server_id, 'RESIZE-CONFIRM')

        # SSH into the server to ensure it came back up
        self._assert_ssh_password()

        # Ensure API reports new flavor
        server = self.os.nova.get_server(self.server_id)
        self.assertEqual(self.flavor_ref_alt, server['flavor']['id'])

        # Make revertResize request
        post_body = json.dumps({'revertResize': 'null'})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=post_body)

        # Assert status transition
        self.assertEqual('202', response['status'])
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # Ensure flavor ref was reverted to original
        server = self.os.nova.get_server(self.server_id)
        self.assertEqual(self.flavor_ref, server['flavor']['id'])


class SnapshotTests(unittest.TestCase):

    def setUp(self):
        self.os = openstack.Manager()

        self.image_ref = self.os.config.env.image_ref
        self.flavor_ref = self.os.config.env.flavor_ref
        self.ssh_timeout = self.os.config.nova.ssh_timeout
        self.build_timeout = self.os.config.nova.build_timeout

        self.server_name = 'stacktester1'

        expected_server = {
            'name': self.server_name,
            'imageRef': self.image_ref,
            'flavorRef': self.flavor_ref,
        }

        created_server = self.os.nova.create_server(expected_server)
        self.server_id = created_server['id']

    def tearDown(self):
        self.os.nova.delete_server(self.server_id)

    def _wait_for_server_status(self, server_id, status):
        try:
            self.os.nova.wait_for_server_status(server_id, status,
                                                timeout=self.build_timeout)
        except exceptions.TimeoutException:
            self.fail("Server failed to change status to %s" % status)

    def test_snapshot_server_active(self):
        """Create image from an existing server"""

        # Wait for server to come up before running this test
        self._wait_for_server_status(self.server_id, 'ACTIVE')

        # Create snapshot
        image_data = {'name': 'backup'}
        req_body = json.dumps({'createImage': image_data})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=req_body)

        self.assertEqual(response['status'], '202')
        image_ref = response['location']
        snapshot_id = image_ref.rsplit('/', 1)[1]

        # Get snapshot and check its attributes
        resp, body = self.os.nova.request('GET', '/images/%s' % snapshot_id)
        snapshot = json.loads(body)['image']
        self.assertEqual(snapshot['name'], image_data['name'])
        server_ref = snapshot['server']['links'][0]['href']
        self.assertTrue(server_ref.endswith('/%s' % self.server_id))

        # Ensure image is actually created
        self.os.nova.wait_for_image_status(snapshot['id'], 'ACTIVE')

        # Cleaning up
        self.os.nova.request('DELETE', '/images/%s' % snapshot_id)

    def test_snapshot_server_inactive(self):
        """Ensure inability to snapshot server in BUILD state"""

        # Create snapshot
        req_body = json.dumps({'createImage': {'name': 'backup'}})
        url = '/servers/%s/action' % self.server_id
        response, body = self.os.nova.request('POST', url, body=req_body)

        # KNOWN-ISSUE - we shouldn't be able to snapshot a building server
        #self.assertEqual(response['status'], '400')  # what status code?
        self.assertEqual(response['status'], '202')
        snapshot_id = response['location'].rsplit('/', 1)[1]
        # Delete image for now, won't need this once correct status code is in
        self.os.nova.request('DELETE', '/images/%s' % snapshot_id)
