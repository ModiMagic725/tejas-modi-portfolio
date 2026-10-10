import socket
import smtplib
from unittest import mock

from django.core import mail
from django.core.cache import cache
from django.test import TestCase, override_settings

from .models import ContactMessage

VALID = {'name': 'Test User', 'email': 'visitor@example.com', 'subject': 'Hello',
         'project_type': 'website', 'message': 'I need a website.'}
URL = '/api/contact/'


@override_settings(EMAIL_BACKEND='django.core.mail.backends.locmem.EmailBackend',
                   EMAIL_HOST_USER='owner@example.com')
class ContactSubmitTests(TestCase):
    def setUp(self):
        cache.clear()

    def test_success_saves_and_sends_both_emails(self):
        r = self.client.post(URL, VALID)
        self.assertEqual(r.status_code, 200)
        self.assertTrue(r.json()['ok'])
        self.assertTrue(r.json()['email_sent'])
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(len(mail.outbox), 2)

    def test_smtp_timeout_still_reports_saved(self):
        with mock.patch('dashboard_app.views.send_mail', side_effect=socket.timeout('timed out')) as m:
            with self.assertLogs('dashboard_app.views', level='ERROR') as logs:
                r = self.client.post(URL, VALID)
        self.assertEqual(r.status_code, 200)
        body = r.json()
        self.assertTrue(body['ok'])
        self.assertFalse(body['email_sent'])
        self.assertIn('received successfully', body['message'])
        self.assertEqual(ContactMessage.objects.count(), 1)
        self.assertEqual(m.call_count, 1)  # visitor email skipped -> no second timeout wait
        self.assertIn('timeout', ''.join(logs.output).lower())

    def test_smtp_auth_error_does_not_leak_or_fail(self):
        err = smtplib.SMTPAuthenticationError(535, b'Username and Password not accepted')
        with mock.patch('dashboard_app.views.send_mail', side_effect=err):
            with self.assertLogs('dashboard_app.views', level='ERROR'):
                r = self.client.post(URL, VALID)
        self.assertTrue(r.json()['ok'])
        self.assertFalse(r.json()['email_sent'])
        self.assertEqual(ContactMessage.objects.count(), 1)

    def test_database_failure_returns_500(self):
        with mock.patch('dashboard_app.views.ContactMessage.objects.create', side_effect=Exception('db down')):
            with self.assertLogs('dashboard_app.views', level='ERROR'):
                r = self.client.post(URL, VALID)
        self.assertEqual(r.status_code, 500)
        self.assertFalse(r.json()['ok'])
        self.assertEqual(len(mail.outbox), 0)

    def test_validation_unchanged(self):
        r = self.client.post(URL, {**VALID, 'email': 'bad'})
        self.assertEqual(r.status_code, 400)
        self.assertIn('email', r.json()['errors'])
        self.assertEqual(ContactMessage.objects.count(), 0)

    def test_honeypot_unchanged(self):
        r = self.client.post(URL, {**VALID, 'website': 'spam.com'})
        self.assertEqual(r.json(), {'ok': True})
        self.assertEqual(ContactMessage.objects.count(), 0)


class EmailTimeoutSetting(TestCase):
    def test_timeout_is_set(self):
        from django.conf import settings
        self.assertEqual(settings.EMAIL_TIMEOUT, 10)


class BrevoBackendTests(TestCase):
    def _backend(self, key='test-key'):
        from dashboard_app.email_backends import BrevoAPIEmailBackend
        with override_settings(BREVO_API_KEY=key, EMAIL_TIMEOUT=7):
            return BrevoAPIEmailBackend()

    def _fake_response(self):
        resp = mock.MagicMock()
        resp.__enter__.return_value = resp
        resp.read.return_value = b'{"messageId":"x"}'
        return resp

    def test_sends_json_over_https_with_key_and_timeout(self):
        import json
        from django.core.mail import EmailMessage
        backend = self._backend()
        msg = EmailMessage('Hi', 'Body text', 'Tejas <owner@example.com>', ['v@example.com'], connection=backend)
        msg.attach('brief.pdf', b'%PDF-data', 'application/pdf')
        with mock.patch('urllib.request.urlopen', return_value=self._fake_response()) as up:
            self.assertEqual(msg.send(), 1)
        req = up.call_args[0][0]
        self.assertEqual(req.full_url, 'https://api.brevo.com/v3/smtp/email')
        self.assertEqual(req.get_header('Api-key'), 'test-key')
        self.assertEqual(up.call_args[1]['timeout'], 7)
        body = json.loads(req.data)
        self.assertEqual(body['sender'], {'email': 'owner@example.com', 'name': 'Tejas'})
        self.assertEqual(body['to'], [{'email': 'v@example.com'}])
        self.assertEqual(body['textContent'], 'Body text')
        self.assertEqual(body['attachment'][0]['name'], 'brief.pdf')

    def test_http_error_raises_without_leaking_key(self):
        import io, urllib.error
        from django.core.mail import EmailMessage
        from dashboard_app.email_backends import BrevoAPIError
        backend = self._backend('SECRET-KEY-123')
        err = urllib.error.HTTPError('u', 401, 'Unauthorized', {}, io.BytesIO(b'{"message":"Key not found"}'))
        with mock.patch('urllib.request.urlopen', side_effect=err):
            with self.assertRaises(BrevoAPIError) as cm:
                EmailMessage('s', 'b', 'o@example.com', ['v@example.com'], connection=backend).send()
        self.assertIn('401', str(cm.exception))
        self.assertNotIn('SECRET-KEY-123', str(cm.exception))

    def test_missing_key_raises(self):
        from django.core.mail import EmailMessage
        from dashboard_app.email_backends import BrevoAPIError
        backend = self._backend('')
        with self.assertRaises(BrevoAPIError):
            EmailMessage('s', 'b', 'o@example.com', ['v@example.com'], connection=backend).send()

    @override_settings(EMAIL_BACKEND='dashboard_app.email_backends.BrevoAPIEmailBackend',
                       BREVO_API_KEY='k', EMAIL_HOST_USER='owner@example.com')
    def test_contact_view_still_saves_when_brevo_fails(self):
        cache.clear()
        with mock.patch('urllib.request.urlopen', side_effect=OSError('Network is unreachable')):
            with self.assertLogs('dashboard_app.views', level='ERROR'):
                r = self.client.post(URL, VALID)
        self.assertTrue(r.json()['ok'])
        self.assertFalse(r.json()['email_sent'])
        self.assertEqual(ContactMessage.objects.count(), 1)
