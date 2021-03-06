# Copyright 2012 OpenStack Foundation
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


import logging

import fixtures
from keystoneauth1 import session
import mock

import novaclient.api_versions
import novaclient.client
import novaclient.extension
from novaclient.tests.unit import utils
import novaclient.v2.client


class ClientConnectionPoolTest(utils.TestCase):

    @mock.patch("keystoneauth1.session.TCPKeepAliveAdapter")
    def test_get(self, mock_http_adapter):
        mock_http_adapter.side_effect = lambda: mock.Mock()
        pool = novaclient.client._ClientConnectionPool()
        self.assertEqual(pool.get("abc"), pool.get("abc"))
        self.assertNotEqual(pool.get("abc"), pool.get("def"))


class ClientTest(utils.TestCase):

    def test_client_with_timeout(self):
        auth_url = "http://example.com"
        instance = novaclient.client.HTTPClient(user='user',
                                                password='password',
                                                projectid='project',
                                                timeout=2,
                                                auth_url=auth_url)
        self.assertEqual(2, instance.timeout)

        headers = {
            'x-server-management-url': 'example.com',
            'x-auth-token': 'blah',
        }

        self.requests_mock.get(auth_url, headers=headers)

        instance.authenticate()

        self.assertEqual(2, self.requests_mock.last_request.timeout)

    def test_client_reauth(self):
        auth_url = "http://www.example.com"
        instance = novaclient.client.HTTPClient(user='user',
                                                password='password',
                                                projectid='project',
                                                timeout=2,
                                                auth_url=auth_url)
        instance.auth_token = 'foobar'
        mgmt_url = "http://mgmt.example.com"
        instance.management_url = mgmt_url
        instance.get_service_url = mock.Mock(return_value=mgmt_url)
        instance.version = 'v2.0'

        auth = self.requests_mock.post(auth_url + '/tokens', status_code=401)
        detail = self.requests_mock.get(mgmt_url + '/servers/detail',
                                        status_code=401)

        self.assertRaises(novaclient.exceptions.Unauthorized,
                          instance.get,
                          '/servers/detail')

        self.assertEqual(2, self.requests_mock.call_count)
        self.assertTrue(detail.called_once)
        self.assertTrue(auth.called_once)

        detail_headers = detail.last_request.headers
        self.assertEqual('project', detail_headers['X-Auth-Project-Id'])
        self.assertEqual('foobar', detail_headers['X-Auth-Token'])
        self.assertEqual('python-novaclient', detail_headers['User-Agent'])
        self.assertEqual('application/json', detail_headers['Accept'])

        reauth_headers = auth.last_request.headers
        self.assertEqual('application/json', reauth_headers['Content-Type'])
        self.assertEqual('application/json', reauth_headers['Accept'])
        self.assertEqual('python-novaclient', reauth_headers['User-Agent'])

        data = {
            "auth": {
                "tenantName": "project",
                "passwordCredentials": {
                    "username": "user",
                    "password": "password"
                }
            }
        }

        self.assertEqual(data, auth.last_request.json())

    def _check_version_url(self, management_url, version_url):
        projectid = '25e469aa1848471b875e68cde6531bc5'
        auth_url = "http://example.com"
        instance = novaclient.client.HTTPClient(user='user',
                                                password='password',
                                                projectid=projectid,
                                                auth_url=auth_url)
        instance.auth_token = 'foobar'
        instance.management_url = management_url % projectid
        mock_get_service_url = mock.Mock(return_value=instance.management_url)
        instance.get_service_url = mock_get_service_url
        instance.version = 'v2.0'

        versions = self.requests_mock.get(version_url, json={'versions': []})
        servers = self.requests_mock.get(instance.management_url + 'servers')

        # If passing None as the part of url, a client accesses the url which
        # doesn't include "v2/<projectid>" for getting API version info.
        instance.get(None)

        self.assertTrue(versions.called_once)

        # Otherwise, a client accesses the url which includes "v2/<projectid>".
        self.assertFalse(servers.called_once)
        instance.get('servers')
        self.assertTrue(servers.called_once)

    def test_client_version_url(self):
        self._check_version_url('http://example.com/v2/%s',
                                'http://example.com/')
        self._check_version_url('http://example.com/v2.1/%s',
                                'http://example.com/')
        self._check_version_url('http://example.com/v3.785/%s',
                                'http://example.com/')

    def test_client_version_url_with_project_name(self):
        self._check_version_url('http://example.com/nova/v2/%s',
                                'http://example.com/nova/')
        self._check_version_url('http://example.com/nova/v2.1/%s',
                                'http://example.com/nova/')
        self._check_version_url('http://example.com/nova/v3.785/%s',
                                'http://example.com/nova/')

    def test_get_client_class_v2(self):
        output = novaclient.client.get_client_class('2')
        self.assertEqual(output, novaclient.v2.client.Client)

    def test_get_client_class_v2_int(self):
        output = novaclient.client.get_client_class(2)
        self.assertEqual(output, novaclient.v2.client.Client)

    def test_get_client_class_v1_1(self):
        output = novaclient.client.get_client_class('1.1')
        self.assertEqual(output, novaclient.v2.client.Client)

    def test_get_client_class_unknown(self):
        self.assertRaises(novaclient.exceptions.UnsupportedVersion,
                          novaclient.client.get_client_class, '0')

    def test_get_client_class_latest(self):
        self.assertRaises(novaclient.exceptions.UnsupportedVersion,
                          novaclient.client.get_client_class, 'latest')
        self.assertRaises(novaclient.exceptions.UnsupportedVersion,
                          novaclient.client.get_client_class, '2.latest')

    def test_client_with_os_cache_enabled(self):
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2", os_cache=True)
        self.assertTrue(cs.os_cache)
        self.assertTrue(cs.client.os_cache)

    def test_client_with_os_cache_disabled(self):
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2", os_cache=False)
        self.assertFalse(cs.os_cache)
        self.assertFalse(cs.client.os_cache)

    def test_client_with_no_cache_enabled(self):
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2", no_cache=True)
        self.assertFalse(cs.os_cache)
        self.assertFalse(cs.client.os_cache)

    def test_client_with_no_cache_disabled(self):
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2", no_cache=False)
        self.assertTrue(cs.os_cache)
        self.assertTrue(cs.client.os_cache)

    def test_client_set_management_url_v1_1(self):
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2")
        cs.set_management_url("blabla")
        self.assertEqual("blabla", cs.client.management_url)

    def test_client_get_reset_timings_v1_1(self):
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2")
        self.assertEqual(0, len(cs.get_timings()))
        cs.client.times.append("somevalue")
        self.assertEqual(1, len(cs.get_timings()))
        self.assertEqual("somevalue", cs.get_timings()[0])

        cs.reset_timings()
        self.assertEqual(0, len(cs.get_timings()))

    @mock.patch('novaclient.client.HTTPClient')
    def test_contextmanager_v1_1(self, mock_http_client):
        fake_client = mock.Mock()
        mock_http_client.return_value = fake_client
        with novaclient.client.Client("2", "user", "password", "project_id",
                                      auth_url="foo/v2"):
            pass
        self.assertTrue(fake_client.open_session.called)
        self.assertTrue(fake_client.close_session.called)

    def test_client_with_password_in_args_and_kwargs(self):
        # check that TypeError is not raised during instantiation of Client
        cs = novaclient.client.Client("2", "user", "password", "project_id",
                                      password='pass')
        self.assertEqual('pass', cs.client.password)

    def test_get_password_simple(self):
        cs = novaclient.client.HTTPClient("user", "password", "", "")
        cs.password_func = mock.Mock()
        self.assertEqual("password", cs._get_password())
        self.assertFalse(cs.password_func.called)

    def test_get_password_none(self):
        cs = novaclient.client.HTTPClient("user", None, "", "")
        self.assertIsNone(cs._get_password())

    def test_get_password_func(self):
        cs = novaclient.client.HTTPClient("user", None, "", "")
        cs.password_func = mock.Mock(return_value="password")
        self.assertEqual("password", cs._get_password())
        cs.password_func.assert_called_once_with()

        cs.password_func = mock.Mock()
        self.assertEqual("password", cs._get_password())
        self.assertFalse(cs.password_func.called)

    def test_auth_url_rstrip_slash(self):
        cs = novaclient.client.HTTPClient("user", "password", "project_id",
                                          auth_url="foo/v2/")
        self.assertEqual("foo/v2", cs.auth_url)

    def test_token_and_bypass_url(self):
        cs = novaclient.client.HTTPClient(None, None, None,
                                          auth_token="12345",
                                          bypass_url="compute/v100/")
        self.assertIsNone(cs.auth_url)
        self.assertEqual("12345", cs.auth_token)
        self.assertEqual("compute/v100", cs.bypass_url)
        self.assertEqual("compute/v100", cs.management_url)

    def test_service_url_lookup(self):
        service_type = 'compute'
        cs = novaclient.client.HTTPClient(None, None, None,
                                          auth_url='foo/v2',
                                          service_type=service_type)

        self.requests_mock.get('http://mgmt.example.com/compute/v5/servers')

        @mock.patch.object(cs,
                           'get_service_url',
                           return_value='http://mgmt.example.com/compute/v5')
        @mock.patch.object(cs, 'authenticate')
        def do_test(mock_auth, mock_get):

            def set_service_catalog():
                cs.service_catalog = 'catalog'

            mock_auth.side_effect = set_service_catalog
            cs.get('/servers')
            mock_get.assert_called_once_with(service_type)
            mock_auth.assert_called_once_with()

        do_test()

        self.assertEqual(1, self.requests_mock.call_count)

        self.assertEqual('/compute/v5/servers',
                         self.requests_mock.last_request.path)

    def test_bypass_url_no_service_url_lookup(self):
        bypass_url = 'http://mgmt.compute.com/v100'
        cs = novaclient.client.HTTPClient(None, None, None,
                                          auth_url='foo/v2',
                                          bypass_url=bypass_url)

        get = self.requests_mock.get('http://mgmt.compute.com/v100/servers')

        @mock.patch.object(cs, 'get_service_url')
        def do_test(mock_get):
            cs.get('/servers')
            self.assertFalse(mock_get.called)

        do_test()
        self.assertTrue(get.called_once)

    @mock.patch("novaclient.client.requests.Session")
    def test_session(self, mock_session):
        fake_session = mock.Mock()
        mock_session.return_value = fake_session
        cs = novaclient.client.HTTPClient("user", None, "", "")
        cs.open_session()
        self.assertEqual(cs._session, fake_session)
        cs.close_session()
        self.assertIsNone(cs._session)

    def test_session_connection_pool(self):
        cs = novaclient.client.HTTPClient("user", None, "",
                                          "", connection_pool=True)
        cs.open_session()
        self.assertIsNone(cs._session)
        cs.close_session()
        self.assertIsNone(cs._session)

    def test_get_session(self):
        cs = novaclient.client.HTTPClient("user", None, "", "")
        self.assertIsNone(cs._get_session("http://example.com"))

    @mock.patch("novaclient.client.requests.Session")
    def test_get_session_open_session(self, mock_session):
        fake_session = mock.Mock()
        mock_session.return_value = fake_session
        cs = novaclient.client.HTTPClient("user", None, "", "")
        cs.open_session()
        self.assertEqual(fake_session, cs._get_session("http://example.com"))

    @mock.patch("novaclient.client.requests.Session")
    @mock.patch("novaclient.client._ClientConnectionPool")
    def test_get_session_connection_pool(self, mock_pool, mock_session):
        service_url = "http://service.example.com"

        pool = mock.MagicMock()
        pool.get.return_value = "http_adapter"
        mock_pool.return_value = pool
        cs = novaclient.client.HTTPClient("user", None, "",
                                          "", connection_pool=True)
        cs._current_url = "http://current.example.com"

        session = cs._get_session(service_url)
        self.assertEqual(session, mock_session.return_value)
        pool.get.assert_called_once_with(service_url)
        mock_session().mount.assert_called_once_with(service_url,
                                                     'http_adapter')

    def test_init_without_connection_pool(self):
        cs = novaclient.client.HTTPClient("user", None, "", "")
        self.assertIsNone(cs._connection_pool)

    @mock.patch("novaclient.client._ClientConnectionPool")
    def test_init_with_proper_connection_pool(self, mock_pool):
        fake_pool = mock.Mock()
        mock_pool.return_value = fake_pool
        cs = novaclient.client.HTTPClient("user", None, "",
                                          connection_pool=True)
        self.assertEqual(cs._connection_pool, fake_pool)

    def test_log_req(self):
        self.logger = self.useFixture(
            fixtures.FakeLogger(
                format="%(message)s",
                level=logging.DEBUG,
                nuke_handlers=True
            )
        )
        cs = novaclient.client.HTTPClient("user", None, "",
                                          connection_pool=True)
        cs.http_log_debug = True
        cs.http_log_req('GET', '/foo', {'headers': {}})
        cs.http_log_req('GET', '/foo', {'headers':
                                        {'X-Auth-Token': None}})
        cs.http_log_req('GET', '/foo', {'headers':
                                        {'X-Auth-Token': 'totally_bogus'}})
        cs.http_log_req('GET', '/foo', {'headers':
                                        {'X-Foo': 'bar',
                                         'X-Auth-Token': 'totally_bogus'}})
        cs.http_log_req('GET', '/foo', {'headers': {},
                                        'data':
                                            '{"auth": {"passwordCredentials": '
                                            '{"password": "zhaoqin"}}}'})

        output = self.logger.output.split('\n')

        self.assertIn("REQ: curl -g -i '/foo' -X GET", output)
        self.assertIn(
            "REQ: curl -g -i '/foo' -X GET -H "
            '"X-Auth-Token: None"',
            output)
        self.assertIn(
            "REQ: curl -g -i '/foo' -X GET -H "
            '"X-Auth-Token: {SHA1}b42162b6ffdbd7c3c37b7c95b7ba9f51dda0236d"',
            output)
        self.assertIn(
            "REQ: curl -g -i '/foo' -X GET -H "
            '"X-Auth-Token: {SHA1}b42162b6ffdbd7c3c37b7c95b7ba9f51dda0236d"'
            ' -H "X-Foo: bar"',
            output)
        self.assertIn(
            "REQ: curl -g -i '/foo' -X GET -d "
            '\'{"auth": {"passwordCredentials": {"password":'
            ' "{SHA1}4fc49c6a671ce889078ff6b250f7066cf6d2ada2"}}}\'',
            output)

    def test_log_resp(self):
        self.logger = self.useFixture(
            fixtures.FakeLogger(
                format="%(message)s",
                level=logging.DEBUG,
                nuke_handlers=True
            )
        )

        cs = novaclient.client.HTTPClient("user", None, "",
                                          connection_pool=True)
        cs.http_log_debug = True
        text = ('{"access": {"token": {"id": "zhaoqin"}}}')
        resp = utils.TestResponse({'status_code': 200, 'headers': {},
                                   'text': text})

        cs.http_log_resp(resp)
        output = self.logger.output.split('\n')

        self.assertIn('RESP: [200] {}', output)
        self.assertIn('RESP BODY: {"access": {"token": {"id":'
                      ' "{SHA1}4fc49c6a671ce889078ff6b250f7066cf6d2ada2"}}}',
                      output)

    def test_timings(self):
        self.requests_mock.get('http://no.where')

        client = novaclient.client.HTTPClient(user='zqfan', password='')
        client._time_request("http://no.where", 'GET')
        self.assertEqual(0, len(client.times))

        client = novaclient.client.HTTPClient(user='zqfan', password='',
                                              timings=True)
        client._time_request("http://no.where", 'GET')
        self.assertEqual(1, len(client.times))
        self.assertEqual('GET http://no.where', client.times[0][0])


