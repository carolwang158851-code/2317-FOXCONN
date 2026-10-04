from __future__ import annotations

import hashlib
import json
import sys
import tempfile
import unittest
from pathlib import Path
from unittest import mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / 'tools'))
import p1008_app_server as app


class FreshRefreshTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name)
        self.current = {'jobId': 'old-job', 'jobType': 'default', 'status': 'SUCCEEDED',
                        'steps': [], 'errors': []}
        self.write_state(self.current)
        staging = self.root / 'staging/2026-10-04'
        staging.mkdir(parents=True)
        (staging / 'DRY_RUN.json').write_text(json.dumps({
            'candidateDate': '2026-10-04', 'generatedFiles': [],
            'noPublishRequired': True, 'alreadyPublishedTargets': ['data/macro_snapshot.csv']
        }), encoding='utf-8')
        (self.root / 'data').mkdir()
        (self.root / 'data/macro_snapshot.csv').write_bytes(b'Date,VIX\n2026-10-04,16\n')
        self.manager = app.P1008JobManager(self.root)
        self.catalog = mock.patch.object(app.quarterly_editorial, 'quarterly_editorial_catalog',
                                         return_value={'reports': []})
        self.catalog.start()
        self.addCleanup(self.catalog.stop)

    def write_state(self, payload):
        path = self.root / app.STATE_REL
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(payload), encoding='utf-8')

    def publish_completed(self):
        self.current.update(jobId='owner-publish-completed', jobType='owner-publish',
                            formalCsvModified=True)
        self.write_state(self.current)

    def identities(self):
        return {str(p.relative_to(self.root)): hashlib.sha256(p.read_bytes()).hexdigest()
                for p in self.root.rglob('*') if p.is_file()}

    def test_post_publish_reload_without_restart(self):
        instance = self.manager.server_instance_id
        self.publish_completed()
        self.assertEqual(self.manager.snapshot()['jobId'], 'old-job')
        payload = self.manager.refresh_payload()
        self.assertEqual(payload['app']['jobId'], 'owner-publish-completed')
        self.assertEqual(payload['app']['serverInstanceId'], instance)
        self.assertEqual(payload['stateSource'], 'DISK')

    def test_zero_targets_no_action_review_schema(self):
        self.publish_completed()
        result = self.manager.refresh_payload()
        self.assertEqual(result['review']['generatedFiles'], [])
        self.assertTrue(result['review']['readiness']['noActionRequired'])
        self.assertFalse(result['review']['formalPublishRequired'])
        self.assertEqual(result['review']['status'], 'READY')

    def test_repeated_refresh_idempotent(self):
        first = self.manager.refresh_payload()
        self.assertEqual(self.manager.refresh_payload(), first)

    def test_refresh_never_publishes(self):
        with mock.patch.object(self.manager, 'start_owner_publish') as publish:
            self.manager.refresh_payload()
            publish.assert_not_called()

    def test_refresh_never_updates_data(self):
        with mock.patch.object(self.manager, 'start_job') as job:
            self.manager.refresh_payload()
            job.assert_not_called()

    def test_refresh_never_writes_csv_or_runtime(self):
        before = self.identities()
        with mock.patch.object(self.manager, '_persist_locked') as persist, \
             mock.patch.object(app, 'write_json') as write:
            self.manager.refresh_payload()
            self.manager.refresh_payload()
            persist.assert_not_called()
            write.assert_not_called()
        self.assertEqual(self.identities(), before)

    def test_genuine_publish_failure_preserved(self):
        self.current.update(jobType='owner-publish', status='FAILED', errors=['Publisher rejected schema'])
        self.write_state(self.current)
        payload = self.manager.refresh_payload()
        self.assertEqual(payload['app']['status'], 'FAILED')
        self.assertEqual(payload['app']['errors'], ['Publisher rejected schema'])
        self.assertFalse(payload['app']['launcherGate']['canEnterNewUi'])

    def test_missing_current_state_fails_closed(self):
        (self.root / app.STATE_REL).unlink()
        with self.assertRaisesRegex(ValueError, 'is missing'):
            self.manager.refresh_payload()

    def test_corrupt_current_state_fails_closed(self):
        (self.root / app.STATE_REL).write_text('{broken', encoding='utf-8')
        with self.assertRaises(json.JSONDecodeError):
            self.manager.refresh_payload()

    def test_invalid_current_state_schema_fails_closed(self):
        for payload in ([], {}, {'status': 'SUCCEEDED', 'steps': None},
                        {'status': 'SUCCEEDED', 'errors': 'invalid'}):
            with self.subTest(payload=payload):
                self.write_state(payload)
                with self.assertRaisesRegex(ValueError, 'schema'):
                    self.manager.refresh_payload()

    def test_active_worker_not_overwritten(self):
        self.publish_completed()
        self.manager.active_thread = mock.Mock()
        self.manager.active_thread.is_alive.return_value = True
        payload = self.manager.refresh_payload()
        self.assertEqual(payload['stateSource'], 'ACTIVE_JOB')
        self.assertEqual(payload['app']['jobId'], 'old-job')

    def test_missing_review_artifact_remains_fail_closed(self):
        (self.root / 'staging/2026-10-04/DRY_RUN.json').unlink()
        payload = self.manager.refresh_payload()
        self.assertEqual(payload['review']['status'], 'ERROR')
        self.assertTrue(payload['review']['formalPublishBlocked'])
        self.assertFalse(payload['app']['launcherGate']['canEnterNewUi'])


if __name__ == '__main__':
    unittest.main()
