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


# ---------------------------------------------------------------- Backend project: showcase PDF (full look)
import shutil
import tempfile

from django.core.files.uploadedfile import SimpleUploadedFile

from .models import AdminUser, BackendProject

PDF_BYTES = b'%PDF-1.4\n1 0 obj\n<<>>\nendobj\ntrailer\n<<>>\n%%EOF\n'
_TMP_MEDIA = tempfile.mkdtemp()


@override_settings(MEDIA_ROOT=_TMP_MEDIA, ALLOWED_HOSTS=['testserver'])
class BackendShowcasePdfTests(TestCase):
    @classmethod
    def tearDownClass(cls):
        super().tearDownClass()
        shutil.rmtree(_TMP_MEDIA, ignore_errors=True)

    def setUp(self):
        cache.clear()
        admin = AdminUser(full_name='Tester', email='t@example.com')
        admin.set_password('pass12345!')
        admin.save()
        session = self.client.session
        session['user_id'] = admin.id
        session['role'] = 'admin'
        session.save()

    def _form(self, **extra):
        data = {'title': 'Test System', 'short_description': 'Short', 'description': 'Long text',
                'category': 'management', 'is_published': 'on'}
        data.update(extra)
        return data

    def _pdf(self, name):
        return SimpleUploadedFile(name, PDF_BYTES, content_type='application/pdf')

    def test_add_with_showcase_pdf_and_public_preview(self):
        r = self.client.post('/admin-panel/backend/add/', self._form(
            showcase_pdf=self._pdf('look.pdf'), allow_showcase_download='on'))
        self.assertEqual(r.status_code, 302)
        p = BackendProject.objects.get()
        self.assertTrue(p.showcase_pdf)
        self.assertFalse(p.documentation_pdf)       # dono PDFs alag hain

        pub = self.client.get(f'/docs/backend/{p.slug}/showcase/')
        self.assertEqual(pub.status_code, 200)
        self.assertEqual(pub['Content-Type'], 'application/pdf')
        self.assertNotIn('attachment', pub.get('Content-Disposition', ''))
        # documentation URL par showcase file nahi milti
        self.assertEqual(self.client.get(f'/docs/backend/{p.slug}/').status_code, 404)

    def test_download_toggle_blocks_download_but_not_preview(self):
        self.client.post('/admin-panel/backend/add/', self._form(showcase_pdf=self._pdf('look.pdf')))   # allow_showcase_download off
        p = BackendProject.objects.get()
        self.assertFalse(p.allow_showcase_download)
        self.assertEqual(self.client.get(f'/docs/backend/{p.slug}/showcase/').status_code, 200)
        self.assertEqual(self.client.get(f'/docs/backend/{p.slug}/showcase/?download=1').status_code, 404)

        r = self.client.post(f'/admin-panel/backend/toggle-showcase-download/{p.id}/')
        self.assertEqual(r.status_code, 302)
        p.refresh_from_db()
        self.assertTrue(p.allow_showcase_download)
        dl = self.client.get(f'/docs/backend/{p.slug}/showcase/?download=1')
        self.assertEqual(dl.status_code, 200)
        self.assertIn('attachment', dl['Content-Disposition'])

    def test_unpublished_or_missing_showcase_is_404(self):
        self.client.post('/admin-panel/backend/add/', self._form())
        p = BackendProject.objects.get()
        self.assertEqual(self.client.get(f'/docs/backend/{p.slug}/showcase/').status_code, 404)
        p.showcase_pdf = self._pdf('x.pdf')
        p.is_published = False
        p.save()
        self.assertEqual(self.client.get(f'/docs/backend/{p.slug}/showcase/').status_code, 404)

    def test_fake_pdf_rejected(self):
        fake = SimpleUploadedFile('look.pdf', b'not really a pdf', content_type='application/pdf')
        r = self.client.post('/admin-panel/backend/add/', self._form(showcase_pdf=fake))
        self.assertEqual(r.status_code, 200)                   # form wapas, error ke saath
        self.assertEqual(BackendProject.objects.count(), 0)

    def test_edit_replace_and_remove_showcase(self):
        self.client.post('/admin-panel/backend/add/', self._form(showcase_pdf=self._pdf('a.pdf')))
        p = BackendProject.objects.get()
        first = p.showcase_pdf.name
        # edit without a file keeps it
        self.client.post(f'/admin-panel/backend/edit/{p.id}/', self._form())
        p.refresh_from_db()
        self.assertEqual(p.showcase_pdf.name, first)
        # replace
        self.client.post(f'/admin-panel/backend/edit/{p.id}/', self._form(showcase_pdf=self._pdf('b.pdf')))
        p.refresh_from_db()
        self.assertNotEqual(p.showcase_pdf.name, first)
        # remove
        self.client.post(f'/admin-panel/backend/edit/{p.id}/', self._form(remove_showcase='on'))
        p.refresh_from_db()
        self.assertFalse(p.showcase_pdf)

    def test_public_and_dashboard_pages_render(self):
        self.client.post('/admin-panel/backend/add/', self._form(showcase_pdf=self._pdf('a.pdf'), is_featured='on'))
        p = BackendProject.objects.get()
        page = self.client.get('/backend-projects/')
        self.assertEqual(page.status_code, 200)
        self.assertContains(page, f'/docs/backend/{p.slug}/showcase/')
        self.assertContains(self.client.get('/'), 'View full look')
        self.assertContains(self.client.get('/admin-panel/backend/'), 'Showcase PDF')
        self.assertContains(self.client.get('/admin-panel/backend/add/'), 'name="showcase_pdf"')
        self.assertContains(self.client.get(f'/admin-panel/backend/edit/{p.id}/'), 'remove_showcase')
