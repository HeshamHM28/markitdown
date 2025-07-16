import io
from typing import Any, BinaryIO, Optional
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


class HtmlConverter(DocumentConverter):
    """Anything with content type text/html"""

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> bool:
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        if extension in ACCEPTED_FILE_EXTENSIONS:
            return True

        for prefix in ACCEPTED_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        return False

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        # Figure out encoding once only
        encoding = "utf-8" if stream_info.charset is None else stream_info.charset

        # Read and decode content in one go; use a faster parser if possible
        text = _fast_get_html_string(file_stream, encoding)
        try:
            soup = BeautifulSoup(text, "lxml")
        except Exception:
            soup = BeautifulSoup(text, "html.parser")

        # Efficient script/style removal
        _fast_strip_script_and_style(soup)

        # Get body if present, fallback to soup
        body_elm = soup.find("body")

        # Reuse _CustomMarkdownify instance
        markdownify_converter = _CustomMarkdownify(**kwargs)
        if body_elm is not None:
            webpage_text = markdownify_converter.convert_soup(body_elm)
        else:
            webpage_text = markdownify_converter.convert_soup(soup)

        # Remove leading/trailing \n
        webpage_text = webpage_text.strip()

        # Use .string if soup.title found, else None
        title = soup.title.string if soup.title is not None else None

        return DocumentConverterResult(
            markdown=webpage_text,
            title=title,
        )

    def convert_string(
        self, html_content: str, *, url: Optional[str] = None, **kwargs
    ) -> DocumentConverterResult:
        """
        Non-standard convenience method to convert a string to markdown.
        Given that many converters produce HTML as intermediate output, this
        allows for easy conversion of HTML to markdown.
        """
        # Avoid multiple encode/decode; use BytesIO, as original
        return self.convert(
            file_stream=io.BytesIO(html_content.encode("utf-8")),
            stream_info=StreamInfo(
                mimetype="text/html",
                extension=".html",
                charset="utf-8",
                url=url,
            ),
            **kwargs,
        )


def _fast_get_html_string(file_stream: BinaryIO, encoding: str) -> str:
    # Read all bytes at once and decode (avoiding partials)
    html_bytes = file_stream.read()
    return html_bytes.decode(encoding, errors="replace")

def _fast_strip_script_and_style(soup):
    # Remove <script> and <style> tags in a single pass, using decompose for speed
    tags = soup.find_all(["script", "style"])
    for tag in tags:
        tag.decompose()
