#!/usr/bin/env python3
"""Reversible, hash-checked Survival Log Vuplex patch. Python 3.9+, stdlib only."""
import argparse
import hashlib
import os
from pathlib import Path
import re
import stat
import sys
import tempfile

ORIGINAL_SHA256 = '1c74ee9ed70ec086e4230573511636097eb8d4f6d9f51f64d93174edaad59ea8'
PATCHED_SHA256 = '87bae34bf4b295b1a48e40d21f9259405752b9573436785d65dbba504bdf79d2'


def digest(data):
    return hashlib.sha256(data).hexdigest()


def require(condition, message):
    if not condition:
        raise ValueError(message)


def hex_bytes(value):
    try:
        result = bytes.fromhex(value)
        if not result:
            raise ValueError()
        return result
    except ValueError:
        raise argparse.ArgumentTypeError('Expected non-empty hex bytes, e.g. "F1".')


def sha256(value):
    if not re.fullmatch(r'[0-9a-fA-F]{64}', value):
        raise argparse.ArgumentTypeError('SHA-256 must contain 64 hex digits.')
    return value.lower()


def atomic_replace(path, data, expected):
    """Stage a complete file alongside the DLL, then atomically replace its name."""
    mode = stat.S_IMODE(path.stat().st_mode)
    fd, name = tempfile.mkstemp(prefix='.' + path.name + '.', dir=path.parent)
    temporary = Path(name)
    try:
        with os.fdopen(fd, 'wb') as stream:
            stream.write(data)
            stream.flush()
            os.fsync(stream.fileno())
        os.chmod(temporary, mode)
        require(path.read_bytes() == expected, 'DLL changed during operation; aborted.')
        os.replace(temporary, path)
        require(path.read_bytes() == data, 'Post-write verification failed; retain backup.')
    finally:
        if temporary.exists():
            temporary.unlink()


def discover_dll(args):
    """Search only CrossOver bottle C: drives; never follow directory symlinks."""
    root = Path(args.bottles_dir).expanduser().resolve()
    require(root.is_dir(), 'Bottle directory not found: ' + str(root)
            + '. Use --bottles-dir PATH or --dll PATH.')
    print('Searching bottles:', root)
    matches = []
    visited = 0

    def scan_error(error):
        raise ValueError('Search incomplete: ' + str(error) + '. Use --dll PATH.')

    for bottle in sorted(root.iterdir()):
        if bottle.is_symlink() or not bottle.is_dir():
            continue
        drive = bottle / 'drive_c'
        if drive.is_symlink() or not drive.is_dir():
            continue
        for directory, dirs, files in os.walk(drive, followlinks=False, onerror=scan_error):
            visited += 1
            require(visited <= 50000, 'Search limit reached; use --dll PATH.')
            parent = Path(directory)
            dirs[:] = sorted(name for name in dirs
                             if not (parent / name).is_symlink()
                             and not (parent == drive and name.lower() == 'windows'))
            for name in files:
                if name.lower() != 'vuplexwebviewwindows.dll':
                    continue
                candidate = parent / name
                suffix = tuple(part.lower() for part in candidate.parts[-4:])
                if suffix != ('survivallog_data', 'plugins', 'x86_64',
                              'vuplexwebviewwindows.dll') or candidate.is_symlink():
                    continue
                if not (candidate.parents[3] / 'SurvivalLog.exe').is_file():
                    continue
                value = digest(candidate.read_bytes())
                supported = value in (args.original_sha256, args.patched_sha256)
                print(('Supported: ' if supported else 'Unsupported: ') + str(candidate))
                if supported:
                    matches.append(candidate)
    require(matches, 'No supported Survival Log DLL found. Use --dll PATH for an explicit file.')
    require(len(matches) == 1,
            'Multiple supported installations found; select one with --dll PATH.')
    return matches[0]


