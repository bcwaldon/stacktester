import json
import os

import unittest2 as unittest

from stacktester import openstack


class ImagesTest(unittest.TestCase):

    def setUp(self):
        self.os = openstack.Manager()

        host = self.os.config.nova.host
        port = self.os.config.nova.port
        self.base_url = '%s:%s' % (host, port)
        self.api_url = os.path.join(self.base_url, self.os.config.nova.base_url)

    def tearDown(self):
        pass

    def _assert_image_links(self, image):
        image_id = str(image['id'])

        self_link = 'http://' + os.path.join(self.api_url, 'images', image_id)
        bookmark_link = 'http://' + os.path.join(self.base_url, 'images', image_id)

        expected_links = [
            {
                'rel': 'self',
                'href': self_link,
            },
            {
                'rel': 'bookmark',
                'href': bookmark_link,
            },
        ]

        # KNOWN-ISSUE lp803505
        #self.assertEqual(image['links'], expected_links)

    def _assert_image_entity_basic(self, image):
        actual_keys = set(image.keys())
        expected_keys = set((
            'id',
            'name',
            'links',
        ))
        self.assertEqual(actual_keys, expected_keys)

        self._assert_image_links(image)

    def _assert_image_entity_detailed(self, image):
        actual_keys = set(image.keys())
        expected_keys = set((
            'id',
            'name',
            'created',
            'updated',
            'status',
            'metadata',
            'links',
        ))
        self.assertEqual(actual_keys, expected_keys)

        self._assert_image_links(image)

    def test_index(self):
        """List all images"""

        response, body = self.os.nova.request('GET', '/images')

        self.assertEqual(response['status'], '200')
        resp_body = json.loads(body)
        self.assertEqual(resp_body.keys(), ['images'])

        for image in resp_body['images']:
            self._assert_image_entity_basic(image)

    def test_detail(self):
        """List all images in detail"""

        response, body = self.os.nova.request('GET', '/images/detail')

        self.assertEqual(response['status'], '200')
        resp_body = json.loads(body)
        self.assertEqual(resp_body.keys(), ['images'])

        for image in resp_body['images']:
            self._assert_image_entity_detailed(image)

    def _create_snapshot(self, image):
        req_body = json.dumps({'image': image})
        response, body = self.os.nova.request('POST', '/images', body=req_body)

        # KNOWN-ISSUE incorrect response code
        #self.assertEqual(response['status'], '202')
        self.assertEqual(response['status'], '200')

        data = json.loads(body)
        self.assertEqual(data.keys(), ['image'])
        return data['image']

    def test_snapshot_active_server(self):
        """Create image from an existing server"""

        # Create server to snapshot
        expected_server = {
            'name' : 'testserver',
            'imageRef' : self.os.config.env.image_ref,
            'flavorRef' : self.os.config.env.flavor_ref
        }
        server = self.os.nova.create_server(expected_server)
        self.os.nova.wait_for_server_status(server['id'], 'ACTIVE')

        # Create snapshot
        server_ref = 'http://' + os.path.join(self.api_url, 'servers', str(server['id']))
        expected_image = {
            'name' : 'backup',
            'serverRef' : server_ref,
        }
        snapshot = self._create_snapshot(expected_image)
        # KNOWN-ISSUE
        server_ref = snapshot.pop('server', None)
        #self.assertEqual(server_ref, expected_image['serverRef'])
        self._assert_image_entity_detailed(snapshot)
        self.assertEqual(snapshot['name'], expected_image['name'])

        self.os.nova.wait_for_image_status(snapshot['id'], 'ACTIVE')

        # Cleaning up
        self.os.nova.request('DELETE', '/images/%s' % snapshot['id'])
        self.os.nova.delete_server(server['id'])

    def test_snapshot_server_not_active(self):
        """Ensure inability to snapshot server in BUILD state"""

        # Create server to snapshot
        expected_server = {
            'name' : 'testserver',
            'imageRef' : self.os.config.env.image_ref,
            'flavorRef' : self.os.config.env.flavor_ref,
        }
        server = self.os.nova.create_server(expected_server)

        # Create snapshot
        req_body = json.dumps({
            'image': {
                'name' : 'backup',
                'serverRef' : str(server['id']),
            },
        })
        response, body = self.os.nova.request('POST',
                                              '/images',
                                              body=req_body)

        # KNOWN-ISSUE - we shouldn't be able to snapshot a building server
        #self.assertEqual(response['status'], '400')  # what status code?
        self.assertEqual(response['status'], '200')
        image_id = json.loads(body)['image']['id']
        # Delete image for now, won't need this once correct status code is in
        self.os.nova.request('DELETE', '/images/%s' % image_id)

        # Cleaning up
        self.os.nova.delete_server(server['id'])
