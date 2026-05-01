from pathlib import Path

from pharos.ingestion.parser import parse_feed


def test_parse_sample_rss_feed():
    body = (Path(__file__).parent / "fixtures" / "sample_feed.xml").read_bytes()
    feed = parse_feed(body)
    assert feed.title == "Sample Threat Feed"
    assert len(feed.entries) == 2
    titles = {e.title for e in feed.entries}
    assert "APT29 abuses CVE-2024-12345 in Exchange" in titles
    for e in feed.entries:
        assert e.url.startswith("https://example.com/articles/")
        assert e.published_at is not None