def execute(args):
    dll = (Path(args.dll).expanduser().absolute() if args.dll else discover_dll(args))
    require(not dll.is_symlink(), 'DLL symlinks are not supported; specify the actual file.')
    require(dll.is_file(), 'DLL file not found: ' + str(dll))
    dll = dll.resolve()
    require(dll.stat().st_nlink == 1, 'Hard-linked DLLs are not supported.')
    backup = (Path(args.backup).expanduser().absolute() if args.backup
              else dll.with_name(dll.name + '.original.bak'))
    require(not backup.is_symlink(), 'Backup must not be a symlink.')
    require(backup.resolve() != dll, 'Backup and DLL must be different files.')
    require(args.offset >= 0, 'Offset must not be negative.')
    require(len(args.before) == len(args.after), 'Before/after lengths must match.')
    require(args.before != args.after, 'Before/after bytes must differ.')
    require(args.original_sha256 != args.patched_sha256, 'Hashes must differ.')
    data = dll.read_bytes()
    current = digest(data)
    state = ('original' if current == args.original_sha256 else
             'patched' if current == args.patched_sha256 else 'unknown')
    print('DLL:', dll)
    print('SHA-256:', current)
    print('State:', state)
    print('Backup:', backup)
    if args.action == 'status':
        if backup.is_file():
            print('Backup SHA-256:', digest(backup.read_bytes()))
        return 0 if state != 'unknown' else 1
    desired = 'patched' if args.action == 'patch' else 'original'
    if state == desired:
        print('Already ' + desired + '; no files changed.')
        return 0
    require(state != 'unknown', 'Unknown DLL version: refusing to modify it.')
    offset = args.offset
    before, after = ((args.before, args.after) if args.action == 'patch'
                     else (args.after, args.before))
    require(data[offset:offset + len(before)] == before,
            'Bytes at the offset do not match the expected sequence.')
    output = data[:offset] + after + data[offset + len(before):]
    expected_hash = (args.patched_sha256 if args.action == 'patch'
                     else args.original_sha256)
    require(digest(output) == expected_hash, 'Output hash mismatch; no files changed.')
    if args.action == 'patch':
        if os.path.lexists(backup):
            require(backup.is_file() and backup.read_bytes() == data,
                    'Existing backup does not match the original; refusing to overwrite it.')
        require(backup.parent.is_dir(), 'Backup directory does not exist.')
    else:
        require(backup.is_file(), 'Original backup missing; supply --backup PATH.')
        original = backup.read_bytes()
        require(digest(original) == args.original_sha256, 'Backup hash mismatch.')
        require(original == output, 'Backup does not match the reconstructed original.')
        output = original
    print('Change: offset', hex(offset), before.hex(' '), '->', after.hex(' '))
    if args.dry_run:
        print('Dry run OK; no files changed.')
        return 0
    if args.action == 'patch':
        if os.path.lexists(backup):
            require(not backup.is_symlink() and backup.is_file()
                    and backup.read_bytes() == data,
                    'Existing backup changed or is invalid; DLL not changed.')
            print('Reusing verified original backup:', backup)
        else:
            # Exclusive creation prevents overwriting a concurrently created backup.
            with backup.open('xb') as stream:
                stream.write(data)
                stream.flush()
                os.fsync(stream.fileno())
            require(backup.read_bytes() == data, 'Backup verification failed; DLL not changed.')
            print('Original backup created:', backup)
    atomic_replace(dll, output, data)
    print('Verified SHA-256:', digest(dll.read_bytes()))
    print('Done. Backup retained.')
    return 0


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('action', choices=('status', 'patch', 'restore'))
    parser.add_argument('--dll', help='Explicit DLL path; otherwise search CrossOver bottles')
    parser.add_argument('--bottles-dir',
                        default=str(Path.home() / 'Library/Application Support/CrossOver/Bottles'),
                        help='Bottle directory to search when --dll is omitted')
    parser.add_argument('--backup', help='Backup path; default: DLL.original.bak')
    parser.add_argument('--dry-run', action='store_true', help='Validate without writing')
    parser.add_argument('--offset', type=lambda s: int(s, 0), default=0xF505,
                        help='File offset, decimal or 0x-prefixed (default: 0xF505)')
    parser.add_argument('--before', type=hex_bytes, default=bytes.fromhex('F1'),
                        help='Original hex bytes (default: F1)')
    parser.add_argument('--after', type=hex_bytes, default=bytes.fromhex('00'),
                        help='Patched hex bytes (default: 00)')
    parser.add_argument('--original-sha256', type=sha256, default=ORIGINAL_SHA256)
    parser.add_argument('--patched-sha256', type=sha256, default=PATCHED_SHA256)
    args = parser.parse_args()
    try:
        return execute(args)
    except (OSError, ValueError) as error:
        print('ERROR:', error, file=sys.stderr)
        return 1


if __name__ == '__main__':
    sys.exit(main())
