"""Invented byte fixtures only; no network, npm install or model calls."""
import base64
import gzip
import hashlib
import io
import tarfile
import unittest
from unittest.mock import patch
from dataclasses import replace

from closed_loop.fixtures import request
from closed_loop.guards import TemporalGateway
from closed_loop.npm_source import verify_npm_source

NAME = 'sample-sdk'
VERSION = '1.0.0'


def _tar_bytes(members):
    stream = io.BytesIO()
    with tarfile.open(fileobj=stream, mode='w') as archive:
        for path, data in members:
            if data is None:
                info = tarfile.TarInfo(path)
                info.type = tarfile.DIRTYPE
                archive.addfile(info)
                continue
            info = tarfile.TarInfo(path)
            info.size = len(data)
            archive.addfile(info, io.BytesIO(data))
    return stream.getvalue()


def tarball(package_json=None, readme=b'SDK docs: https://synthetic.example/docs\n',
            extra=(), name=NAME, version=VERSION, published='2024-03-20T00:00:00Z',
            readme_path='package/README.md'):
    pkg = package_json
    if pkg is None:
        pkg = ('{"name":"%s","version":"%s","homepage":"https://synthetic.example"}' % (name, version)).encode()
    members = [('package/package.json', pkg)]
    if readme is not None:
        members.append((readme_path, readme))
    members.extend(extra)
    raw_tar = _tar_bytes(members)
    raw = gzip.compress(raw_tar)
    integrity = 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode()
    meta = dict(name=name, version=version, published=published,
        dist=dict(tarball=f'https://registry.npmjs.org/{name}/-/{name}-{version}.tgz', integrity=integrity))
    return raw, meta


