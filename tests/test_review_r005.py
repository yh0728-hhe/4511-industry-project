"""Regression inputs for independently reviewed failure paths; no network."""
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import patch
from concurrent.futures import ThreadPoolExecutor
import sys
import unittest
sys.path.insert(0,str(Path(__file__).parents[1]/'src'))
from closed_loop.openai_backend import APISpendEnvelope,decode_as
from closed_loop.native_support import NativeBinding
from closed_loop.fixtures import request
from closed_loop.guards import CallBudget
from test_archive_transport import provider


class ReviewRegressions(unittest.TestCase):
    def test_partial_lease_write_releases_own_file(self):
        for failing in ('os.fdopen','os.fsync'):
            with self.subTest(failing=failing),TemporaryDirectory() as folder:
                path=Path(folder)/'pilot.jsonl'
                with patch('closed_loop.openai_backend.'+failing,side_effect=OSError('fixture disk failure')):
                    with self.assertRaises(OSError):APISpendEnvelope('.20',path)
                self.assertFalse(path.with_suffix('.jsonl.lock').exists())
                owner=APISpendEnvelope('.20',path);owner.close()

    def test_number_schema_accepts_integer_but_not_bool(self):
        self.assertEqual(decode_as(float,10),10.0)
        self.assertIs(type(decode_as(float,10)),float)
        with self.assertRaises(ValueError):decode_as(float,True)
        with self.assertRaises(ValueError):decode_as(int,True)

    def test_seal_or_close_also_blocks_existing_in_memory_owner(self):
        from closed_loop.guards import BudgetStopped
        sealed=APISpendEnvelope('.20');sealed.seal_completed()
        with self.assertRaisesRegex(BudgetStopped,'ALREADY_COMPLETED'):sealed.reserve(1,1)
        closed=APISpendEnvelope('.20');closed.close()
        with self.assertRaisesRegex(BudgetStopped,'OWNER_CLOSED'):closed.reserve(1,1)

    def test_miswired_live_budget_fails_before_dispatch(self):
        req=request()
        class Backend:call_budget=CallBudget(req)
        with self.assertRaisesRegex(ValueError,'same call budget'):
            NativeBinding(Backend(),CallBudget(req),None)
        NativeBinding(Backend(),Backend.call_budget,None)

    def test_shared_provider_concurrent_lookup_dispatches_once(self):
        p,_,budget,client=provider(max_requests=1)
        url='https://web.archive.org/cdx/search/cdx?url=synthetic.example/'
        with ThreadPoolExecutor(max_workers=8) as pool:
            responses=list(pool.map(lambda _:p._get(url),range(16)))
        self.assertTrue(all(r is responses[0] for r in responses))
        self.assertEqual(len(client.calls),1)
        self.assertEqual(budget.used['search'],1)


if __name__=='__main__':unittest.main()
