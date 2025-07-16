import re
import markdownify

from typing import Any, Optional
from urllib.parse import quote, unquote, urlparse, urlunparse


class _CustomMarkdownify(markdownify.MarkdownConverter):
    """
    A custom version of markdownify's MarkdownConverter. Changes include:

    - Altering the default heading style to use '#', '##', etc.
    - Removing javascript hyperlinks.
    - Truncating images with large data:uri sources.
    - Ensuring URIs are properly escaped, and do not conflict with Markdown syntax
    """

    def __init__(self, **options: Any):
        options["heading_style"] = options.get("heading_style", markdownify.ATX)
        options["keep_data_uris"] = options.get("keep_data_uris", False)
        super().__init__(**options)

    def convert_hn(
        self,
        n: int,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ) -> str:
        """Same as usual, but be sure to start with a new line"""
        if not convert_as_inline:
            if not re.search(r"^\n", text):
                return "\n" + super().convert_hn(n, el, text, convert_as_inline)  # type: ignore

        return super().convert_hn(n, el, text, convert_as_inline)  # type: ignore

    def convert_a(
        self,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ):
        """Same as usual converter, but removes Javascript links and escapes URIs."""
        # Cache these lookups for speed
        options = self.options
        autolinks = options["autolinks"]
        default_title = options["default_title"]
        prefix, suffix, text = markdownify.chomp(text)  # type: ignore

        if not text:
            return ""

        # Quick attribute/lookup and pointer alias for fast execution
        find_parent = getattr(el, "find_parent", None)
        if find_parent is not None:
            has_pre = find_parent("pre") is not None
            if has_pre:
                return text

        # Inline variable lookups
        href = el.get("href")
        title = el.get("title")

        # Acceptable URI schemes (set for fast membership test)
        _valid_schemes = {"http", "https", "file"}

        # Escape URIs and skip non-http or file schemes
        if href:
            parsed_url = None
            try:
                # Avoid allocating parsed_url if not needed
                lower_scheme = href[:5].lower()
                if lower_scheme and ":" in href:
                    parsed_url = urlparse(href)
                    scheme = parsed_url.scheme
                    if scheme and scheme.lower() not in _valid_schemes:
                        return "%s%s%s" % (prefix, text, suffix)

                    # Only quote/unquote/replace path if needed
                    new_path = quote(unquote(parsed_url.path))
                    if new_path != parsed_url.path:
                        parsed_url = parsed_url._replace(path=new_path)
                        href = urlunparse(parsed_url)
                    else:
                        href = urlunparse(parsed_url)
                # If no scheme (relative), leave as is
            except Exception:
                return "%s%s%s" % (prefix, text, suffix)

        # For the replacement see #29: text nodes underscores are escaped
        # Use local var lookups
        if (
            autolinks
            and text.replace(r"\_", "_") == href
            and not title
            and not default_title
        ):
            # Shortcut syntax
            return "<%s>" % href
        if default_title and not title:
            title = href
        title_part = ' "%s"' % title.replace('"', r"\"") if title else ""
        return (
            "%s[%s](%s%s)%s" % (prefix, text, href, title_part, suffix)
            if href
            else text
        )

    def convert_img(
        self,
        el: Any,
        text: str,
        convert_as_inline: Optional[bool] = False,
        **kwargs,
    ) -> str:
        """Same as usual converter, but removes data URIs"""

        alt = el.attrs.get("alt", None) or ""
        src = el.attrs.get("src", None) or ""
        title = el.attrs.get("title", None) or ""
        title_part = ' "%s"' % title.replace('"', r"\"") if title else ""
        if (
            convert_as_inline
            and el.parent.name not in self.options["keep_inline_images_in"]
        ):
            return alt

        # Remove dataURIs
        if src.startswith("data:") and not self.options["keep_data_uris"]:
            src = src.split(",")[0] + "..."

        return "![%s](%s%s)" % (alt, src, title_part)

    def convert_soup(self, soup: Any) -> str:
        return super().convert_soup(soup)  # type: ignore
