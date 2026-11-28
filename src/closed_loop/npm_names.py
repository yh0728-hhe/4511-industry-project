"""Pure strict npm package-name parsing/validation shared by registry callers.

Only the canonical lowercase, unencoded forms documented at
https://docs.npmjs.com/cli/v11/using-npm/scope/ are accepted: an unscoped
name or an `@scope/name` pair. There is no normalization: whatever string
is passed in is either exactly one of these two shapes or rejected.
"""
import re

_SEGMENT = r'[a-z0-9][a-z0-9._-]*'
UNSCOPED_NAME_RE = re.compile(_SEGMENT)
SCOPED_NAME_RE = re.compile(r'@(%s)/(%s)' % (_SEGMENT, _SEGMENT))
VERSION_RE = re.compile(r'[0-9A-Za-z][0-9A-Za-z.+-]*')


def parse_npm_name(name):
    """Return ('unscoped', name) or ('scoped', scope, basename); else None."""
    if not isinstance(name, str):
        return None
    match = UNSCOPED_NAME_RE.fullmatch(name)
    if match and '..' not in name:
        return ('unscoped', name)
    match = SCOPED_NAME_RE.fullmatch(name)
    if match:
        scope, basename = match.group(1), match.group(2)
        if '..' not in scope and '..' not in basename:
            return ('scoped', scope, basename)
    return None


def is_valid_npm_name(name):
    return parse_npm_name(name) is not None


def is_valid_npm_version(version):
    return isinstance(version, str) and bool(VERSION_RE.fullmatch(version))


def canonical_tarball_url(name, version):
    """Return the canonical registry.npmjs.org tarball URL, else None.

    Scoped tarball filenames use only the basename (without the leading
    `@scope/`), matching registry.npmjs.org's actual layout.
    """
    parsed = parse_npm_name(name)
    if parsed is None or not is_valid_npm_version(version):
        return None
    if parsed[0] == 'unscoped':
        return f'https://registry.npmjs.org/{name}/-/{name}-{version}.tgz'
    _, scope, basename = parsed
    return f'https://registry.npmjs.org/@{scope}/{basename}/-/{basename}-{version}.tgz'
