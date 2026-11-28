"""Offline pointer planning; no archive text or proof is admitted."""
from dataclasses import FrozenInstanceError
from datetime import datetime,timezone,timedelta
import json
import unittest
from closed_loop.commoncrawl_index import parse_commoncrawl_index

URL='https://sample.com/'
CUTOFF=datetime(2024,4,4,23,59,59,tzinfo=timezone.utc)
COLLECTION='CC-MAIN-2024-10'


def row(**changes):
    value=dict(url=URL,status='200',mime='text/html',timestamp='20240302075821',
        digest='A'*32,length='3598',offset='615755361',
        filename='crawl-data/CC-MAIN-2024-10/segments/1707947475757.50/warc/CC-MAIN-20240302052634-20240302082634-00381.warc.gz')
    value.update(changes);return value


def body(*rows):return ('\n'.join(json.dumps(r) for r in rows)).encode()


def parse(raw=None,**changes):
    args=dict(requested_url=URL,as_of=CUTOFF,collection=COLLECTION)
    args.update(changes)
    return parse_commoncrawl_index(body(row()) if raw is None else raw,**args)


class CommonCrawlIndexTests(unittest.TestCase):
    def test_valid_pointer_generates_exact_range_but_never_source_proof(self):
        scan=parse();pointer=scan.pointers[0]
        self.assertEqual(pointer.range_header,'bytes=615755361-615758958')
        self.assertEqual(pointer.data_url,'https://data.commoncrawl.org/'+row()['filename'])
        self.assertFalse(pointer.source_admission_allowed)
        self.assertTrue(pointer.requires_body_verification)
        self.assertFalse(scan.source_admission_allowed)
        self.assertFalse(hasattr(pointer,'text'))
        with self.assertRaises(FrozenInstanceError):pointer.length=1
    def test_only_empty_homepage_path_is_normalized(self):
        self.assertEqual(len(parse(body(row(url='https://sample.com')),requested_url=URL).pointers),1)
        for url in ('http://sample.com/','https://www.sample.com/','https://other.com/'):
            scan=parse(body(row(url=url)))
            self.assertFalse(scan.pointers);self.assertEqual(scan.rejected_reason_counts,{'URL_MISMATCH':1})
    def test_unsafe_requested_urls_fail_before_any_rows(self):
        for url in ('file:///x','https://u@sample.com/','https://sample.com:443/',
            'https://sample.com/path','https://sample.com/?','https://sample.com/#',
            'https://sample.com/%2f','https://sample.com\\evil','https://127.0.0.1/',
            'https://[::1]/','https://foo.local/','https://localhost/',
            ' https://sample.com/','https://SAMPLE.com/'):
            with self.subTest(url=url):
                with self.assertRaises(ValueError):parse(requested_url=url)
    def test_future_capture_is_rejected_instead_of_becoming_a_fact(self):
        scan=parse(body(row(timestamp='20240405000000')))
        self.assertEqual(scan.rejected_reason_counts,{'AFTER_CUTOFF':1})
        self.assertEqual(scan.raw_record_count,1);self.assertFalse(scan.pointers)
    def test_utc_equivalent_cutoff_and_exact_boundary(self):
        equivalent=CUTOFF.astimezone(timezone(timedelta(hours=-5)))
        self.assertEqual(len(parse(body(row(timestamp='20240404235959')),as_of=equivalent).pointers),1)
        with self.assertRaisesRegex(ValueError,'AWARE_CUTOFF_REQUIRED'):parse(as_of=CUTOFF.replace(tzinfo=None))
    def test_invalid_dates_digests_and_metadata_have_reasons(self):
        for changes,reason in [(dict(timestamp='20240230000000'),'INVALID_TIMESTAMP'),
            (dict(timestamp=True),'INVALID_TIMESTAMP'),(dict(digest='x'*32),'INVALID_DIGEST'),
            (dict(digest='0'*32),'INVALID_DIGEST'),(dict(status=200),'NON_200_CAPTURE'),
            (dict(mime='application/json'),'NON_HTML_CAPTURE')]:
            scan=parse(body(row(**changes)))
            self.assertEqual(scan.rejected_reason_counts,{reason:1});self.assertFalse(scan.pointers)
    def test_offsets_length_and_overflow_are_bounded(self):
        for changes in (dict(offset='-1'),dict(offset=True),dict(offset=1),dict(offset='1.0'),
            dict(length='0'),dict(length='262145'),dict(length=True),dict(length=' 1'),
            dict(offset=str(2**63-1),length='2'),dict(offset='9'*21)):
            with self.subTest(changes=changes):
                self.assertEqual(parse(body(row(**changes))).rejected_reason_counts,{'INVALID_RANGE':1})
    def test_foreign_collection_and_path_injection_are_held(self):
        valid=row()['filename']
        for filename in (valid.replace('2024-10','2024-18'),valid+'?x=1',
            valid.replace('/warc/','/../warc/'),'https://evil.com/x',
            valid.replace('/warc/','/crawldiagnostics/'),valid.replace('segments/','segments/%2f')):
            self.assertEqual(parse(body(row(filename=filename))).rejected_reason_counts,{'INVALID_ARCHIVE_FILENAME':1})
    def test_exact_duplicates_deduplicate_but_conflicts_fail_whole_scan(self):
        scan=parse(body(row(),row()))
        self.assertEqual(len(scan.pointers),1);self.assertEqual(scan.rejected_reason_counts,{'DUPLICATE_CAPTURE':1})
        for changes in (dict(offset='1'),dict(digest='B'*32),dict(length='1')):
            with self.assertRaisesRegex(ValueError,'CONFLICTING_CAPTURE_METADATA'):parse(body(row(),row(**changes)))
    def test_whole_jsonl_validation_prevents_partial_return(self):
        for tail in (b'{bad',b'{"a":1,"a":2}',b'{"a":NaN}',b'[]',b'null',b'1'):
            with self.subTest(tail=tail):
                with self.assertRaises(ValueError):parse(body(row())+b'\n'+tail)
    def test_bounds_are_strict_and_body_is_bounded_bytes(self):
        for key,bad in [('max_records',True),('max_records',101),('max_bytes',65537),
            ('max_range_bytes',262145),('max_records',0),('max_bytes',None)]:
            with self.assertRaises(ValueError):parse(**{key:bad})
        with self.assertRaises(ValueError):parse('not bytes')
        with self.assertRaises(ValueError):parse(b'x'*65537)
        with self.assertRaisesRegex(ValueError,'INDEX_RECORD_LIMIT'):parse(body(row(),row()),max_records=1)
    def test_empty_and_filtered_results_are_not_absence_proof(self):
        for raw in (b'',b'\n  \n',body(row(status='308'))):
            scan=parse(raw)
            self.assertFalse(scan.pointers);self.assertFalse(scan.source_admission_allowed)
    def test_records_are_sorted_oldest_first_and_reasons_cannot_mutate_scan(self):
        scan=parse(body(row(timestamp='20240303000000'),row(timestamp='20240301000000'),row(status='308')))
        self.assertLess(scan.pointers[0].captured_at,scan.pointers[1].captured_at)
        reasons=scan.rejected_reason_counts;reasons['NON_200_CAPTURE']=99
        self.assertEqual(scan.rejected_reason_counts['NON_200_CAPTURE'],1)
    def test_collection_identifier_does_not_accept_urls_or_traversal(self):
        for collection in ('CC-MAIN-2024-00','CC-MAIN-2024-54','../x','https://evil.com',True):
            with self.assertRaises(ValueError):parse(collection=collection)


if __name__=='__main__':unittest.main()
