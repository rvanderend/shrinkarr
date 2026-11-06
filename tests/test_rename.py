"""Run with: python -m unittest discover tests"""
import tempfile
import unittest
from pathlib import Path

from app.rename import plan


def probe(mark, *audio):
    return {"format": {"tags": {"SHRINKARR": mark} if mark else {}},
            "streams": [{"codec_type": "video", "codec_name": "hevc"}]
            + [{"codec_type": "audio", "codec_name": c, "channels": ch} for c, ch in audio]}


class Plan(unittest.TestCase):
    def setUp(self):
        self.d = Path(tempfile.mkdtemp())

    def new(self, name, p):
        f = self.d / name
        f.write_text("x")
        r = plan(f, p)
        return r.name if r else None

    def test_full_encode_with_eac3(self):
        self.assertEqual(self.new("Some.Movie.2016.1080p.BluRay.DTS.x264-GRP.mkv", probe("qsv q21 + eac3", ("eac3", 6))),
                         "Some.Movie.2016.1080p.BluRay.DDP5.1.x265-GRP.mkv")

    def test_audio_only(self):
        self.assertEqual(self.new("Some.Movie.(2016).1080p.BluRay.DTS.X265.HEVC.mkv", probe("video copy + eac3", ("eac3", 6))),
                         "Some.Movie.(2016).1080p.BluRay.DDP5.1.X265.HEVC.mkv")

    def test_video_only_keeps_dts_word(self):
        # converted before DTS->E-AC3 was on: the DTS track is still there
        self.assertEqual(self.new("Other.Movie.2014.1080p.BluRay.DTS.x264-GRP.mkv", probe("qsv q21", ("dts", 6))),
                         "Other.Movie.2014.1080p.BluRay.DTS.x265-GRP.mkv")

    def test_dts_left_in_another_track(self):
        self.assertEqual(self.new("Movie.2010.DTS.x264-GRP.mkv", probe("qsv q21 + eac3", ("eac3", 6), ("dts", 2))),
                         "Movie.2010.DTS.x265-GRP.mkv")

    def test_stereo(self):
        self.assertEqual(self.new("Show.S01E01.720p.BluRay.DTS.x264-GRP.mkv", probe("qsv q24 + eac3", ("eac3", 2))),
                         "Show.S01E01.720p.BluRay.DDP2.0.x265-GRP.mkv")

    def test_not_ours_or_already_right(self):
        self.assertIsNone(self.new("Other.2010.x264.mkv", probe(None, ("ac3", 6))))
        self.assertIsNone(self.new("Right.2010.x265.mkv", probe("qsv q21", ("ac3", 6))))

    def test_target_exists(self):
        (self.d / "Dup.2010.x265.mkv").write_text("x")
        self.assertIsNone(self.new("Dup.2010.x264.mkv", probe("qsv q21", ("ac3", 6))))


if __name__ == "__main__":
    unittest.main()
