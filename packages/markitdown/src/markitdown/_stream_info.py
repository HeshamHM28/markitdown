from dataclasses import dataclass
from typing import Optional


@dataclass(kw_only=True, frozen=True)
class StreamInfo:
    """The StreamInfo class is used to store information about a file stream.
    All fields can be None, and will depend on how the stream was opened.
    """

    mimetype: Optional[str] = None
    extension: Optional[str] = None
    charset: Optional[str] = None
    filename: Optional[
        str
    ] = None  # From local path, url, or Content-Disposition header
    local_path: Optional[str] = None  # If read from disk
    url: Optional[str] = None  # If read from url

    def copy_and_update(self, *args, **kwargs):
        """Copy the StreamInfo object and update it with the given StreamInfo
        instance and/or other keyword arguments."""

        # Fastest path: no args/kwargs - just return self (not mandatory, but ultra-fast for this case)
        if not args and not kwargs:
            return self

        # Start with self's own dict (no need for asdict, __dict__ is fine, all fields are shallow, and frozen ensures safety)
        new_info = dict(self.__dict__)

        # Update with all non-None values from provided StreamInfo instances
        for si in args:
            assert isinstance(si, StreamInfo)
            # Avoid asdict. Direct field access:
            for key, value in si.__dict__.items():
                if value is not None:
                    new_info[key] = value

        # Apply final updates from kwargs
        if kwargs:
            new_info.update(kwargs)

        return StreamInfo(**new_info)
