#!/usr/bin/env python3
"""Experimental public-page probe, not an app importer or a Spotify API client.

Reads metadata only. Does not log in, read cookies, fetch previews, search for
audio, or change a Music library. Refuses an incomplete playlist. Usage:
  python3 scripts/probe_spotify_playlist.py https://open.spotify.com/playlist/ID
  ... --output /tmp/playlist-metadata.json
"""
import argparse
import base64
import html
import json
import re
import sys
import time
import urllib.parse
import urllib.request
from pathlib import Path

MAX_PAGE_BYTES = 5_000_000
ID = re.compile(r"[A-Za-z0-9]{22}")


def playlist_id(url):
    parsed = urllib.parse.urlsplit(url.strip())
    if parsed.scheme != "https" or parsed.netloc != "open.spotify.com":
        raise ValueError("Use o link HTTPS completo de uma playlist em open.spotify.com.")
    match = re.fullmatch(r"/(?:intl-[a-z]{2}/)?playlist/([A-Za-z0-9]{22})/?", parsed.path)
    if not match:
        raise ValueError("O link precisa apontar para uma playlist, não uma faixa ou álbum.")
    return match.group(1)


class SameHostRedirect(urllib.request.HTTPRedirectHandler):
    def redirect_request(self, req, fp, code, msg, headers, newurl):
        target = urllib.parse.urlsplit(newurl)
        if target.scheme != "https" or target.netloc != "open.spotify.com":
            raise ValueError("Redirecionamento inesperado; leitura interrompida.")
        return super().redirect_request(req, fp, code, msg, headers, newurl)


def fetch(path):
    req = urllib.request.Request("https://open.spotify.com/" + path,
                                 headers={"User-Agent": "Mozilla/5.0"})
    with urllib.request.build_opener(SameHostRedirect()).open(req, timeout=15) as response:
        raw = response.read(MAX_PAGE_BYTES + 1)
        if len(raw) > MAX_PAGE_BYTES:
            raise ValueError("Página maior que o limite do protótipo.")
        return raw.decode("utf-8")


def script(page, name):
    match = re.search(r'<script\b[^>]*\bid=["\']' + re.escape(name)
                      + r'["\'][^>]*>(.*?)</script>', page, re.S)
    if not match:
        raise ValueError("O formato público do Spotify mudou ou a playlist está indisponível.")
    return match.group(1)


def parse_pages(pid, public_page, embedded_page):
    """Checks the declared count and source identity before releasing metadata."""
    if not ID.fullmatch(pid):
        raise ValueError("Identificador inválido.")
    uri = "spotify:playlist:" + pid
    try:
        state = json.loads(base64.b64decode(script(public_page, "initialState"), validate=True))
        entity = state["entities"]["items"][uri]
        total = entity["content"]["totalCount"]
        preview = entity["content"]["items"]
        embedded = json.loads(script(embedded_page, "__NEXT_DATA__"))
        source = embedded["props"]["pageProps"]["state"]["data"]["entity"]
        rows = source["trackList"]
    except (KeyError, TypeError, json.JSONDecodeError) as exc:
        raise ValueError("Não foi possível verificar a estrutura da playlist.") from exc
    if source.get("uri") != uri or entity.get("uri") != uri:
        raise ValueError("A página retornou uma playlist diferente da solicitada.")
    if type(total) is not int or total < 0 or not isinstance(rows, list):
        raise ValueError("Quantidade de músicas inválida.")
    tracks = []
    unavailable = []
    for position, row in enumerate(rows):
        if not isinstance(row, dict):
            raise ValueError("Formato de faixa inesperado.")
        track_uri = row.get("uri", "")
        title, artists, duration = row.get("title"), row.get("subtitle"), row.get("duration")
        if (not re.fullmatch(r"spotify:track:[A-Za-z0-9]{22}", track_uri)
                or not isinstance(title, str) or not title.strip()
                or not isinstance(artists, str) or type(duration) is not int or duration <= 0):
            unavailable.append(position + 1)
            continue
        tracks.append({"spotify_id": track_uri.split(":")[-1], "title": html.unescape(title),
                       "artists": html.unescape(artists).replace("\xa0", " "), "duration_ms": duration})
    # Duplicate tracks may be intentional. Preserve occurrences and their order.
    complete = len(rows) == total and not unavailable
    # Spotify can serve regional/album variants with different track IDs. Only
    # accept those aliases when title, full artist text and duration agree.
    def normalized(value):
        return " ".join(html.unescape(value).replace("\xa0", " ").casefold().split())

    def same_track(item, row):
        data = item.get("itemV2", {}).get("data", {})
        if data.get("uri") == row.get("uri"):
            return True
        artists = ", ".join(artist.get("profile", {}).get("name", "")
                            for artist in data.get("artists", {}).get("items", []))
        return (bool(data.get("name")) and bool(artists)
                and normalized(data["name"]) == normalized(row.get("title", ""))
                and normalized(artists) == normalized(row.get("subtitle", ""))
                and data.get("duration", {}).get("totalMilliseconds") == row.get("duration"))

    aligned = len(preview) <= len(rows) and all(
        same_track(item, rows[index]) for index, item in enumerate(preview))
    return {"playlist_id": pid, "name": source.get("name", "Playlist"),
            "declared_tracks": total, "read_tracks": len(rows),
            "usable_metadata_tracks": len(tracks), "unavailable_positions": unavailable,
            "complete": complete and aligned, "preview_order_verified": aligned,
            "tracks": tracks if complete and aligned else []}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("url")
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    started = time.monotonic()
    try:
        pid = playlist_id(args.url)
        result = parse_pages(pid, fetch("playlist/" + pid), fetch("embed/playlist/" + pid))
        result["elapsed_seconds"] = round(time.monotonic() - started, 3)
        summary = {key: value for key, value in result.items() if key != "tracks"}
        print(json.dumps(summary, ensure_ascii=False, indent=2))
        if not result["complete"]:
            print("Lista incompleta ou inconsistente: nenhuma faixa liberada para importação.", file=sys.stderr)
            return 2
        if args.output:
            # Exclusive creation: never overwrite another metadata export.
            with args.output.open("x", encoding="utf-8") as target:
                json.dump(result, target, ensure_ascii=False, indent=2)
                target.write("\n")
        return 0
    except Exception as exc:
        print("Leitura interrompida: " + str(exc), file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
