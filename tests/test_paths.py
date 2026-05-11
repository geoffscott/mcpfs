import pytest

from mcpfs.paths import PathError, normalize, normalize_prefix


class TestNormalize:
    def test_strips_leading_and_trailing_slashes(self):
        assert normalize("/foo/bar/") == "foo/bar"

    def test_plain_path(self):
        assert normalize("foo/bar/baz.txt") == "foo/bar/baz.txt"

    @pytest.mark.parametrize(
        "bad",
        [
            "",
            "/",
            "..",
            "foo/../bar",
            "foo/./bar",
            "foo//bar",
            "foo\\bar",
            "foo\x00bar",
            "foo\x01bar",
        ],
    )
    def test_rejects_unsafe(self, bad):
        with pytest.raises(PathError):
            normalize(bad)

    def test_rejects_oversized(self):
        with pytest.raises(PathError):
            normalize("a" * 1025)


class TestNormalizePrefix:
    def test_empty_is_root(self):
        assert normalize_prefix("") == ""
        assert normalize_prefix("/") == ""

    def test_adds_trailing_slash(self):
        assert normalize_prefix("foo/bar") == "foo/bar/"

    def test_rejects_unsafe(self):
        with pytest.raises(PathError):
            normalize_prefix("foo/../bar")
