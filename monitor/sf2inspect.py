"""Read the preset (instrument) list out of a .sf2 / .sf3 SoundFont.

SoundFonts are RIFF containers: a "sfbk" top chunk holding LISTs named
INFO / sdta / pdta. The pdta list carries the preset headers ("phdr") —
one 38-byte record per preset plus a terminator. This module walks only
the chunk headers (it seeks PAST sdta so a 140MB font costs a few KB of
reads), parses phdr, and returns (bank, program, name) triples. No
fluidsynth, no parser libs, no pip installs.

Parsed results are cached per (path, mtime) — refetches are instant.
"""

import os
import struct

_PHDR = struct.Struct("<20sHHHIII")   # name, preset, bank, bagNdx, lib, genre, morph
_cache = {}


class SoundFontError(ValueError):
    pass


def _label(name_bytes):
    """20-byte SF2 name field: NUL/pad8 terminated, strip leftover padding."""
    name = name_bytes.split(b"\x00")[0]
    # Pad8 names can be space-padded too, and sometimes have stray padding.
    return name.decode("latin-1", "replace").strip()


def presets(path):
    """[(bank, program, name), ...] for the .sf2/.sf3 at `path`.

    Sorted by (bank, program). The final phdr record (the EOP terminator
    the spec mandates) is dropped. Raises SoundFontError on unreadable /
    non-SoundFont input.
    """
    try:
        mtime = os.path.getmtime(path)
    except OSError as exc:
        raise SoundFontError("cannot stat %s: %s" % (path, exc))
    cached = _cache.get(path)
    if cached and cached[0] == mtime:
        return cached[1]
    parsed = _parse(path)
    _cache[path] = (mtime, parsed)
    return parsed


def _parse(path):
    try:
        f = open(path, "rb")
    except OSError as exc:
        raise SoundFontError("cannot open %s: %s" % (path, exc))
    try:
        head = f.read(12)
        if head[:4] != b"RIFF" or head[8:12] != b"sfbk":
            raise SoundFontError("not a SoundFont (RIFF sfbk missing): %s" % path)
        off = 12
        while True:
            f.seek(off)
            hdr = f.read(8)
            if len(hdr) < 8:
                break
            cid, size = struct.unpack("<4sI", hdr)
            if cid == b"LIST":
                list_type = f.read(4)
                if list_type == b"pdta":
                    payload = f.read(size - 4)   # pdta is small (preset headers)
                    return _parse_pdta(payload, path)
            off += 8 + size + (size & 1)          # chunks pad to even
        raise SoundFontError("no pdta chunk found in %s" % path)
    finally:
        f.close()


def _parse_pdta(payload, path):
    off = 0
    while off + 8 <= len(payload):
        cid, size = struct.unpack_from("<4sI", payload, off)
        if cid == b"phdr":
            data = payload[off + 8: off + 8 + size]
            n = len(data) // _PHDR.size
            recs = []
            # Spec: phdr has N+1 records, the last being the EOP terminator.
            for i in range(max(n - 1, 0)):
                name_b, program, bank, _bag, _lib, _gen, _morph = \
                    _PHDR.unpack_from(data, i * _PHDR.size)
                name = _label(name_b)
                if not name:
                    continue
                recs.append((bank, program, name))
            recs.sort()
            return recs
        off += 8 + size + (size & 1)
    raise SoundFontError("no phdr chunk in pdta of %s" % path)