import pytest
from wdmsworker.model.mime_types import MimeType, MimeTypes


@pytest.mark.parametrize(
    "mimetype,filename,expected",
    [
        (MimeTypes.PARQUET, "filename", "filename.parquet"),
        (MimeTypes.PARQUET, "filename.parquet", "filename.parquet"),
        (MimeTypes.JSON, "filename", "filename.json"),
    ],
)
def test_mime_type_add_extension(mimetype: MimeType, filename: str, expected: str):
    assert mimetype.add_extension(filename) == expected


@pytest.mark.parametrize(
    "from_type,to_type,filename,expected",
    [
        (MimeTypes.PARQUET, MimeTypes.JSON, "filename", "filename.json"),
        (MimeTypes.PARQUET, MimeTypes.PARQUET, "filename.parquet", "filename.parquet"),
        (MimeTypes.JSON, MimeTypes.PARQUET, "filename.json", "filename.parquet"),
        (MimeTypes.JSON, MimeTypes.PARQUET, "filename.index", "filename.index.parquet"),
    ],
)
def test_mime_type_replace_extension(from_type: MimeType, to_type: MimeType, filename: str, expected: str):
    assert to_type.replace_extension(filename, from_type) == expected


def test_match_extension():
    assert list(filter(MimeTypes.META.match_extension, ["f1.meta", "f2.json", "f3.META"])) == ["f1.meta", "f3.META"]
