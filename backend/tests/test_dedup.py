from pharos.ingestion.dedup import (
    canonicalize_url,
    content_simhash,
    hamming_distance_hex,
    url_hash,
)


def test_canonicalize_strips_tracking_params():
    a = "https://Example.COM/path/?utm_source=x&id=123"
    b = "http://example.com:80/path?id=123"
    assert canonicalize_url(a) == "https://example.com/path?id=123"
    assert canonicalize_url(b) == "http://example.com/path?id=123"


def test_url_hash_is_stable_across_equivalent_urls():
    assert url_hash("https://example.com/a/?utm_source=x") == url_hash(
        "https://example.com/a"
    )


def test_simhash_similar_articles_have_low_hamming_distance():
    a = (
        "APT29 was observed exploiting a Microsoft Exchange vulnerability "
        "to target European diplomats this week."
    )
    b = (
        "Russian state hackers exploited a Microsoft Exchange flaw to "
        "target European diplomats earlier this week."
    )
    c = "Cats and dogs lounge in the sun while bees gather pollen."
    ha, hb, hc = content_simhash(a), content_simhash(b), content_simhash(c)
    assert hamming_distance_hex(ha, hb) < hamming_distance_hex(ha, hc)
