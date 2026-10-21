"""Prepare researched photos and check their placement. No API key required.

The host researches and inspects sources; this helper fetches only the exact
image URLs it supplies, or uses already acquired files. Renderers stay offline.
"""
from __future__ import annotations
import argparse
import base64
import copy
from datetime import date
from io import BytesIO
import ipaddress
import json
from pathlib import Path
import socket
from urllib.parse import urlsplit
from urllib.error import HTTPError, URLError
from urllib.request import Request, HTTPRedirectHandler, build_opener

MAX_BYTES = 15 * 1024 * 1024


def property_photo(item, place_id):
    return bool(place_id and item.get('role') == 'stay' and item.get('place_id') == place_id
                and item.get('depicts') == 'property' and item.get('verified_property') is True
                and item.get('identity_source_url') and item.get('identity_note') and item.get('data_uri'))


def assess_media(trip):
    """Missing photos are an explicit review result, never silent success."""
    if trip.get('photo_policy') == 'off':
        return {'status': 'opted_out', 'ready': 0, 'required': 0, 'missing': []}
    ko = trip.get('language', 'ko') == 'ko'
    media = trip.get('media', [])
    targets = [{'role': 'hero', 'place_id': None, 'label': '여행 대표 사진' if ko else 'Trip cover photo'}]
    seen = set()
    for booking in trip.get('bookings', []):
        if booking.get('type') != 'stay':
            continue
        key = booking.get('place_id') or booking['id']
        if key in seen:
            continue
        seen.add(key)
        targets.append({'role': 'stay', 'place_id': booking.get('place_id'), 'label': booking.get('name') or key})
    missing = []
    for target in targets:
        found = any(m.get('role') == 'hero' and m.get('depicts') == 'landscape' and m.get('data_uri') for m in media) if target['role'] == 'hero' else any(property_photo(m, target['place_id']) for m in media)
        if found:
            continue
        attempt = next((a for a in reversed(trip.get('photo_attempts', [])) if a.get('role') == target['role'] and a.get('place_id') == target['place_id']), {})
        reason = attempt.get('reason') or ('사진 수집·확인이 아직 완료되지 않았습니다.' if ko else 'Photo collection and verification are not complete.')
        missing.append({**target, 'reason': reason})
    return {'status': 'needs_review' if missing else 'ready', 'ready': len(targets)-len(missing), 'required': len(targets), 'missing': missing}


def _public_url(url):
    parts = urlsplit(url)
    if parts.scheme != 'https' or not parts.hostname or parts.username or parts.password or parts.port not in (None, 443):
        raise ValueError('Image downloads require a public HTTPS URL')
    addresses = socket.getaddrinfo(parts.hostname, 443, type=socket.SOCK_STREAM)
    if not addresses or any(not ipaddress.ip_address(a[4][0]).is_global for a in addresses):
        raise ValueError('Image downloads cannot use private or local addresses')
    return url


