# -*- encoding: utf-8 -*-
# pylint: skip-file
from __future__ import absolute_import

from .mock import _all_auth_mock_
from .mock import public_incursion
from .mock import public_incursion_no_expires
from .mock import public_incursion_no_expires_second
from .mock import public_incursion_server_error
from .mock import public_incursion_warning
from .mock import public_incursion_expired
from esipy import App
from esipy import EsiClient
from esipy import EsiSecurity
from esipy.cache import BaseCache
from esipy.cache import DictCache
from esipy.cache import DummyCache

from requests.adapters import HTTPAdapter
from requests.exceptions import ConnectionError

import httmock
import mock
import six
import time
import unittest
import warnings

import logging
# set pyswagger logger to error, as it displays too much thing for test needs
pyswagger_logger = logging.getLogger('pyswagger')
pyswagger_logger.setLevel(logging.ERROR)


class TestEsiPy(unittest.TestCase):
    CALLBACK_URI = "https://foo.bar/baz/callback"
    LOGIN_EVE = "https://login.eveonline.com"
    OAUTH_VERIFY = "%s/oauth/verify" % LOGIN_EVE
    OAUTH_TOKEN = "%s/oauth/token" % LOGIN_EVE
    CLIENT_ID = 'foo'
    SECRET_KEY = 'bar'
    BASIC_TOKEN = six.u('Zm9vOmJhcg==')
    SECURITY_NAME = 'evesso'

    @mock.patch('six.moves.urllib.request.urlopen')
    def setUp(self, urlopen_mock):
        # I hate those mock... thx urlopen instead of requests...
        urlopen_mock.return_value = open('test/resources/swagger.json')

        self.app = App.create(
            'https://esi.tech.ccp.is/latest/swagger.json'
        )

        self.security = EsiSecurity(
            app=self.app,
            redirect_uri=TestEsiPy.CALLBACK_URI,
            client_id=TestEsiPy.CLIENT_ID,
            secret_key=TestEsiPy.SECRET_KEY,
        )

        self.cache = DictCache()
        self.client = EsiClient(self.security, cache=self.cache)
        self.client_no_auth = EsiClient(cache=self.cache, retry_requests=True)

    def tearDown(self):
        """ clear the cache so we don't have residual data """
        self.cache._dict = {}

    def test_esipy_client_no_args(self):
        client_no_args = EsiClient()
        self.assertIsNone(client_no_args.security)
        self.assertTrue(isinstance(client_no_args.cache, DictCache))
        self.assertEqual(
            client_no_args._session.headers['User-Agent'],
            'EsiPy/Client - https://github.com/Kyria/EsiPy'
        )
        self.assertEqual(client_no_args.raw_body_only, False)

    def test_esipy_client_with_headers(self):
        client_with_headers = EsiClient(headers={'User-Agent': 'foobar'})
        self.assertEqual(
            client_with_headers._session.headers['User-Agent'],
            'foobar'
        )

    def test_esipy_client_with_adapter(self):
        transport_adapter = HTTPAdapter()
        client_with_adapters = EsiClient(
            transport_adapter=transport_adapter
        )
        self.assertEqual(
            client_with_adapters._session.get_adapter('http://'),
            transport_adapter
        )
        self.assertEqual(
            client_with_adapters._session.get_adapter('https://'),
            transport_adapter
        )

    def test_esipy_client_without_cache(self):
        client_without_cache = EsiClient(cache=None)
        self.assertTrue(isinstance(client_without_cache.cache, DummyCache))

    def test_esipy_client_with_cache(self):
        cache = DictCache()
        client_with_cache = EsiClient(cache=cache)
        self.assertTrue(isinstance(client_with_cache.cache, BaseCache))
        self.assertEqual(client_with_cache.cache, cache)

    def test_esipy_client_wrong_cache(self):
        with self.assertRaises(ValueError):
            EsiClient(cache=DictCache)

    def test_esipy_request_public(self):
        with httmock.HTTMock(public_incursion):
            incursions = self.client_no_auth.request(
                self.app.op['get_incursions']()
            )
            self.assertEqual(incursions.data[0].type, 'Incursion')
            self.assertEqual(incursions.data[0].faction_id, 500019)

    def test_esipy_request_authed(self):
        with httmock.HTTMock(*_all_auth_mock_):
            self.security.auth('let it bee')
            char_location = self.client.request(
                self.app.op['get_characters_character_id_location'](
                    character_id=123456789
                )
            )
            self.assertEqual(char_location.data.station_id, 60004756)

            # force expire
            self.security.token_expiry = 0
            char_location_with_refresh = self.client.request(
                self.app.op['get_characters_character_id_location'](
                    character_id=123456789
                )
            )
            self.assertEqual(
                char_location_with_refresh.data.station_id,
                60004756
            )

    def test_client_cache_request(self):
        @httmock.all_requests
        def fail_if_request(url, request):
            self.fail('Cached data is not supposed to do requests')

        incursion_operation = self.app.op['get_incursions']

        with httmock.HTTMock(public_incursion_no_expires):
            incursions = self.client_no_auth.request(incursion_operation())
            self.assertEqual(incursions.data[0].state, 'mobilizing')

        with httmock.HTTMock(public_incursion_no_expires_second):
            incursions = self.client_no_auth.request(incursion_operation())
            self.assertEqual(incursions.data[0].state, 'established')

        with httmock.HTTMock(public_incursion):
            incursions = self.client_no_auth.request(incursion_operation())
            self.assertEqual(incursions.data[0].state, 'mobilizing')

        with httmock.HTTMock(fail_if_request):
            incursions = self.client_no_auth.request(incursion_operation())
            self.assertEqual(incursions.data[0].state, 'mobilizing')

    def test_client_warning_header(self):
        with httmock.HTTMock(public_incursion_warning):
            warnings.simplefilter('error')
            incursion_operation = self.app.op['get_incursions']

            with self.assertRaises(UserWarning):
                self.client_no_auth.request(incursion_operation())

    def test_client_raw_body_only(self):
        client = EsiClient(raw_body_only=True)
        self.assertEqual(client.raw_body_only, True)

        with httmock.HTTMock(public_incursion):
            incursions = client.request(self.app.op['get_incursions']())
            self.assertIsNone(incursions.data)
            self.assertTrue(len(incursions.raw) > 0)

            incursions = client.request(
                self.app.op['get_incursions'](),
                raw_body_only=False
            )
            self.assertIsNotNone(incursions.data)

    def test_esipy_reuse_operation(self):
        operation = self.app.op['get_incursions']()
        with httmock.HTTMock(public_incursion):
            incursions = self.client_no_auth.request(operation)
            self.assertEqual(incursions.data[0].faction_id, 500019)

            # this shouldn't create any errors
            incursions = self.client_no_auth.request(operation)
            self.assertEqual(incursions.data[0].faction_id, 500019)

    def test_esipy_multi_request(self):
        operation = self.app.op['get_incursions']()

        with httmock.HTTMock(public_incursion):
            count = 0
            for req, incursions in self.client_no_auth.multi_request(
                    [operation, operation, operation], threads=2):
                self.assertEqual(incursions.data[0].faction_id, 500019)
                count += 1

            # Check we made 3 requests
            self.assertEqual(count, 3)

    def test_esipy_backoff(self):
        operation = self.app.op['get_incursions']()

        start_calls = time.time()

        with httmock.HTTMock(public_incursion_server_error):
            incursions = self.client_no_auth.request(operation)
            self.assertEqual(incursions.data.error, 'broke')

        end_calls = time.time()

        # Check we retried 5 times
        self.assertEqual(incursions.data.count, 5)

        # Check that backoff slept for a sum > 2 seconds
        self.assertTrue(end_calls - start_calls > 2)

    def test_esipy_timeout(self):
        def send_function(*args, **kwargs):
            """ manually create a ConnectionError to test the retry and be sure
            no exception is thrown """
            send_function.count += 1
            raise ConnectionError
        send_function.count = 0

        self.client_no_auth._session.send = mock.MagicMock(
            side_effect=send_function
        )

        operation = self.app.op['get_incursions']()
        with httmock.HTTMock(public_incursion):
            incursions = self.client_no_auth.request(operation)
            # there shouldn't be any exceptions

        self.assertEqual(incursions.status, 500)
        self.assertEqual(send_function.count, 5)

    def test_esipy_expired_response(self):
        operation = self.app.op['get_incursions']

        with httmock.HTTMock(public_incursion_expired):
            warnings.filterwarnings('error', '.*returned expired result')

            with self.assertRaises(UserWarning):
                self.client_no_auth.request(operation())

            warnings.resetwarnings()
            warnings.simplefilter('ignore')
            incursions = self.client_no_auth.request(operation())
            self.assertEquals(incursions.status, 200)