class NpmSourceTests(unittest.TestCase):
    def verify(self, raw, meta, req=None):
        return verify_npm_source(raw, meta, NAME, req or request())

    def test_normal_package_root_directory_allowed(self):
        self.verify(*tarball(extra=[('package', None)]))

    def test_double_slash_member_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(extra=[('package//ambiguous', b'x')]))

    def test_member_count_bound(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(extra=[('package/f'+str(i), b'x') for i in range(2001)]))

    def test_valid_gateway_admit(self):
        candidate, record = self.verify(*tarball())
        self.assertIn('publisher claims', candidate.text)
        self.assertIn('SDK docs', candidate.text)
        gateway = TemporalGateway(request(), [record])
        fact, error = gateway.admit(candidate)
        self.assertIsNone(error)
        self.assertEqual(fact.proof_kind, 'VERIFIED_ORIGINAL_PUBLICATION')
        self.assertEqual(fact.topic, 'package-documentation')

    def test_gateway_rejects_changed_content(self):
        candidate, record = self.verify(*tarball())
        _, error = TemporalGateway(request(), [record]).admit(replace(candidate, text='changed'))
        self.assertEqual(error['reason'], 'CONTENT_MISMATCH')

    def test_future_publish_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(published='2099-01-01T00:00:00Z'))

    def test_naive_publish_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(published='2024-03-20T00:00:00'))

    def test_wrong_name_or_version_rejected(self):
        raw, meta = tarball()
        meta['name'] = 'other-pkg'
        with self.assertRaises(ValueError):
            self.verify(raw, meta)
        raw, meta = tarball()
        meta['version'] = '2.0.0'
        with self.assertRaises(ValueError):
            self.verify(raw, meta)
        raw, meta = tarball(name='other-pkg', version=VERSION)
        with self.assertRaises(ValueError):
            self.verify(raw, meta, )

    def test_wrong_domain_rejected(self):
        pkg = b'{"name":"sample-sdk","version":"1.0.0","homepage":"https://evil.test"}'
        with self.assertRaises(ValueError):
            self.verify(*tarball(package_json=pkg))

    def test_suffix_domain_rejected(self):
        pkg = b'{"name":"sample-sdk","version":"1.0.0","homepage":"https://synthetic.example.evil.test"}'
        with self.assertRaises(ValueError):
            self.verify(*tarball(package_json=pkg))
        readme = b'docs at https://synthetic.example.evil.test/docs\n'
        with self.assertRaises(ValueError):
            self.verify(*tarball(readme=readme))

    def test_corrupt_integrity_rejected(self):
        raw, meta = tarball()
        meta['dist']['integrity'] = 'sha512-' + 'A' * 20
        with self.assertRaises(ValueError):
            self.verify(raw, meta)
        raw, meta = tarball()
        raw = raw[:-1] + bytes([raw[-1] ^ 1])
        with self.assertRaises(ValueError):
            self.verify(raw, meta)

    def test_malformed_url_rejected(self):
        for url in [
            f'http://registry.npmjs.org/{NAME}/-/{NAME}-{VERSION}.tgz',
            f'https://registry.npmjs.org.evil.test/{NAME}/-/{NAME}-{VERSION}.tgz',
            f'https://user@registry.npmjs.org/{NAME}/-/{NAME}-{VERSION}.tgz',
            f'https://registry.npmjs.org:443/{NAME}/-/{NAME}-{VERSION}.tgz',
            f'https://registry.npmjs.org/{NAME}/-/{NAME}-{VERSION}.tgz?x=1',
            f'https://registry.npmjs.org/{NAME}/-/{NAME}-{VERSION}.tgz#frag',
        ]:
            raw, meta = tarball()
            meta['dist']['tarball'] = url
            with self.subTest(url=url), self.assertRaises(ValueError):
                self.verify(raw, meta)

    def test_duplicate_json_keys_rejected(self):
        pkg = b'{"name":"sample-sdk","name":"sample-sdk","version":"1.0.0","homepage":"https://synthetic.example"}'
        with self.assertRaises(ValueError):
            self.verify(*tarball(package_json=pkg))

    def test_traversal_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(extra=[('../escape', b'x')]))
        with self.assertRaises(ValueError):
            self.verify(*tarball(extra=[('/absolute', b'x')]))

    def test_duplicate_member_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(extra=[('package/package.json', b'{}')]))

    def test_readme_ambiguity_rejected(self):
        with self.assertRaises(ValueError):
            self.verify(*tarball(readme_path='package/Readme.md'))
        with self.assertRaises(ValueError):
            self.verify(*tarball(extra=[('package/readme.md', b'dup https://synthetic.example')]))

    def test_symlink_rejected(self):
        raw_tar = _tar_bytes([
            ('package/package.json',
             ('{"name":"%s","version":"%s","homepage":"https://synthetic.example"}' % (NAME, VERSION)).encode()),
            ('package/README.md', b'docs https://synthetic.example'),
        ])
        stream = io.BytesIO(raw_tar)
        with tarfile.open(fileobj=stream, mode='a') as archive:
            info = tarfile.TarInfo('package/link')
            info.type = tarfile.SYMTYPE
            info.linkname = 'package/README.md'
            archive.addfile(info)
        raw = gzip.compress(stream.getvalue())
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode()
        meta = dict(name=NAME, version=VERSION, published='2024-03-20T00:00:00Z',
            dist=dict(tarball=f'https://registry.npmjs.org/{NAME}/-/{NAME}-{VERSION}.tgz', integrity=integrity))
        with self.assertRaises(ValueError):
            self.verify(raw, meta)

    def test_oversized_gzip_rejected(self):
        raw_tar = _tar_bytes([
            ('package/package.json',
             ('{"name":"%s","version":"%s","homepage":"https://synthetic.example"}' % (NAME, VERSION)).encode()),
            ('package/README.md', b'0' * 50_000_000),
        ])
        raw = gzip.compress(raw_tar)
        if len(raw) > 3_000_000:
            self.skipTest('fixture too large for 3MB bound; ratio case still covered below')
        integrity = 'sha512-' + base64.b64encode(hashlib.sha512(raw).digest()).decode()
        meta = dict(name=NAME, version=VERSION, published='2024-03-20T00:00:00Z',
            dist=dict(tarball=f'https://registry.npmjs.org/{NAME}/-/{NAME}-{VERSION}.tgz', integrity=integrity))
        with self.assertRaises(ValueError):
            self.verify(raw, meta)

    def test_no_extraction_side_effects(self):
        with patch.object(tarfile.TarFile, 'extractall', side_effect=AssertionError('no extraction')) as all_mock, \
             patch.object(tarfile.TarFile, 'extract', side_effect=AssertionError('no extraction')) as one_mock:
            candidate, record = self.verify(*tarball())
        all_mock.assert_not_called()
        one_mock.assert_not_called()
        self.assertIsInstance(candidate.text, str)


if __name__ == '__main__':
    unittest.main()
