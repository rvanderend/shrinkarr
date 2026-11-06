"""Run with: python -m unittest discover tests

The names are made up, but follow the spellings found in real release names.
"""
import tempfile
import unittest
from pathlib import Path

from app.naming import new_stem, sidecars


class Video(unittest.TestCase):
    def check(self, before, after):
        self.assertEqual(new_stem(before, video=True, dts=False), after)

    def test_styles(self):
        self.check("Some.Movie.2017.1080p.BluRay.DD5.1.x264.NLSubs-GRP", "Some.Movie.2017.1080p.BluRay.DD5.1.x265.NLSubs-GRP")
        self.check("Some.Movie.2002.NORDiC.1080p.WEB-DL.DDP5.1.H.264-GROUP", "Some.Movie.2002.NORDiC.1080p.WEB-DL.DDP5.1.H.265-GROUP")
        self.check("Some.Show.S02E01.1080p.WEB-DL.DD5.1.H264-GRP", "Some.Show.S02E01.1080p.WEB-DL.DD5.1.H265-GRP")
        self.check("Some Movie (2010) 1080P.X264.NL.SUBBED.Name", "Some Movie (2010) 1080P.X265.NL.SUBBED.Name")
        self.check("some.movie.2013.1080p.dtshd-ma.x264-grp", "some.movie.2013.1080p.dtshd-ma.x265-grp")
        self.check("Movie.2010.720p.BluRay.AVC.DTS-HD.MA.5.1-GRP", "Movie.2010.720p.BluRay.HEVC.DTS-HD.MA.5.1-GRP")
        self.check("Some.Show.S02e08.Title.1080P.Bluray.Remux.Avc.Dts-Hd.Ma.5.1-Nogrp-8",
                   "Some.Show.S02e08.Title.1080P.Bluray.Remux.Hevc.Dts-Hd.Ma.5.1-Nogrp-8")
        self.check("Some.Movie.2014.720p.BRRiP.XVID.AC3-GROUP_Hardcoded Subs", "Some.Movie.2014.720p.BRRiP.X265.AC3-GROUP_Hardcoded Subs")
        self.check("Some_Movie_2007_1080p_Bluray_Remux_VC1_DD_5.1", "Some_Movie_2007_1080p_Bluray_Remux_X265_DD_5.1")

    def test_no_word_no_change(self):
        for name in ("Some Movie (1977) 1080p NL Subs",
                     "Some Movie (2013) NL Gespr",
                     "Some.Movie.2014.LIMITED.1080p.BluRay.x265-GRP",  # already right
                     "Avcilar.2019.1080p"):  # AVC inside a word
            self.check(name, name)

    def test_audio_only_keeps_video_word(self):
        name = "Some.Movie.2010.1080p.BluRay.DTS.x264-GRP"
        self.assertEqual(new_stem(name, video=False, dts=True), "Some.Movie.2010.1080p.BluRay.DDP5.1.x264-GRP")


