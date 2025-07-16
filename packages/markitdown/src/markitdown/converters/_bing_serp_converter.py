import re
import base64
import binascii
from urllib.parse import parse_qs, urlparse
from typing import Any, BinaryIO
from bs4 import BeautifulSoup

from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from ._markdownify import _CustomMarkdownify

ACCEPTED_MIME_TYPE_PREFIXES = [
    "text/html",
    "application/xhtml",
]

ACCEPTED_FILE_EXTENSIONS = [
    ".html",
    ".htm",
]


class BingSerpConverter(DocumentConverter):
    """
    Handle Bing results pages (only the organic search results).
    NOTE: It is better to use the Bing API
    """

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> bool:
        """
        Make sure we're dealing with HTML content *from* Bing.
        """

        url = stream_info.url or ""
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if not re.search(r"^https://www\.bing\.com/search\?q=", url):
            # Not a Bing SERP URL
            return False

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        for prefix in ACCEPTED_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        # Not HTML content
        return False

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        assert stream_info.url is not None

        # Parse the query parameters (fast)
        parsed_qs = urlparse(stream_info.url)
        query = parse_qs(parsed_qs.query).get("q", [""])[0]

        # Parse the stream
        encoding = "utf-8" if stream_info.charset is None else stream_info.charset
        soup = BeautifulSoup(file_stream, "html.parser", from_encoding=encoding)

        # Compile regex once (faster)
        newlines_re = re.compile(r'\n+')

        # Mark for deletion to avoid repeated find_all passes
        algoSlug_icons = set()
        tptts = []

        # Mark relevant tags in a single pass, plus collect results (.b_algo)
        b_algo_results = []
        for tag in soup.find_all(True, class_=['b_algo', 'tptt', 'algoSlug_icon']):
            classes = tag.get('class', [])
            if 'b_algo' in classes:
                b_algo_results.append(tag)
            if 'algoSlug_icon' in classes:
                algoSlug_icons.add(tag)
            if 'tptt' in classes:
                tptts.append(tag)

        # Clean up some formatting (merged tptt and algoSlug_icon)
        for tptt in tptts:
            if hasattr(tptt, "string") and tptt.string:
                tptt.string += " "
        for slug in algoSlug_icons:
            slug.extract()

        # Prepare converter (construct once)
        _markdownify = _CustomMarkdownify(**kwargs)
        results = []

        # Loop over result tags, decode URLs and convert to markdown
        for result in b_algo_results:
            # Rewrite redirect urls (only do if tag has child anchors)
            anchors_with_href = result.find_all("a", href=True)
            if anchors_with_href:
                for a in anchors_with_href:
                    href = a.get("href")
                    parsed_href = urlparse(href)
                    qs = parse_qs(parsed_href.query)
                    # The destination is contained in the u parameter (base64 encoded, with some prefix)
                    u_vals = qs.get("u")
                    if u_vals:
                        # Simply and safely extract the base64 payload (protection from short strings)
                        u_val = u_vals[0]
                        if len(u_val) > 2:
                            b64 = u_val[2:].strip() + "=="
                            try:
                                a["href"] = base64.b64decode(b64, altchars=b"-_").decode("utf-8")
                            except (UnicodeDecodeError, binascii.Error):
                                pass

            # Convert to markdown (major hotspot)
            md_result = _markdownify.convert_soup(result)
            # Remove leading/trailing whitespace and blank lines (do both efficiently)
            lines = [line.strip() for line in newlines_re.split(md_result) if line.strip()]
            results.append('\n'.join(lines))

        webpage_text = (
            f"## A Bing search for '{query}' found the following results:\n\n"
            + "\n\n".join(results)
        )

        return DocumentConverterResult(
            markdown=webpage_text,
            title=None if soup.title is None else soup.title.string,
        )
