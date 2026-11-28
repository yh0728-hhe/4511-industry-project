"""Inspect a privately acquired archive bundle offline; never certify transport.

Writes a text preview and integrity receipt only. No ledger registration, model,
network, recommendation, or outcome labels. Original acquisition must be audited.
"""
import argparse
from datetime import datetime
import hashlib
import json
from pathlib import Path
from types import SimpleNamespace

from closed_loop.archive_transport import HTTPResponse
from closed_loop.commoncrawl_index import parse_commoncrawl_index
from closed_loop.commoncrawl_record import verify_commoncrawl_record
from closed_loop.contracts import CompanySeed


def read_bounded(path, limit):
    with Path(path).open('rb') as stream:
        raw = stream.read(limit + 1)
    if len(raw) > limit:
        raise ValueError('BUNDLE_INPUT_TOO_LARGE')
    return raw


def strict_json(raw):
    def pairs(items):
        value = {}
        for key, item in items:
            if key in value:
                raise ValueError('DUPLICATE_MANIFEST_KEY')
            value[key] = item
        return value
    def reject(value):
        raise ValueError('NONFINITE_MANIFEST_NUMBER')
    return json.loads(raw.decode('utf-8'), object_pairs_hook=pairs, parse_constant=reject)


def inspect_bundle(manifest_path, index_path, body_path, output_dir):
    output = Path(output_dir)
    if output.exists():
        raise ValueError('FRESH_OUTPUT_DIRECTORY_REQUIRED')
    manifest_raw = read_bounded(manifest_path, 65536)
    manifest = strict_json(manifest_raw)
    keys = {'company', 'as_of', 'collection', 'original_url', 'capture_timestamp',
            'response_status', 'response_url', 'response_headers', 'acquisition_note'}
    if not isinstance(manifest, dict) or set(manifest) != keys:
        raise ValueError('EXACT_BUNDLE_MANIFEST_REQUIRED')
    note = manifest['acquisition_note']
    if not isinstance(note, str) or not 1 <= len(note.strip()) <= 2000:
        raise ValueError('BOUNDED_ACQUISITION_NOTE_REQUIRED')
    cutoff = datetime.fromisoformat(manifest['as_of'].replace('Z', '+00:00'))
    company = CompanySeed.from_dict(manifest['company'])
    index_raw = read_bounded(index_path, 65536)
    scan = parse_commoncrawl_index(index_raw, requested_url=manifest['original_url'],
        as_of=cutoff, collection=manifest['collection'])
    selected = [p for p in scan.pointers
        if p.captured_at.strftime('%Y%m%d%H%M%S') == manifest['capture_timestamp']]
    if len(selected) != 1:
        raise ValueError('EXACTLY_ONE_SELECTED_CAPTURE_REQUIRED')
    body = read_bounded(body_path, 262144)
    response = HTTPResponse(manifest['response_status'], manifest['response_url'],
                            manifest['response_headers'], body)
    candidate, _, receipt = verify_commoncrawl_record(selected[0], response,
        request=SimpleNamespace(company=company, as_of=cutoff), collection=manifest['collection'])
    receipt.update(status='INTEGRITY_CHECKED_ACQUISITION_REVIEW_PENDING',
        transport_independently_authenticated=False, ledger_registration_allowed=False,
        model_input_released=False, company_id=company.company_id,
        acquisition_note=note,
        input_sha256={name: hashlib.sha256(raw).hexdigest() for name, raw in
            [('manifest', manifest_raw), ('index', index_raw), ('compressed_body', body)]})
    # Validate everything before writing. Never replace earlier evidence/results.
    output.mkdir(parents=True, exist_ok=False)
    (output / 'integrity_receipt.json').write_text(json.dumps(receipt, indent=2) + '\n', encoding='utf-8')
    (output / 'text_preview.txt').write_text(candidate.text, encoding='utf-8')
    return receipt


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    for name in ('manifest', 'index', 'body', 'output-dir'):
        parser.add_argument('--' + name, required=True)
    args = parser.parse_args()
    receipt = inspect_bundle(args.manifest, args.index, args.body, args.output_dir)
    print(json.dumps({key: receipt[key] for key in
        ('status', 'transport_independently_authenticated', 'ledger_registration_allowed',
         'model_input_released', 'source_http_requests', 'model_calls')}, indent=2))


if __name__ == '__main__':
    main()
