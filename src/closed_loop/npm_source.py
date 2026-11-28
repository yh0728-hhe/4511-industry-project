"""Offline verification of frozen npm tarball documentation; never installs/executes code.

Caller must supply `version_metadata` independently retrieved from the npm
registry over HTTPS (normalized as {name,version,published,dist:{tarball,
integrity}}). This function cannot authenticate that mapping or certify
historic ownership of a domain; it only checks internal consistency and
cryptographic binding between the supplied bytes and the supplied metadata.
Model assertions must never populate this trust input. Only the embedded
README text is evidence, not current project metadata, downloads or traction.
"""
import base64
import gzip
import hashlib
import io
import json
import re
import tarfile
from datetime import datetime
from urllib.parse import urlsplit

from .contracts import aware, digest
from .guards import SourceCandidate, VerifiedRecord
from .npm_names import canonical_tarball_url, is_valid_npm_version, parse_npm_name

MAX_TARBALL_BYTES = 3_000_000
MAX_DECOMPRESSED_BYTES = 10_000_000
MAX_RATIO = 200
MAX_MEMBERS = 2000
MAX_TOTAL_DECLARED_SIZE = 10_000_000
MAX_DOC_BYTES = 128_000
README_WARNING = (
    'The following text is drawn from a package README as published by the '
    'package maintainer. Any product or performance statements it contains '
    'are publisher claims, not independent validation.\n\n'
)


def _fail():
    raise ValueError('INVALID_HISTORICAL_NPM_SOURCE')


def _dupe_object_pairs(pairs):
    seen = set()
    result = {}
    for key, value in pairs:
        if key in seen:
            _fail()
        seen.add(key)
        result[key] = value
    return result


def _parse_timestamp(value):
    if isinstance(value, datetime):
        return aware(value)
    if isinstance(value, str) and value.strip():
        return aware(datetime.fromisoformat(value.replace('Z', '+00:00')))
    _fail()


def _domain_match(url_text, domain):
    target = urlsplit(url_text)
    return (
        target.scheme == 'https' and target.hostname is not None and
        target.hostname.lower().removeprefix('www.') == domain and
        target.username is None and target.password is None and
        target.port in (None, 443)
    )


def verify_npm_source(tarball_bytes, version_metadata, expected_package, request):
    """Return candidate/record only after bounded byte, date and identity checks.

    `version_metadata` is a trusted npm registry record, not an LLM output.
    Its `published` timestamp bounds availability of the digest-bound
    artifact, not company age. The result supports package documentation
    only. Caller still routes the result through the gateway.
    """
    try:
        return _verify(tarball_bytes, version_metadata, expected_package, request)
    except (ValueError, TypeError, KeyError, AttributeError, OverflowError, UnicodeError,
            tarfile.TarError, RuntimeError, NotImplementedError, OSError, EOFError,
            json.JSONDecodeError):
        raise ValueError('INVALID_HISTORICAL_NPM_SOURCE') from None


