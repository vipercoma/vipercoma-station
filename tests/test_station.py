import gc
import os
import subprocess
import sys
import tempfile
import types
import unittest
import warnings
from pathlib import Path
from unittest.mock import patch

if os.name == "nt":
    lockmod = types.ModuleType("fcntl")
    lockmod.LOCK_EX = 1
    lockmod.LOCK_NB = 2
    lockmod.flock = lambda *args: None
    sys.modules["fcntl"] = lockmod

os.environ.setdefault('STATION_STATE_DIR', tempfile.mkdtemp(prefix='station-tests-'))
import app as station
import auth
from notes import NotesStore
import diagnostics
import wifi_admin


class StationTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.old_store = station.notes_store
        station.notes_store = NotesStore(self.temp.name)
        self.client = station.app.test_client()
        with self.client.session_transaction() as session:
            session['authenticated'] = True
            session['csrf'] = 'test-token'
        self.headers = {'X-CSRF-Token':'test-token'}

    def tearDown(self):
        station.notes_store = self.old_store
        self.temp.cleanup()

    def test_pages_and_assets(self):
        for path in ('/', '/workspace', '/login', '/static/station-effects.js', '/static/workspace.js'):
            response = self.client.get(path)
            self.assertEqual(response.status_code, 200, path)
            response.close()

    def test_removed_tools_are_unreachable(self):
        for path in ('/wifi', '/network', '/api/workspace/files', '/api/wifi/status', '/api/workspace/files/test/download'):
            self.assertEqual(self.client.get(path).status_code, 404)
        self.assertNotIn('Drop', self.client.get('/').text)

    def test_wifi_setup_requires_login_and_captive_redirects(self):
        client = station.app.test_client()
        self.assertEqual(client.get('/setup').location, '/login?next=/setup')
        self.assertEqual(client.get('/api/wifi/networks').status_code, 401)
        self.assertEqual(client.get('/generate_204').location, '/login?next=/setup')

    def test_wifi_setup_page_and_network_scan_are_authenticated(self):
        self.assertEqual(self.client.get('/setup').status_code, 200)
        with patch.object(station, 'wifi_helper', return_value=({'networks': []}, 200)) as helper:
            response = self.client.get('/api/wifi/networks')
        self.assertEqual(response.status_code, 200)
        helper.assert_called_once_with('scan')

    def test_wifi_connect_requires_csrf_and_keeps_signin_password_independent(self):
        self.assertEqual(self.client.post('/api/wifi/connect', json={'ssid': 'Home'}).status_code, 403)
        with patch.object(station, 'wifi_helper', return_value=({'ok': True}, 202)) as helper:
            response = self.client.post('/api/wifi/connect', json={'ssid': 'Home'}, headers=self.headers)
        self.assertEqual(response.status_code, 202)
        helper.assert_called_once_with('connect', {'ssid': 'Home'})
        self.assertNotIn('set-password-stdin', Path(wifi_admin.__file__).read_text())

    def test_unauthenticated_access(self):
        other = station.app.test_client()
        self.assertEqual(other.get('/api/workspace/notes').status_code, 401)
        self.assertEqual(other.get('/workspace').status_code, 302)

    def test_csrf_and_cross_site(self):
        self.assertEqual(self.client.post('/api/workspace/notes', json={'text':'hello'}).status_code, 403)
        self.assertEqual(self.client.post('/api/workspace/notes', json={'text':'hello'}, headers={**self.headers, 'Origin':'https://example.com'}).status_code, 403)

    def test_notes_persist_and_delete(self):
        self.assertEqual(self.client.post('/api/workspace/notes', json={'text':'saved'}, headers=self.headers).status_code, 201)
        notes = NotesStore(self.temp.name).listing()
        self.assertEqual(notes[0]['text'], 'saved')
        self.assertEqual(self.client.post('/api/workspace/notes/'+notes[0]['id']+'/delete', headers=self.headers).status_code, 200)
        self.assertEqual(station.notes_store.listing(), [])

    def test_note_input_and_cap(self):
        for text in ('', None, 'x'*4001):
            self.assertEqual(self.client.post('/api/workspace/notes', json={'text':text}, headers=self.headers).status_code, 400)
        for _ in range(200):
            station.notes_store.add('note')
        with self.assertRaises(ValueError):
            station.notes_store.add('overflow')

    def test_connections_close(self):
        with warnings.catch_warnings(record=True) as caught:
            warnings.simplefilter('always', ResourceWarning)
            for _ in range(20):
                station.notes_store.listing()
            gc.collect()
        self.assertFalse([w for w in caught if issubclass(w.category, ResourceWarning)])

    def test_fixed_probe_only(self):
        self.assertEqual(self.client.post('/api/diagnostics/reboot', headers=self.headers).status_code, 400)
        with patch.object(diagnostics.shutil, 'which', return_value=None):
            self.assertFalse(diagnostics.probe('addresses')['ok'])

    def test_probe_timeout(self):
        with patch.object(diagnostics.shutil, 'which', return_value='/bin/ping'), patch.object(diagnostics.subprocess, 'run', side_effect=subprocess.TimeoutExpired('ping', 6)):
            self.assertIn('timed out', diagnostics.probe('latency')['output'])

    def test_probe_arguments_and_bounds(self):
        with patch.object(diagnostics.shutil, 'which', return_value='/bin/ip'), patch.object(diagnostics.subprocess, 'run') as run:
            run.return_value = subprocess.CompletedProcess([], 0, 'x'*15000, '')
            self.assertEqual(len(diagnostics.probe('addresses')['output']), 12000)
            self.assertEqual(run.call_args.args[0], ['ip','-brief','address'])
            self.assertEqual(run.call_args.kwargs['timeout'], 6)

    def test_security_headers(self):
        response = self.client.get('/')
        self.assertEqual(response.headers['X-Frame-Options'], 'DENY')
        self.assertNotIn('unsafe-inline', response.headers['Content-Security-Policy'])

    def test_health_identifies_release(self):
        self.assertEqual(self.client.get('/healthz').json, {'status':'ok','version':'2.1.0-wifi'})

    def test_logout_clears_session(self):
        self.assertEqual(self.client.post('/logout', headers=self.headers).status_code, 200)
        self.assertEqual(self.client.get('/api/workspace/notes').status_code, 401)


class PasswordTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.patch = patch.object(auth, 'STATE', Path(self.temp.name))
        self.patch.start()

    def tearDown(self):
        self.patch.stop()
        self.temp.cleanup()

    def test_password_is_hashed(self):
        auth.set_password('test-password')
        self.assertTrue(auth.password_matches('test-password'))
        self.assertFalse(auth.password_matches('wrong-password'))
        self.assertNotIn('test-password', (auth.STATE/'password-hash').read_text())

    def test_password_migration_preserves_choice(self):
        (auth.STATE/'access-code').write_text('existing-password\n')
        auth.migrate_password()
        self.assertTrue(auth.password_matches('existing-password'))

    def test_password_validation(self):
        for value in ('', 'short', 'x'*129):
            with self.assertRaises(ValueError):
                auth.set_password(value)

    def test_login_with_chosen_password(self):
        auth.set_password('test-password')
        station.login_attempts.clear()
        client = station.app.test_client()
        client.get('/login')
        with client.session_transaction() as session:
            token = session['login_csrf']
        self.assertEqual(client.post('/login', data={'password':'test-password','login_csrf':token}).status_code, 302)
        self.assertEqual(client.get('/api/workspace/notes').status_code, 200)

    def test_login_preserves_wifi_setup_destination(self):
        auth.set_password('test-password')
        client = station.app.test_client()
        page = client.get('/login?next=/setup')
        self.assertIn('action="/login?next=/setup"', page.text)
        with client.session_transaction() as session:
            token = session['login_csrf']
        response = client.post('/login?next=/setup', data={'password':'test-password','login_csrf':token})
        self.assertEqual(response.location, '/setup')
        self.assertEqual(client.get('/setup').status_code, 200)

    def test_login_rate_limit(self):
        auth.set_password('test-password')
        station.login_attempts.clear()
        client = station.app.test_client()
        client.get('/login')
        with client.session_transaction() as session:
            token = session['login_csrf']
        for _ in range(5):
            self.assertEqual(client.post('/login', data={'password':'wrong','login_csrf':token}).status_code, 200)
        self.assertEqual(client.post('/login', data={'password':'wrong','login_csrf':token}).status_code, 429)


class WifiHelperTests(unittest.TestCase):
    def test_scan_parses_escaped_ssids_and_marks_enterprise_unsupported(self):
        output = "Home\\: Upstairs:82:WPA2\nOffice:74:WPA2 802.1X\nGuest:31:\n"
        with patch.object(wifi_admin, 'run', return_value=subprocess.CompletedProcess([], 0, output, '')):
            networks = wifi_admin.scan()
        self.assertEqual([row['ssid'] for row in networks], ['Home: Upstairs', 'Office', 'Guest'])
        self.assertFalse(networks[1]['supported'])
        self.assertEqual(networks[2]['security'], 'Open')

    def test_connect_rejects_malformed_and_enterprise_network_requests(self):
        with self.assertRaises(ValueError):
            wifi_admin.connect([])
        with self.assertRaises(ValueError):
            wifi_admin.connect({'ssid': 'Home', 'password': '', 'sync_password': True})
        with patch.object(wifi_admin, 'scan', return_value=[{
            'ssid': 'Office', 'signal': 80, 'security': 'WPA2 802.1X', 'supported': False
        }]):
            with self.assertRaisesRegex(ValueError, 'enterprise security'):
                wifi_admin.connect({'ssid': 'Office', 'password': 'irrelevant'})

    def test_failed_wifi_activation_restores_the_setup_hotspot(self):
        with tempfile.TemporaryDirectory(dir=os.environ.get('TEMP')) as directory:
            root = Path(directory)
            ident = '12345678-abcd-1234-abcd-1234567890ab'
            profile = root / f'vipercoma-wifi-{ident}.nmconnection'
            profile.write_text('private test profile')
            pending = root / 'pending'
            pending.write_text(ident + '\n9999999999\n')

            def fake_run(args, **kwargs):
                if args[1:4] == ['--wait', '60', 'connection']:
                    raise RuntimeError('target network unavailable')
                if args[1:3] == ['connection', 'delete']:
                    profile.unlink(missing_ok=True)
                return subprocess.CompletedProcess(args, 0, '', '')

            with patch.object(wifi_admin, 'WIFI_DIR', root), \
                 patch.object(wifi_admin, 'PENDING', pending), \
                 patch.object(wifi_admin, 'ap_uuid', return_value='setup-ap-uuid'), \
                 patch.object(wifi_admin, 'run', side_effect=fake_run) as run:
                wifi_admin.activate(ident)

            commands = [call.args[0] for call in run.call_args_list]
            self.assertEqual(len(commands), 4)
            self.assertEqual(commands[2][1:3], ['connection', 'delete'])
            self.assertEqual(commands[-1][-5:], ['up', 'uuid', 'setup-ap-uuid', 'ifname', 'wlan0'])
            self.assertFalse(profile.exists())
            self.assertFalse(pending.exists())


if __name__ == '__main__':
    unittest.main()
