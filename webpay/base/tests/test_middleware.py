import json

from django import http
from django.conf import settings
from django.test import TestCase
from django.test.client import RequestFactory
from django.test.utils import override_settings

import fudge
import mock
from nose.tools import eq_, ok_

from webpay.base.middleware import (CEFMiddleware, CSPMiddleware,
                                    LocaleMiddleware, LogJSONerror)


class TestLocaleMiddleware(TestCase):

    def process(self, **request_kw):
        loc = LocaleMiddleware()
        req = RequestFactory().get('/', **request_kw)
        loc.process_request(req)
        resp = http.HttpResponse('output')
        loc.process_response(req, resp)
        return req.locale, resp

    def test_accept_exact(self):
        with self.settings(LANGUAGE_CODE='ja'):
            eq_(self.process(HTTP_ACCEPT_LANGUAGE='en-us')[0], 'en-US')

    @fudge.patch('tower.activate')
    def test_activate_tower(self, fake_activate):
        fake_activate.expects_call()
        self.process(HTTP_ACCEPT_LANGUAGE='en-us')

    def test_accept_prefix(self):
        with self.settings(LANGUAGE_CODE='ja'):
            eq_(self.process(HTTP_ACCEPT_LANGUAGE='en')[0], 'en-US')

    def test_accept_first_prefix_wins(self):
        # See bug 439568.
        eq_(self.process(HTTP_ACCEPT_LANGUAGE='en,ja;q=0.9,fr;q=0.8,de;'
                                              'q=0.7,es;q=0.6,it;q=0.5,nl;'
                                              'q=0.4,sv;q=0.3,nb;q=0.2')[0],
            'en-US')

    def test_accept_not_supported(self):
        eq_(self.process(HTTP_ACCEPT_LANGUAGE='foo')[0],
            settings.LANGUAGE_CODE)

    def test_accept_varies_cache(self):
        locale, resp = self.process(HTTP_ACCEPT_LANGUAGE='en-us')
        eq_(resp['Vary'], 'Accept-Language')

    def test_default_to_lang_code(self):
        with self.settings(LANGUAGE_CODE='de'):
            eq_(self.process(HTTP_ACCEPT_LANGUAGE='foo')[0], 'de')

    def test_lang_exact(self):
        with self.settings(LANGUAGE_CODE='ja'):
            eq_(self.process(data=dict(lang='en-us'))[0], 'en-US')

    def test_lang_wrong_suffix(self):
        with self.settings(LANGUAGE_CODE='ja'):
            eq_(self.process(data=dict(lang='en-xx'))[0], 'en-US')

    def test_lang_prefix(self):
        with self.settings(LANGUAGE_CODE='ja'):
            eq_(self.process(data=dict(lang='en'))[0], 'en-US')

    def test_lang_non_existant(self):
        eq_(self.process(data=dict(lang='xx'))[0], settings.LANGUAGE_CODE)

    def test_no_input(self):
        eq_(self.process()[0], settings.LANGUAGE_CODE)


class ExcWithContent(Exception):

    def __init__(self, msg, content):
        Exception.__init__(self, msg)
        self.content = content


class TestLogJSONerror(TestCase):

    def test_json(self):
        err = LogJSONerror()
        exc = ExcWithContent('msg', json.dumps({'foo': 'bar'}))
        err.process_exception(None, exc)

    def test_not_json(self):
        err = LogJSONerror()
        err.process_exception(None, ExcWithContent('msg', '}]not valid JSON'))


@mock.patch('webpay.base.middleware.log_cef')
class TestCEFMiddleware(TestCase):

    def test_request(self, log_cef):
        self.client.get('/')
        assert log_cef.called

    def test_request_with_content(self, log_cef):
        exc = ExcWithContent('msg', 'foo')
        CEFMiddleware().process_exception(None, exc)
        log_cef.assert_called_with('ExcWithContent', None, severity=8)


class TestCSPMiddleware(TestCase):
    # Override the setting so it gets reset
    @override_settings(SPARTACUS_STATIC='',
                       STATIC_URL='http://webpay.dev/media/')
    def test_without_spartacus(self):
        del settings.SPARTACUS_STATIC
        middleware = CSPMiddleware()
        sources = middleware.get_sources()
        eq_(sources, ('http://webpay.dev',))

    @override_settings(SPARTACUS_STATIC='http://spartacus.dev/media/',
                       STATIC_URL='http://webpay.dev/media/')
    def test_with_spartacus(self):
        middleware = CSPMiddleware()
        sources = middleware.get_sources()
        eq_(set(sources), set(['http://webpay.dev', 'http://spartacus.dev']))

    @override_settings(SPARTACUS_STATIC='http://webpay.dev/media/',
                       STATIC_URL='http://webpay.dev/media/')
    def test_spartacus_and_static_match(self):
        middleware = CSPMiddleware()
        sources = middleware.get_sources()
        eq_(sources, ('http://webpay.dev',))

    @mock.patch('webpay.base.middleware.CSPMiddleware.get_sources')
    def test_get_sources_is_used(self, get_sources):
        stubbed_source = 'I totally get used'
        get_sources.return_value = (stubbed_source,)
        response = self.client.get('/')
        csp = response['content-security-policy']
        ok_(stubbed_source in csp)
