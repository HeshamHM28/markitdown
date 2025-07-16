import sys
import base64
import os
import io
import re
import html

from typing import BinaryIO, Any
from operator import attrgetter

from ._html_converter import HtmlConverter
from ._llm_caption import llm_caption
from .._base_converter import DocumentConverter, DocumentConverterResult
from .._stream_info import StreamInfo
from .._exceptions import MissingDependencyException, MISSING_DEPENDENCY_MESSAGE
import pptx

# Try loading optional (but in this case, required) dependencies
# Save reporting of any exceptions for later
_dependency_exc_info = None
try:
    import pptx
except ImportError:
    # Preserve the error and stack trace for later
    _dependency_exc_info = sys.exc_info()


ACCEPTED_MIME_TYPE_PREFIXES = [
    "application/vnd.openxmlformats-officedocument.presentationml",
]

ACCEPTED_FILE_EXTENSIONS = [".pptx"]


class PptxConverter(DocumentConverter):
    """
    Converts PPTX files to Markdown. Supports heading, tables and images with alt text.
    """

    def __init__(self):
        super().__init__()
        self._html_converter = HtmlConverter()

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
        # Check the dependencies
        if _dependency_exc_info is not None:
            raise MissingDependencyException(
                MISSING_DEPENDENCY_MESSAGE.format(
                    converter=type(self).__name__,
                    extension=".pptx",
                    feature="pptx",
                )
            ) from _dependency_exc_info[
                1
            ].with_traceback(  # type: ignore[union-attr]
                _dependency_exc_info[2]
            )

        presentation = pptx.Presentation(file_stream)
        md_lines = []
        slide_num = 0

        # Optimize regex precomp
        re_newlines = re.compile(r"[\r\n\[\]]")
        re_spaces = re.compile(r"\s+")
        re_nonword = re.compile(r"\W")

        # Early bindings
        is_picture = self._is_picture
        is_table = self._is_table
        convert_table_to_markdown = self._convert_table_to_markdown
        convert_chart_to_markdown = self._convert_chart_to_markdown
        mso_group = pptx.enum.shapes.MSO_SHAPE_TYPE.GROUP

        llm_caption_func = llm_caption

        get = getattr  # local alias for perf

        for slide in presentation.slides:
            slide_num += 1
            md_lines.append(f"\n\n<!-- Slide number: {slide_num} -->")
            title = slide.shapes.title

            def get_shape_content(shape, **kwargs):
                # Pictures
                if is_picture(shape):
                    llm_description = ""
                    alt_text = ""
                    llm_client = kwargs.get("llm_client")
                    llm_model = kwargs.get("llm_model")
                    if llm_client is not None and llm_model is not None:
                        # Prepare a file_stream and stream_info for the image data
                        image_obj = shape.image
                        image_filename = image_obj.filename
                        image_extension = os.path.splitext(image_filename)[1] if image_filename else None
                        image_stream_info = StreamInfo(
                            mimetype=image_obj.content_type,
                            extension=image_extension,
                            filename=image_filename,
                        )
                        image_stream = io.BytesIO(image_obj.blob)
                        try:
                            llm_description = llm_caption_func(
                                image_stream,
                                image_stream_info,
                                client=llm_client,
                                model=llm_model,
                                prompt=kwargs.get("llm_prompt"),
                            )
                        except Exception:
                            pass

                    # Also grab any description embedded in the deck
                    try:
                        # Fast, attribute access; fail silently
                        alt_text = shape._element._nvXxPr.cNvPr.attrib.get("descr", "")
                    except Exception:
                        pass

                    # Prepare the alt, escaping special characters
                    if llm_description or alt_text:
                        merged_alt = "\n".join(filter(None, (llm_description, alt_text)))
                    else:
                        merged_alt = shape.name
                    merged_alt = re_newlines.sub(" ", merged_alt)
                    merged_alt = re_spaces.sub(" ", merged_alt).strip()

                    # If keep_data_uris is True, use base64 encoding for images
                    if kwargs.get("keep_data_uris", False):
                        blob = shape.image.blob
                        content_type = shape.image.content_type or "image/png"
                        b64_string = base64.b64encode(blob).decode("utf-8")
                        md_lines.append(f"\n![{merged_alt}](data:{content_type};base64,{b64_string})")
                    else:
                        filename = re_nonword.sub("", shape.name) + ".jpg"
                        md_lines.append(f"\n![{merged_alt}]({filename})")

                # Tables
                elif is_table(shape):
                    md_lines.append(convert_table_to_markdown(shape.table, **kwargs))

                # Charts
                elif shape.has_chart:
                    md_lines.append(convert_chart_to_markdown(shape.chart))

                # Text areas
                elif shape.has_text_frame:
                    if shape is title:
                        md_lines.append("# " + shape.text.lstrip())
                    else:
                        md_lines.append(shape.text)

                # Group Shapes
                if get(shape, "shape_type", None) == mso_group:
                    subshapes = shape.shapes
                    # Avoid unnecessary sorted() if only one or two in most cases
                    subshapes_sorted = sorted(subshapes, key=attrgetter("top", "left")) if len(subshapes) > 1 else subshapes
                    for subshape in subshapes_sorted:
                        get_shape_content(subshape, **kwargs)

            shapes = slide.shapes
            shapes_sorted = sorted(shapes, key=attrgetter("top", "left")) if len(shapes) > 1 else shapes
            for shape in shapes_sorted:
                get_shape_content(shape, **kwargs)

            # If present, notes appended as markdown at end of slide processing
            if slide.has_notes_slide:
                notes_frame = slide.notes_slide.notes_text_frame
                if notes_frame is not None:
                    md_lines.append("\n\n### Notes:")
                    md_lines.append(notes_frame.text)

        # Strip leading/trailing whitespace at the very end
        md_content = "\n".join(md_lines).strip()
        return DocumentConverterResult(markdown=md_content)

    def _is_picture(self, shape):
        if shape.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PICTURE:
            return True
        if shape.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.PLACEHOLDER:
            if hasattr(shape, "image"):
                return True
        return False

    def _is_table(self, shape):
        if shape.shape_type == pptx.enum.shapes.MSO_SHAPE_TYPE.TABLE:
            return True
        return False

    def _convert_table_to_markdown(self, table, **kwargs):
        # Write the table as HTML, then convert it to Markdown
        html_table = "<html><body><table>"
        first_row = True
        for row in table.rows:
            html_table += "<tr>"
            for cell in row.cells:
                if first_row:
                    html_table += "<th>" + html.escape(cell.text) + "</th>"
                else:
                    html_table += "<td>" + html.escape(cell.text) + "</td>"
            html_table += "</tr>"
            first_row = False
        html_table += "</table></body></html>"

        return (
            self._html_converter.convert_string(html_table, **kwargs).markdown.strip()
            + "\n"
        )

    def _convert_chart_to_markdown(self, chart):
        try:
            md = "\n\n### Chart"
            if chart.has_title:
                md += f": {chart.chart_title.text_frame.text}"
            md += "\n\n"
            data = []
            category_names = [c.label for c in chart.plots[0].categories]
            series_names = [s.name for s in chart.series]
            data.append(["Category"] + series_names)

            for idx, category in enumerate(category_names):
                row = [category]
                for series in chart.series:
                    row.append(series.values[idx])
                data.append(row)

            markdown_table = []
            for row in data:
                markdown_table.append("| " + " | ".join(map(str, row)) + " |")
            header = markdown_table[0]
            separator = "|" + "|".join(["---"] * len(data[0])) + "|"
            return md + "\n".join([header, separator] + markdown_table[1:])
        except ValueError as e:
            # Handle the specific error for unsupported chart types
            if "unsupported plot type" in str(e):
                return "\n\n[unsupported chart]\n\n"
        except Exception:
            # Catch any other exceptions that might occur
            return "\n\n[unsupported chart]\n\n"
