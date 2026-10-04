"""Test BbML variants and attachment filenames independently of HTTP."""

import pytest

from blackboard_downloader.content import (
    body_files,
    file_key,
    resource_url,
    response_filename,
)
from blackboard_downloader.errors import BlackboardError

BASE = "https://blackboard.example"


def test_unicode_content_disposition_and_url_fallback():
    assert (
        response_filename(
            "attachment; filename*=UTF-8''cours%20%C3%A9t%C3%A9.pdf", BASE
        )
        == "cours été.pdf"
    )
    assert response_filename("", BASE + "/lecture%20one.pdf") == "lecture one.pdf"


def test_signed_webdav_urls_keep_stable_identity():
    assert file_key(BASE + "/bbcswebdav/xid-42_1?signature=old") == file_key(
        BASE + "/bbcswebdav/pid-2-dt-content-rid-42_1/xid-42_1?signature=new"
    )


def test_unresolved_resources_do_not_hide_valid_body_files():
    files = body_files(
        '<a href="bbupload://unpublished" data-bbfile=\'{"linkName":"Draft.pdf"}\'></a>'
        '<a href="/bbcswebdav/xid-42_1" data-bbfile="invalid json"></a>'
        '<a href="https://video.example/" data-bbtype="video"></a>',
        BASE,
    )
    assert files == [
        ("bbupload://unpublished", "Draft.pdf"),
        (BASE + "/bbcswebdav/xid-42_1", None),
    ]


@pytest.mark.parametrize("url", ["bbresource://invalid", "bbupload://draft"])
def test_unresolved_resource_urls_have_useful_errors(url):
    with pytest.raises(BlackboardError):
        resource_url(url)
