import base64
import json
import unittest
from probe_spotify_playlist import parse_pages, playlist_id

PID = "4DSlyU8IYgjaeg3LeANJOG"
TRACK = "a" * 22


def pages(total=2, count=2, other=False):
    uri = "spotify:playlist:" + PID
    items = [{"itemV2": {"data": {"uri": "spotify:track:" + TRACK}}}] * min(count, 30)
    public = {"entities": {"items": {uri: {"uri": uri, "content": {"totalCount": total, "items": items}}}}}
    embedded = {"props": {"pageProps": {"state": {"data": {"entity": {
        "uri": uri + "x" if other else uri, "name": "Teste", "trackList": [
            {"uri": "spotify:track:" + TRACK, "title": "Faixa", "subtitle": "Artista", "duration": 123000}
        ] * count}}}}}}
    return ('<script id="initialState">' + base64.b64encode(json.dumps(public).encode()).decode() + '</script>',
            '<script id="__NEXT_DATA__">' + json.dumps(embedded) + '</script>')


class PlaylistProbeTest(unittest.TestCase):
    def test_complete_preserves_intentional_duplicates(self):
        result = parse_pages(PID, *pages())
        self.assertTrue(result["complete"])
        self.assertEqual(len(result["tracks"]), 2)

    def test_truncation_releases_no_tracks(self):
        result = parse_pages(PID, *pages(total=200, count=100))
        self.assertFalse(result["complete"])
        self.assertEqual(result["tracks"], [])

    def test_wrong_playlist_rejected(self):
        with self.assertRaises(ValueError):
            parse_pages(PID, *pages(other=True))

    def test_changed_page_rejected(self):
        with self.assertRaises(ValueError):
            parse_pages(PID, "<html>Login</html>", "<html></html>")

    def test_missing_metadata_not_silently_dropped(self):
        public, embed = pages()
        embed = embed.replace('"duration": 123000', '"duration": 0', 1)
        result = parse_pages(PID, public, embed)
        self.assertFalse(result["complete"])
        self.assertEqual(result["read_tracks"], 2)
        self.assertEqual(result["unavailable_positions"], [1])
        self.assertEqual(result["tracks"], [])

    def test_regional_id_requires_matching_metadata(self):
        public, embed = pages(total=1, count=1)
        state = {"entities": {"items": {"spotify:playlist:" + PID: {
            "uri": "spotify:playlist:" + PID, "content": {"totalCount": 1, "items": [
                {"itemV2": {"data": {"uri": "spotify:track:" + "b" * 22,
                    "name": "Faixa", "artists": {"items": [{"profile": {"name": "Artista"}}]},
                    "duration": {"totalMilliseconds": 123000}}}}
            ]}}}}}
        public = '<script id="initialState">' + base64.b64encode(json.dumps(state).encode()).decode() + '</script>'
        self.assertTrue(parse_pages(PID, public, embed)["complete"])
        self.assertFalse(parse_pages(PID, public, embed.replace("Artista", "Outro"))["complete"])

    def test_only_canonical_spotify_playlist_links(self):
        self.assertEqual(playlist_id("https://open.spotify.com/intl-pt/playlist/" + PID + "?si=abc"), PID)
        for url in ("http://open.spotify.com/playlist/" + PID,
                    "https://open.spotify.com.evil.test/playlist/" + PID,
                    "https://open.spotify.com@evil.test/playlist/" + PID,
                    "https://open.spotify.com/track/" + PID):
            with self.assertRaises(ValueError):
                playlist_id(url)


if __name__ == "__main__":
    unittest.main()
