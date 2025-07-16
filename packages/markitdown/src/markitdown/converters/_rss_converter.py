from defusedxml import minidom
from xml.dom.minidom import Document, Element
from typing import BinaryIO, Any, Union
from bs4 import BeautifulSoup
from .._stream_info import StreamInfo
from .._base_converter import DocumentConverter, DocumentConverterResult

PRECISE_MIME_TYPE_PREFIXES = [
    "application/rss",
    "application/rss+xml",
    "application/atom",
    "application/atom+xml",
]

PRECISE_FILE_EXTENSIONS = [".rss", ".atom"]

CANDIDATE_MIME_TYPE_PREFIXES = [
    "text/xml",
    "application/xml",
]

CANDIDATE_FILE_EXTENSIONS = [
    ".xml",
]


class RssConverter(DocumentConverter):
    """Convert RSS / Atom type to markdown"""

    def __init__(self):
        super().__init__()
        self._kwargs = {}

    def accepts(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> bool:
        mimetype = (stream_info.mimetype or "").lower()
        extension = (stream_info.extension or "").lower()

        # Check for precise mimetypes and file extensions
        if extension in PRECISE_FILE_EXTENSIONS:
            return True

        for prefix in PRECISE_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return True

        # Check for precise mimetypes and file extensions
        if extension in CANDIDATE_FILE_EXTENSIONS:
            return self._check_xml(file_stream)

        for prefix in CANDIDATE_MIME_TYPE_PREFIXES:
            if mimetype.startswith(prefix):
                return self._check_xml(file_stream)

        return False

    def _check_xml(self, file_stream: BinaryIO) -> bool:
        cur_pos = file_stream.tell()
        try:
            doc = minidom.parse(file_stream)
            return self._feed_type(doc) is not None
        except BaseException as _:
            pass
        finally:
            file_stream.seek(cur_pos)
        return False

    def _feed_type(self, doc: Any) -> str | None:
        if doc.getElementsByTagName("rss"):
            return "rss"
        elif doc.getElementsByTagName("feed"):
            root = doc.getElementsByTagName("feed")[0]
            if root.getElementsByTagName("entry"):
                # An Atom feed must have a root element of <feed> and at least one <entry>
                return "atom"
        return None

    def convert(
        self,
        file_stream: BinaryIO,
        stream_info: StreamInfo,
        **kwargs: Any,  # Options to pass to the converter
    ) -> DocumentConverterResult:
        self._kwargs = kwargs
        doc = minidom.parse(file_stream)
        feed_type = self._feed_type(doc)

        if feed_type == "rss":
            return self._parse_rss_type(doc)
        elif feed_type == "atom":
            return self._parse_atom_type(doc)
        else:
            raise ValueError("Unknown feed type")

    def _parse_atom_type(self, doc: Document) -> DocumentConverterResult:
        """Parse the type of an Atom feed.

        Returns None if the feed type is not recognized or something goes wrong.
        """
        root = doc.getElementsByTagName("feed")[0]
        title = self._get_data_by_tag_name(root, "title")
        subtitle = self._get_data_by_tag_name(root, "subtitle")
        entries = root.getElementsByTagName("entry")
        md_text = f"# {title}\n"
        if subtitle:
            md_text += f"{subtitle}\n"
        for entry in entries:
            entry_title = self._get_data_by_tag_name(entry, "title")
            entry_summary = self._get_data_by_tag_name(entry, "summary")
            entry_updated = self._get_data_by_tag_name(entry, "updated")
            entry_content = self._get_data_by_tag_name(entry, "content")

            if entry_title:
                md_text += f"\n## {entry_title}\n"
            if entry_updated:
                md_text += f"Updated on: {entry_updated}\n"
            if entry_summary:
                md_text += self._parse_content(entry_summary)
            if entry_content:
                md_text += self._parse_content(entry_content)

        return DocumentConverterResult(
            markdown=md_text,
            title=title,
        )

    def _parse_rss_type(self, doc: Document) -> DocumentConverterResult:
        """Parse the type of an RSS feed.

        Returns None if the feed type is not recognized or something goes wrong.
        """

        root = doc.getElementsByTagName("rss")[0]
        channel_list = root.getElementsByTagName("channel")
        if not channel_list:
            raise ValueError("No channel found in RSS feed")
        channel = channel_list[0]

        # Cache all direct child elements by tag name for <channel>
        channel_children = self._first_element_map(channel, {"title", "description"})
        channel_title = self._get_first_node_data(channel_children.get("title"))
        channel_description = self._get_first_node_data(channel_children.get("description"))

        items = channel.getElementsByTagName("item")

        md_lines = []  # use list to accumulate markdown lines, faster than +=

        if channel_title:
            md_lines.append(f"# {channel_title}")
        if channel_description:
            md_lines.append(channel_description)

        # Pre-define tags to extract for <item>
        item_tag_fields = {"title", "description", "pubDate", "content:encoded"}

        for item in items:
            # Cache all direct child elements by tag name for <item>
            item_children = self._first_element_map(item, item_tag_fields)
            title = self._get_first_node_data(item_children.get("title"))
            description = self._get_first_node_data(item_children.get("description"))
            pubDate = self._get_first_node_data(item_children.get("pubDate"))
            content = self._get_first_node_data(item_children.get("content:encoded"))

            if title:
                md_lines.append(f"\n## {title}")
            if pubDate:
                md_lines.append(f"Published on: {pubDate}")
            if description:
                md_lines.append(self._parse_content(description))
            if content:
                md_lines.append(self._parse_content(content))

        # Build markdown text as one string at the end
        md_text = "\n".join(md_lines)

        return DocumentConverterResult(
            markdown=md_text,
            title=channel_title,
        )

    def _parse_content(self, content: str) -> str:
        """Parse the content of an RSS feed item"""
        try:
            # using bs4 because many RSS feeds have HTML-styled content
            soup = BeautifulSoup(content, "html.parser")
            # Use pre-instantiated converter for speed
            return self._markdownify_converter.convert_soup(soup)
        except BaseException as _:
            return content

    def _get_data_by_tag_name(
        self, element: Element, tag_name: str
    ) -> Union[str, None]:
        """Get data from first child element with the given tag name.
        Returns None when no such element is found.
        """
        nodes = element.getElementsByTagName(tag_name)
        if not nodes:
            return None
        fc = nodes[0].firstChild
        if fc:
            if hasattr(fc, "data"):
                return fc.data
        return None

    def _first_element_map(self, element: Element, tag_names: set) -> dict:
        """
        For a given DOM element and set of tag_names,
        returns a dict mapping tag_name to the FIRST found child element for each tag.
        """
        tag_map = {}
        children = element.childNodes
        for child in children:
            if child.nodeType == 1:  # ELEMENT_NODE
                name = child.tagName
                if name in tag_names and name not in tag_map:
                    tag_map[name] = child
        return tag_map

    def _get_first_node_data(self, elt: Union[Element, None]) -> Union[str, None]:
        """Get data from the first child node, if exists, else None."""
        if elt is not None:
            fc = elt.firstChild
            if fc and hasattr(fc, "data"):
                return fc.data
        return None
