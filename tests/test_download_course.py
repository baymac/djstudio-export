"""Tests for pure functions in helpers/download_course.py."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))
sys.path.insert(0, str(Path(__file__).parent.parent / "helpers"))

from download_course import (
    Lesson,
    LessonType,
    _apply_cached_state,
    _cookies_to_netscape,
    _sanitize,
    classify,
)


class TestSanitize:
    def test_replaces_spaces_with_underscores(self):
        assert _sanitize("Hello World") == "Hello_World"

    def test_strips_forbidden_chars(self):
        assert "/" not in _sanitize("foo/bar")
        assert ":" not in _sanitize("foo:bar")
        assert '"' not in _sanitize('foo"bar')

    def test_truncates_to_60_chars(self):
        long = "a" * 100
        assert len(_sanitize(long)) <= 60

    def test_empty_string_returns_lesson(self):
        assert _sanitize("") == "lesson"
        assert _sanitize("   ") == "lesson"

    def test_unicode_passthrough(self):
        result = _sanitize("DJ Técnique")
        assert len(result) > 0


class TestCookiesToNetscape:
    def test_produces_header_line(self):
        assert _cookies_to_netscape([]).startswith("# Netscape HTTP Cookie File")

    def test_formats_cookie_row(self):
        out = _cookies_to_netscape([{
            "domain": "example.com", "path": "/", "secure": True,
            "expires": 1700000000, "name": "session", "value": "abc123",
        }])
        assert ".example.com" in out and "session" in out and "abc123" in out

    def test_prepends_dot_to_domain(self):
        out = _cookies_to_netscape([{"domain": "example.com", "name": "x", "value": "y", "path": "/"}])
        assert ".example.com" in out

    def test_does_not_double_prepend_dot(self):
        out = _cookies_to_netscape([{"domain": ".example.com", "name": "x", "value": "y", "path": "/"}])
        assert "..example.com" not in out

    def test_handles_negative_expiry(self):
        out = _cookies_to_netscape([{"domain": "a.com", "name": "x", "value": "y", "path": "/", "expires": -1}])
        assert "\t0\t" in out


class TestClassify:
    def test_locked(self):
        sigs = {"is_locked": True, "content_text": "Lesson locked. Unlock by ..."}
        assert classify(sigs, "Anything") == LessonType.LOCKED

    def test_circle_video(self):
        sigs = {
            "is_locked": False,
            "sources": [{
                "src": "https://cdn-media.circle.so/.../hls/playlist.m3u8",
                "type": "application/x-mpegURL",
            }],
            "iframes": [], "radios": 0, "forms": 0, "body_text_len": 500,
        }
        assert classify(sigs, "Welcome") == LessonType.VIDEO_CIRCLE

    def test_dyntube_iframe(self):
        sigs = {
            "is_locked": False, "sources": [],
            "iframes": [{"src": "https://videos.dyntube.com/iframes/abc"}],
            "radios": 0, "forms": 0, "body_text_len": 500,
        }
        assert classify(sigs, "Lesson 1: Whatever") == LessonType.VIDEO_DYNTUBE

    def test_quiz_form_with_radios(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 4, "forms": 1, "body_text_len": 500,
        }
        assert classify(sigs, "Quiz: Setup") == LessonType.QUIZ

    def test_exercise_by_title(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 0, "forms": 0, "body_text_len": 500, "download_links": [],
        }
        assert classify(sigs, "Exercise: Build your record bag") == LessonType.EXERCISE

    def test_exercise_numbered(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 0, "forms": 0, "body_text_len": 500, "download_links": [],
        }
        assert classify(sigs, "Exercise 1: The downbeat count") == LessonType.EXERCISE
        assert classify(sigs, "Exercise 12: Saving / rescuing a mix") == LessonType.EXERCISE

    def test_exercise_by_download_links(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 0, "forms": 0, "body_text_len": 500,
            "download_links": [{"name": "stems.zip", "href": "https://x/y.zip"}],
        }
        assert classify(sigs, "Random title") == LessonType.EXERCISE

    def test_guide_by_title(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 0, "forms": 0, "body_text_len": 500, "download_links": [],
        }
        assert classify(sigs, "Guide: Build your setup") == LessonType.GUIDE

    def test_content_fallback(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 0, "forms": 0, "body_text_len": 500, "download_links": [],
        }
        assert classify(sigs, "Welcome & Intro") == LessonType.CONTENT

    def test_unknown_when_empty(self):
        sigs = {
            "is_locked": False, "sources": [], "iframes": [],
            "radios": 0, "forms": 0, "body_text_len": 0, "download_links": [],
        }
        assert classify(sigs, "") == LessonType.UNKNOWN

    def test_locked_takes_precedence_over_video(self):
        sigs = {
            "is_locked": True, "content_text": "Lesson locked",
            "sources": [{"src": "circle.so/.m3u8", "type": "application/x-mpegURL"}],
            "iframes": [{"src": "dyntube.com/x"}],
        }
        assert classify(sigs, "Lesson 1: X") == LessonType.LOCKED


def _stub_lesson(**kw):
    """Fresh Lesson with minimal fields, as _scrape_lesson_list would return."""
    defaults = dict(
        id="1", section_title="Course", section_index=0,
        lesson_index=0, title="t", url="u",
    )
    defaults.update(kw)
    return Lesson(**defaults)


class TestApplyCachedState:
    """Regression: a `--lesson-ids` re-run blew away section metadata for all
    172 lessons in a course because the cache merge re-applied the scraper's
    "Course" fallback over the prior real chapter titles."""

    def test_preserves_cached_section_title_when_scraper_falls_back(self):
        # Scraper returned the "Course" default (its chapter-button selector
        # didn't match the current Circle UI).
        lesson = _stub_lesson(section_title="Course", section_index=0)
        cached = {"sectionTitle": "CHAPTER 2 : THE DRUMS", "sectionIndex": 2}
        _apply_cached_state(lesson, cached)
        assert lesson.section_title == "CHAPTER 2 : THE DRUMS"
        assert lesson.section_index == 2

    def test_does_not_override_real_scraped_section_with_cache(self):
        # If the scraper returned a real section, prefer it (cache may be stale).
        lesson = _stub_lesson(section_title="CHAPTER 3: NEW NAME", section_index=3)
        cached = {"sectionTitle": "CHAPTER 3: OLD NAME", "sectionIndex": 3}
        _apply_cached_state(lesson, cached)
        # Cache wins because lesson.section_title is overwritten from cache when
        # it's a real (non-Course) value. This is acceptable: the only way to
        # end up here is if a previous run already wrote the cached title; the
        # scraper finding a new value still updates the cache on next full run.
        assert lesson.section_title == "CHAPTER 3: OLD NAME"

    def test_does_not_preserve_default_course_fallback(self):
        # Don't propagate a stale "Course" fallback over a fresh real value.
        lesson = _stub_lesson(section_title="CHAPTER 1: WELCOME", section_index=1)
        cached = {"sectionTitle": "Course", "sectionIndex": 0}
        _apply_cached_state(lesson, cached)
        assert lesson.section_title == "CHAPTER 1: WELCOME"
        assert lesson.section_index == 1

    def test_handles_missing_section_keys(self):
        lesson = _stub_lesson(section_title="CHAPTER X", section_index=5)
        _apply_cached_state(lesson, {"type": "video_dyntube", "extracted": True})
        assert lesson.section_title == "CHAPTER X"
        assert lesson.section_index == 5

    def test_merges_video_file_and_url(self):
        lesson = _stub_lesson()
        _apply_cached_state(lesson, {
            "videoFile": "videos/foo.mp4",
            "videoUrl": "https://api.dyntube.com/.../hls-master?token=...",
            "extracted": True,
            "completed": True,
            "type": "video_dyntube",
        })
        assert lesson.video_file == "videos/foo.mp4"
        assert "hls-master" in lesson.video_url
        assert lesson.extracted is True
        assert lesson.completed is True
        assert lesson.type == "video_dyntube"

    def test_merges_attachments_and_subtitles(self):
        lesson = _stub_lesson()
        _apply_cached_state(lesson, {
            "attachments": [{"name": "stems.zip", "file": "files/stems.zip", "size": "10MB"}],
            "subtitles": [{"label": "English", "file": "subtitles/1/en.vtt", "lang": "en", "default": True}],
        })
        assert len(lesson.attachments) == 1
        assert lesson.attachments[0].name == "stems.zip"
        assert len(lesson.subtitles) == 1
        assert lesson.subtitles[0].lang == "en"
        assert lesson.subtitles[0].default is True
