"""Invented byte fixtures only; no network, package installation or model calls."""
import hashlib
import io
import stat
import unittest
import warnings
import zipfile
from dataclasses import replace
from closed_loop.fixtures import request
from closed_loop.guards import TemporalGateway
from closed_loop.package_source import verify_wheel_source


def wheel(text=None,extra=(),member='sample_sdk-1.0.dist-info/METADATA'):
    body=text or 'Name: sample-sdk\nVersion: 1.0\n\nSDK documentation: https://synthetic.example/docs\n'
    stream=io.BytesIO()
    with warnings.catch_warnings():
        warnings.simplefilter('ignore',UserWarning)
        with zipfile.ZipFile(stream,'w',compression=zipfile.ZIP_DEFLATED) as archive:
            archive.writestr(member,body)
            for name,data in extra:archive.writestr(name,data)
    raw=stream.getvalue()
    meta=dict(filename='sample_sdk-1.0-py3-none-any.whl',packagetype='bdist_wheel',
        size=len(raw),yanked=False,digests={'sha256':hashlib.sha256(raw).hexdigest()},
        url='https://files.pythonhosted.org/packages/aa/bb/sample_sdk-1.0-py3-none-any.whl',
        upload_time_iso_8601='2024-03-20T00:00:00Z')
    return raw,meta


class PackageSourceTests(unittest.TestCase):
    def verify(self,raw,meta,req=None):return verify_wheel_source(raw,meta,'sample-sdk',req or request())

    def test_valid_real_gateway_and_readme_only(self):
        candidate,record=self.verify(*wheel())
        self.assertNotIn('Name:',candidate.text)
        gateway=TemporalGateway(request(),[record])
        fact,error=gateway.admit(candidate)
        self.assertIsNone(error)
        self.assertEqual(fact.proof_kind,'VERIFIED_ORIGINAL_PUBLICATION')
        self.assertEqual(fact.topic,'package-documentation')

    def test_gateway_cannot_reuse_proof_for_changed_content(self):
        candidate,record=self.verify(*wheel())
        _,error=TemporalGateway(request(),[record]).admit(replace(candidate,text='changed'))
        self.assertEqual(error['reason'],'CONTENT_MISMATCH')

    def test_bad_metadata_fields(self):
        for key,value in [('size',True),('size',1),('yanked',True),('yanked',None),
                          ('packagetype','sdist'),('filename','../bad.whl'),
                          ('filename','other-1.0-py3-none-any.whl'),
                          ('upload_time_iso_8601','2024-03-20'),
                          ('upload_time_iso_8601','2025-01-01T00:00:00Z')]:
            with self.subTest(key=key,value=value):
                raw,meta=wheel();meta[key]=value
                with self.assertRaisesRegex(ValueError,'INVALID_HISTORICAL_PACKAGE_SOURCE'):self.verify(raw,meta)

    def test_bad_urls(self):
        for url in ['http://files.pythonhosted.org/packages/a.whl',
                    'https://files.pythonhosted.org.evil.test/packages/a.whl',
                    'https://user@files.pythonhosted.org/packages/a.whl',
                    'https://files.pythonhosted.org:443/packages/a.whl',
                    'https://files.pythonhosted.org/packages/../sample_sdk-1.0-py3-none-any.whl',
                    'https://files.pythonhosted.org/packages/%2e%2e/sample_sdk-1.0-py3-none-any.whl']:
            raw,meta=wheel();meta['url']=url
            with self.subTest(url=url),self.assertRaises(ValueError):self.verify(raw,meta)
        for suffix in ['?token=x','#x']:
            raw,meta=wheel();meta['url']+=suffix
            with self.assertRaises(ValueError):self.verify(raw,meta)

    def test_tampered_digest_and_bytes(self):
        raw,meta=wheel();meta['digests']['sha256']='0'*64
        with self.assertRaises(ValueError):self.verify(raw,meta)
        raw,meta=wheel();raw=raw[:-1]+b'x'
        with self.assertRaises(ValueError):self.verify(raw,meta)

    def test_readme_domain_exact_and_no_header_email_identity(self):
        for body in ['https://synthetic.example.evil.test','https://evilsynthetic.example',
                     'https://synthetic.example@evil.test','http://synthetic.example','email only']:
            raw,meta=wheel('Name: sample-sdk\nVersion: 1.0\nAuthor-email: a@synthetic.example\n\n'+body)
            with self.subTest(body=body),self.assertRaises(ValueError):self.verify(raw,meta)
        self.verify(*wheel('Name: sample-sdk\nVersion: 1.0\n\nhttps://www.synthetic.example/docs'))

    def test_duplicate_headers_and_package_version_mismatch(self):
        for head in ['Name: sample-sdk\nName: sample-sdk\nVersion: 1.0',
                     'Name: sample-sdk\nVersion: 1.0\nVersion: 1.0',
                     'Name: other\nVersion: 1.0','Name: sample-sdk\nVersion: 2.0']:
            with self.subTest(head=head),self.assertRaises(ValueError):
                self.verify(*wheel(head+'\n\nhttps://synthetic.example'))

    def test_bad_archive_members(self):
        for extra in [[('../escape',b'x')],[('/absolute',b'x')],
                      [('sample_sdk-1.0.dist-info/METADATA',b'duplicate')],
                      [('other-1.0.dist-info/METADATA',b'other')],
                      [('large',b'0'*500000)],
                      [('a',b'x')]*2]:
            with self.subTest(extra=[n for n,_ in extra]),self.assertRaises(ValueError):self.verify(*wheel(extra=extra))

    def test_nested_metadata_and_wrong_distinfo(self):
        for member in ['nested/sample_sdk-1.0.dist-info/METADATA','other-1.0.dist-info/METADATA']:
            with self.subTest(member=member),self.assertRaises(ValueError):self.verify(*wheel(member=member))

    def test_archive_limits_and_bad_utf8(self):
        for raw,meta in [wheel(extra=[(str(i),b'x') for i in range(2001)]),
                         wheel('Name: sample-sdk\nVersion: 1.0\n\n'+('a'*130000)),
                         wheel(b'Name: sample-sdk\nVersion: 1.0\n\n\xff')]:
            with self.assertRaises(ValueError):self.verify(raw,meta)
        with self.assertRaises(ValueError):self.verify(b'x'*1000001,{})

    def test_symlink_rejected(self):
        raw,meta=wheel();stream=io.BytesIO(raw)
        with zipfile.ZipFile(stream,'a') as archive:
            entry=zipfile.ZipInfo('link');entry.external_attr=(stat.S_IFLNK|0o777)<<16
            archive.writestr(entry,'target')
        raw=stream.getvalue();meta['size']=len(raw);meta['digests']['sha256']=hashlib.sha256(raw).hexdigest()
        with self.assertRaises(ValueError):self.verify(raw,meta)

    def test_aware_timezone_equivalence(self):
        raw,meta=wheel();meta['upload_time_iso_8601']='2024-04-05T01:00:00+02:00'
        self.verify(raw,meta)


if __name__=='__main__':unittest.main()
