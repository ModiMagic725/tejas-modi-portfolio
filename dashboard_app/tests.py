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