class Audio(unittest.TestCase):
    def check(self, before, after, channels=6):
        self.assertEqual(new_stem(before, video=True, dts=True, channels=channels), after)

    def test_dts_family(self):
        self.check("Some.Movie.2016.1080p.BluRay.DTS.x264-GRP", "Some.Movie.2016.1080p.BluRay.DDP5.1.x265-GRP")
        self.check("Some.Show.S02e01.Title.1080P.Bluray.Remux.Avc.Dts-Hd.Ma.5.1-Nogrp-1",
                   "Some.Show.S02e01.Title.1080P.Bluray.Remux.Hevc.DDP5.1-Nogrp-1")
        self.check("SOME MOVIE (2016) 1080p Bluray DTS-HD MA5_1 RETAIL NL subs", "SOME MOVIE (2016) 1080p Bluray DDP5.1 RETAIL NL subs")
        self.check("Movie (2010) DTS-HD 5 1", "Movie (2010) DDP5.1")
        self.check("Movie.2010.DTS-HD.MA-5.1.-GRP", "Movie.2010.DDP5.1.-GRP")
        self.check("Movie.2010.1080p.DTS-HD-MA.x264-GRP", "Movie.2010.1080p.DDP5.1.x265-GRP")
        self.check("some.movie.2013.1080p.dtshd-ma.x264-grp", "some.movie.2013.1080p.ddp5.1.x265-grp")
        self.check("Movie.2018.2160p.UHD.BluRay.DTS-X.7.1.HEVC-GRP", "Movie.2018.2160p.UHD.BluRay.DDP5.1.HEVC-GRP")
        self.check("Movie.2004.DTS-ES.x264-GRP", "Movie.2004.DDP5.1.x265-GRP")
        self.check("Some Show S01E01_ Title - 1080px264_BD2Mkv_DTS+NL_audio_sub",
                   "Some Show S01E01_ Title - 1080px264_BD2Mkv_DDP5.1+NL_audio_sub")
        self.check("Some.Show.S02E14.1080p.BluRay.DTS.x264-GRP", "Some.Show.S02E14.1080p.BluRay.DDP2.0.x265-GRP", channels=2)

    def test_not_dts_x(self):
        # DTS followed by x264/X265, not a DTS:X track
        self.check("Some.Movie.2004.Unrated.1080p.BluRay.DTS.x264-GRP", "Some.Movie.2004.Unrated.1080p.BluRay.DDP5.1.x265-GRP")
        self.check("Some.Movie.(2016).1080p.BluRay.DTS.X265.HEVC", "Some.Movie.(2016).1080p.BluRay.DDP5.1.X265.HEVC")
        self.check("Movie.2010.DTS.x 264-GRP", "Movie.2010.DDP5.1.x 265-GRP")
        self.check("Some Movie (2002) 1080p DTS x265", "Some Movie (2002) 1080p DDP5.1 x265")

    def test_release_group_survives(self):
        # groups that start like a DTS word
        self.check("Movie.2011.1080p.BluRay.x264.DTS-HDMaster", "Movie.2011.1080p.BluRay.x265.DDP5.1-HDMaster")
        self.check("Movie.2009.720p.DTS-ABC", "Movie.2009.720p.DDP5.1-ABC")

    def test_other_tracks_stay(self):
        self.check("Some.Movie.2017.1080p.BluRay.DD5.1.DTS.x264.NLSubs-GRP", "Some.Movie.2017.1080p.BluRay.DD5.1.DDP5.1.x265.NLSubs-GRP")
        self.check("Some Movie (2015) 1080p Bluray DTS & DD5.1 NL Subs", "Some Movie (2015) 1080p Bluray DDP5.1 & DD5.1 NL Subs")
        self.check("Movie.2015.DDP5.1.DTS-GRP", "Movie.2015.DDP5.1-GRP")  # no double word

    def test_words_inside_titles(self):
        for name in ("The.DTSer.2010.1080p", "Mr.Wordsworth.2010"):
            self.check(name, name)


class Sidecars(unittest.TestCase):
    def test_sidecars(self):
        with tempfile.TemporaryDirectory() as d:
            d = Path(d)
            names = ["Movie.2010.x264.mkv", "Movie.2010.x264.nl.srt", "Movie.2010.x264.en.forced.srt",
                     "Movie.2010.x264.nfo", "Movie.2010.x264-poster.jpg", "Movie.2010.x264-trailer.mov",
                     "Movie.2010.x264.Part.2.mkv", "Movie.2010.x264.Part.2.nl.srt",
                     "movie.nfo", "poster.jpg", ".Movie.2010.x264.shrinkarr-tmp"]
            for n in names:
                (d / n).write_text("x")
            got = [p.name for p in sidecars(d / "Movie.2010.x264.mkv")]
            self.assertEqual(got, ["Movie.2010.x264-poster.jpg", "Movie.2010.x264-trailer.mov",
                                   "Movie.2010.x264.en.forced.srt", "Movie.2010.x264.nfo", "Movie.2010.x264.nl.srt"])
            self.assertEqual([p.name for p in sidecars(d / "Movie.2010.x264.Part.2.mkv")], ["Movie.2010.x264.Part.2.nl.srt"])


if __name__ == "__main__":
    unittest.main()