def _verify(raw, meta, expected, request):
    if not isinstance(raw, bytes) or not 0 < len(raw) <= MAX_TARBALL_BYTES:
        _fail()
    if not isinstance(meta, dict):
        _fail()
    if not isinstance(expected, str) or parse_npm_name(expected) is None:
        _fail()
    name = meta.get('name')
    version = meta.get('version')
    if not isinstance(name, str) or parse_npm_name(name) is None or name != expected:
        _fail()
    if not is_valid_npm_version(version):
        _fail()
    published = _parse_timestamp(meta.get('published'))
    if published > aware(request.as_of):
        _fail()
    dist = meta.get('dist')
    if not isinstance(dist, dict):
        _fail()
    tarball_url = dist.get('tarball')
    expected_url = canonical_tarball_url(name, version)
    if expected_url is None:
        _fail()
    parsed = urlsplit(tarball_url if isinstance(tarball_url, str) else '')
    if (not isinstance(tarball_url, str) or tarball_url != expected_url or
            parsed.scheme != 'https' or parsed.netloc != 'registry.npmjs.org' or
            parsed.query or parsed.fragment or parsed.username or parsed.password or
            parsed.port is not None):
        _fail()
    integrity = dist.get('integrity')
    if not isinstance(integrity, str) or not integrity.startswith('sha512-'):
        _fail()
    encoded = integrity[len('sha512-'):]
    try:
        digest_bytes = base64.b64decode(encoded, validate=True)
    except (ValueError, TypeError):
        _fail()
        return
    if digest_bytes != hashlib.sha512(raw).digest():
        _fail()

    decompressed = _bounded_decompress(raw)
    package_json_text, readme_text = _read_members(decompressed, name)

    try:
        manifest = json.loads(package_json_text, object_pairs_hook=_dupe_object_pairs)
    except json.JSONDecodeError:
        _fail()
        return
    if manifest.get('name') != name or manifest.get('version') != version:
        _fail()
    homepage = manifest.get('homepage')
    domain = request.company.domain.removeprefix('www.')
    if not isinstance(homepage, str) or not _domain_match(homepage, domain):
        _fail()
    if not isinstance(readme_text, str) or not readme_text.strip():
        _fail()
    if not any(_domain_match(link, domain) for link in re.findall(r'https://[^\s<>"\)\]]+', readme_text)):
        _fail()

    artifact_sha256 = hashlib.sha256(raw).hexdigest()
    source_id = 'npm-tarball:' + digest(artifact_sha256 + '|' + f'{name}-{version}' + '|' + request.company.company_id)
    text = README_WARNING + readme_text
    candidate = SourceCandidate(source_id, tarball_url, request.company.company_id, 'package-documentation', text)
    record = VerifiedRecord(source_id, tarball_url, request.company.company_id, candidate.topic,
        digest(text), published, 'VERIFIED_ORIGINAL_PUBLICATION', True)
    return candidate, record


def _bounded_decompress(raw):
    with gzip.GzipFile(fileobj=io.BytesIO(raw)) as gz:
        decompressed = gz.read(MAX_DECOMPRESSED_BYTES + 1)
    if len(decompressed) > MAX_DECOMPRESSED_BYTES:
        _fail()
    if len(decompressed) > MAX_RATIO * max(len(raw), 1):
        _fail()
    return decompressed


def _read_members(decompressed, name):
    with tarfile.open(fileobj=io.BytesIO(decompressed), mode='r:') as archive:
        members = []
        for member in archive:
            members.append(member)
            if len(members) > MAX_MEMBERS:
                _fail()
        if not members or len(members) > MAX_MEMBERS:
            _fail()
        names = [m.name for m in members]
        if len(set(names)) != len(names):
            _fail()
        total_size = 0
        package_json_member = None
        readme_member = None
        for member in members:
            path = member.name
            if member.issparse() or member.size < 0:
                _fail()
            if member.isdir() and path.rstrip('/') == 'package':
                continue
            if (path.startswith('/') or '\\' in path or ':' in path or
                    any(part in ('', '.', '..') for part in path.rstrip('/').split('/')) or
                    not path.startswith('package/')):
                _fail()
            if member.isreg():
                total_size += member.size
                if path == 'package/package.json':
                    if package_json_member is not None:
                        _fail()
                    package_json_member = member
                elif path in ('package/README.md', 'package/readme.md'):
                    if readme_member is not None:
                        _fail()
                    readme_member = member
                elif path.lower() == 'package/readme.md':
                    _fail()
            elif member.isdir():
                pass
            else:
                _fail()
        if total_size > MAX_TOTAL_DECLARED_SIZE:
            _fail()
        if package_json_member is None or readme_member is None:
            _fail()
        if package_json_member.size > MAX_DOC_BYTES or readme_member.size > MAX_DOC_BYTES:
            _fail()
        package_json_bytes = archive.extractfile(package_json_member).read()
        readme_bytes = archive.extractfile(readme_member).read()
    package_json_text = package_json_bytes.decode('utf-8', errors='strict')
    readme_text = readme_bytes.decode('utf-8', errors='strict')
    return package_json_text, readme_text