class SessionClientTest(utils.TestCase):

    @mock.patch.object(novaclient.client, '_log_request_id')
    def test_timings(self, mock_log_request_id):
        self.requests_mock.get('http://no.where')

        client = novaclient.client.SessionClient(session=session.Session())
        client.request("http://no.where", 'GET')
        self.assertEqual(0, len(client.times))

        client = novaclient.client.SessionClient(session=session.Session(),
                                                 timings=True)
        client.request("http://no.where", 'GET')
        self.assertEqual(1, len(client.times))
        self.assertEqual('GET http://no.where', client.times[0][0])

    @mock.patch.object(novaclient.client, '_log_request_id')
    def test_log_request_id(self, mock_log_request_id):
        self.requests_mock.get('http://no.where')
        client = novaclient.client.SessionClient(session=session.Session(),
                                                 service_name='compute')
        client.request("http://no.where", 'GET')
        mock_log_request_id.assert_called_once_with(client.logger, mock.ANY,
                                                    'compute')


class DiscoverExtensionTest(utils.TestCase):

    @mock.patch("novaclient.client._discover_via_entry_points")
    @mock.patch("novaclient.client._discover_via_contrib_path")
    @mock.patch("novaclient.client._discover_via_python_path")
    @mock.patch("novaclient.extension.Extension")
    def test_discover_all(self, mock_extension,
                          mock_discover_via_python_path,
                          mock_discover_via_contrib_path,
                          mock_discover_via_entry_points):
        def make_gen(start, end):
            def f(*args, **kwargs):
                for i in range(start, end):
                    yield "name-%s" % i, i
            return f

        mock_discover_via_python_path.side_effect = make_gen(0, 3)
        mock_discover_via_contrib_path.side_effect = make_gen(3, 5)
        mock_discover_via_entry_points.side_effect = make_gen(5, 6)

        version = novaclient.api_versions.APIVersion("2.0")

        result = novaclient.client.discover_extensions(version)

        self.assertEqual([mock.call("name-%s" % i, i) for i in range(0, 6)],
                         mock_extension.call_args_list)
        mock_discover_via_python_path.assert_called_once_with()
        mock_discover_via_contrib_path.assert_called_once_with(version)
        mock_discover_via_entry_points.assert_called_once_with()
        self.assertEqual([mock_extension()] * 6, result)

    @mock.patch("novaclient.client._discover_via_entry_points")
    @mock.patch("novaclient.client._discover_via_contrib_path")
    @mock.patch("novaclient.client._discover_via_python_path")
    @mock.patch("novaclient.extension.Extension")
    def test_discover_only_contrib(self, mock_extension,
                                   mock_discover_via_python_path,
                                   mock_discover_via_contrib_path,
                                   mock_discover_via_entry_points):
        mock_discover_via_contrib_path.return_value = [("name", "module")]

        version = novaclient.api_versions.APIVersion("2.0")

        novaclient.client.discover_extensions(version, only_contrib=True)
        mock_discover_via_contrib_path.assert_called_once_with(version)
        self.assertFalse(mock_discover_via_python_path.called)
        self.assertFalse(mock_discover_via_entry_points.called)
        mock_extension.assert_called_once_with("name", "module")