class PublicRedirect(HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        _public_url(newurl)
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch_image(url):
    request = Request(_public_url(url), headers={'User-Agent': 'TravelPlanner/1.1 photo preparation'})
    with build_opener(PublicRedirect()).open(request, timeout=25) as response:
        data = response.read(MAX_BYTES + 1)
    if len(data) > MAX_BYTES:
        raise ValueError('Image exceeds 15 MiB')
    return data


def encode_image(data):
    # Pillow is needed only for photo preparation, not for HTML rendering.
    from PIL import Image, ImageOps
    if not data or len(data) > MAX_BYTES:
        raise ValueError('Invalid image size')
    try:
        original = Image.open(BytesIO(data))
    except Image.DecompressionBombError as exc:
        raise ValueError('Unsupported image format or pixel count') from exc
    with original:
        if original.format not in ('JPEG', 'PNG', 'WEBP') or original.width * original.height > 40_000_000:
            raise ValueError('Unsupported image format or pixel count')
        original.load()
        im = ImageOps.exif_transpose(original).convert('RGB')
        if min(im.size) < 180 or max(im.size) < 640:
            raise ValueError('Image is too small for the travel layout')
        im.thumbnail((1800, 1800))
        out = BytesIO()
        im.save(out, format='JPEG', quality=85, optimize=True)
    return 'data:image/jpeg;base64,' + base64.b64encode(out.getvalue()).decode('ascii')


def prepare_media(trip, manifest, base_dir):
    from trip_core import ID_RE, safe_url
    out = copy.deepcopy(trip)
    out.setdefault('media', [])
    out.setdefault('photo_attempts', [])
    places = {p['id']: p for p in trip.get('places', [])}
    if trip.get('photo_policy') == 'off':
        raise ValueError('Photo collection is disabled by this trip; do not override the user preference')
    items = manifest.get('items', [])
    if not isinstance(items, list) or any(not isinstance(x, dict) for x in items):
        raise ValueError('Manifest items must be objects')
    report = {'added': [], 'failed': []}
    for item in items:
        # Invalid metadata is an authoring error; do not silently skip it.
        for key in ('id', 'role', 'alt', 'caption', 'creator', 'license', 'checked_at'):
            if not isinstance(item.get(key), str) or not item[key].strip():
                raise ValueError('Required photo metadata: ' + key)
        if not ID_RE.fullmatch(item['id']) or item['role'] not in ('hero', 'stay', 'place'):
            raise ValueError('Invalid photo id or role')
        date.fromisoformat(item['checked_at'])
        if item.get('visually_verified') is not True:
            raise ValueError('Inspect the actual image before marking visually_verified')
        for key in ('source_url', 'license_url'):
            if not safe_url(item.get(key)):
                raise ValueError('A source page and documented reuse terms are required')
        if item.get('place_id') is not None and item['place_id'] not in places:
            raise ValueError('Photo references an unknown place')
        if item['role'] in ('stay', 'place') and not item.get('place_id'):
            raise ValueError('Hotel/place photos must link to an exact place_id')
        if item['role'] == 'stay' and not (item.get('depicts') == 'property' and item.get('verified_property') is True and safe_url(item.get('identity_source_url')) and item.get('identity_note')):
            raise ValueError('Verify the exact hotel name/branch/address and record the identity source')
        if item.get('depicts') not in ('landscape', 'property'):
            raise ValueError('Photo depicts must be landscape or property')
        if item['role'] == 'hero' and item['depicts'] != 'landscape':
            raise ValueError('The cover must show the destination city/landscape, not a hotel')
        if bool(item.get('path')) == bool(item.get('download_url')):
            raise ValueError('Supply exactly one local path or verified direct download_url')
        try:
            if item.get('path'):
                path = Path(base_dir) / item['path']
                if path.stat().st_size > MAX_BYTES:
                    raise ValueError('Image exceeds 15 MiB')
                data = path.read_bytes()
            else:
                data = fetch_image(item['download_url'])
            uri = encode_image(data)
        except (OSError, ValueError) as exc:
            if isinstance(exc, HTTPError):
                reason = ('사진 서버에서 파일을 받지 못했습니다.', 'The image server did not provide the file.')
            elif isinstance(exc, URLError):
                reason = ('사진 서버에 연결하지 못했습니다.', 'Could not connect to the image server.')
            elif str(exc) == 'Image is too small for the travel layout':
                reason = ('사진 해상도가 낮아 여행북에 사용하지 않았습니다.', 'The photo resolution is too low for the travel layout.')
            elif '15 MiB' in str(exc) or str(exc) in ('Invalid image size', 'Unsupported image format or pixel count'):
                reason = ('사진의 파일 크기·해상도·형식이 지원 범위를 벗어났습니다.', 'The photo size, resolution or format is unsupported.')
            else:
                reason = ('사진 파일을 읽을 수 없거나 정상적인 이미지가 아닙니다.', 'The photo file could not be read or decoded as an image.')
            reason = reason[0 if trip.get('language', 'ko') == 'ko' else 1]
            attempt = {'role': item['role'], 'place_id': item.get('place_id'), 'reason': reason, 'checked_at': item['checked_at']}
            out['photo_attempts'].append(attempt)
            report['failed'].append({'id': item['id'], **attempt})
            continue
        keys = ('id', 'role', 'place_id', 'alt', 'caption', 'creator', 'source_url', 'license', 'license_url', 'depicts', 'checked_at', 'verified_property', 'identity_source_url', 'identity_note')
        prepared = {k: item[k] for k in keys if k in item}
        prepared['data_uri'] = uri
        # A retry replaces the same ID, not all unrelated photos.
        out['media'] = [m for m in out['media'] if m['id'] != item['id']] + [prepared]
        report['added'].append({'id': item['id'], 'role': item['role'], 'place_id': item.get('place_id'), 'bytes': len(uri)})
    for attempt in manifest.get('unavailable', []):
        if not isinstance(attempt, dict) or attempt.get('role') not in ('hero', 'stay', 'place') or not isinstance(attempt.get('reason'), str) or not attempt['reason'].strip():
            raise ValueError('Unavailable photos need role, place_id and a concrete reason')
        if attempt.get('place_id') is not None and attempt['place_id'] not in places:
            raise ValueError('Unavailable photo references an unknown place')
        out['photo_attempts'].append({k: attempt[k] for k in ('role', 'place_id', 'reason', 'checked_at') if k in attempt})
    report['coverage'] = assess_media(out)
    return out, report


def main():
    from trip_core import load_trip
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('input')
    parser.add_argument('--manifest', required=True)
    parser.add_argument('--out', required=True)
    args = parser.parse_args()
    try:
        output = Path(args.out).resolve()
        if output in (Path(args.input).resolve(), Path(args.manifest).resolve()):
            raise ValueError('Use a new output file; original input and manifest are preserved')
        manifest_path = Path(args.manifest).resolve()
        trip, report = prepare_media(load_trip(args.input), load_trip(manifest_path), manifest_path.parent)
        output.parent.mkdir(parents=True, exist_ok=True)
        output.write_text(json.dumps(trip, ensure_ascii=False, indent=2) + '\n', encoding='utf-8')
        print(json.dumps({'output': str(output), **report}, ensure_ascii=False, indent=2))
        return 0 if not report['failed'] else 1
    except (ValueError, OSError, ImportError) as exc:
        print(json.dumps({'status': 'failed', 'error': str(exc)}, ensure_ascii=False))
        return 2


if __name__ == '__main__':
    raise SystemExit(main())
