# Copyright 2011 OpenStack LLC.
# All Rights Reserved.
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

from domainobjects.openstack import OpenStack
from domainobjects.flavors import Flavor
from domainobjects.utils import *
from nose.tools import assert_raises, assert_equal

class TestFlavors:
    
    @classmethod
    def setup_class(self):
        self.os = OpenStack(get_username(), get_api_key())

    def test_get_flavor_details(self):
	"""        
	Verify the expected details are returned for a flavor
	"""

	flavor = self.os.flavors.get(1)
        assert_isinstance(flavor, Flavor)
        assert_equal(flavor.ram, 512)
        assert_equal(flavor.disk, 0)
        assert_equal(200, flavor.status_code)

  