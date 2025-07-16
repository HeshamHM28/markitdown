import re
import bs4
from typing import Any, BinaryIO

from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from ._markdownify import _CustomMarkdownify

ACCEPTED_MIME_TYPE_PREFIXES = ("text/html", "application/xhtml")

ACCEPTED_FILE_EXTENSIONS = {".html", ".htm"}


class WikipediaConverter(DocumentConverter):
    """Handle Wikipedia pages separately, focusing only on the main document content."""

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> bool:
        """
        Make sure we're dealing with HTML content *from* Wikipedia.
        """

        url = stream_info.url or ""
        # Fast Wikipedia url check (no regex)
        url_low = url.lower()
        # short circuit: check prefix using tuple
        if not url_low.startswith(WIKIPEDIA_PREFIXES):
            # Not a Wikipedia URL
            return False

        extension = (stream_info.extension or "").lower()
        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        mimetype = (stream_info.mimetype or "").lower()
        if mimetype.startswith(ACCEPTED_MIME_TYPE_PREFIXES):
            return True

        # Not HTML content
        return False

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        # Parse the stream
        encoding = "utf-8" if stream_info.charset is None else stream_info.charset
        soup = bs4.BeautifulSoup(file_stream, "html.parser", from_encoding=encoding)

        # Remove javascript and style blocks
        for script in soup(["script", "style"]):
            script.extract()

        # Print only the main content
        body_elm = soup.find("div", {"id": "mw-content-text"})
        title_elm = soup.find("span", {"class": "mw-page-title-main"})

        webpage_text = ""
        main_title = None if soup.title is None else soup.title.string

        if body_elm:
            # What's the title
            if title_elm and isinstance(title_elm, bs4.Tag):
                main_title = title_elm.string

            # Convert the page
            webpage_text = f"# {main_title}\n\n" + _CustomMarkdownify(
                **kwargs
            ).convert_soup(body_elm)
        else:
            webpage_text = _CustomMarkdownify(**kwargs).convert_soup(soup)

        return DocumentConverterResult(
            markdown=webpage_text,
            title=main_title,
        )

WIKIPEDIA_PREFIXES = tuple(
    f"https://{cc}.wikipedia.org/"
    for cc in (
        "en", "de", "fr", "es", "it", "ru", "ja", "zh", "pt", "pl", "nl", "ar",
        "sv", "uk", "ca", "fi", "cs", "hu", "ko", "tr", "no", "da", "ro", "vi",
        "eo", "sr", "sk", "he", "lt", "sl", "bg", "hr", "et", "ms", "id", "th",
        "el", "simple"
    )
) + tuple(
    f"http://{cc}.wikipedia.org/"
    for cc in (
        "en", "de", "fr", "es", "it", "ru", "ja", "zh", "pt", "pl", "nl", "ar",
        "sv", "uk", "ca", "fi", "cs", "hu", "ko", "tr", "no", "da", "ro", "vi",
        "eo", "sr", "sk", "he", "lt", "sl", "bg", "hr", "et", "ms", "id", "th",
        "el", "simple"
    )
)
