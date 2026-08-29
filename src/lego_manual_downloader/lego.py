from dataclasses import dataclass, field
from functools import cached_property

import pathvalidate


@dataclass(frozen=True)
class LegoSet:
    number: str
    variant: str
    name: str
    year: str
    recorded_file_name: str | None = field(default=None, compare=False)

    @property
    def set_number(self) -> str:
        return f"{self.number}-{self.variant}"

    @cached_property
    def file_name(self) -> str:
        name = f"{self.set_number} {self.name} ({self.year}).pdf"
        return pathvalidate.sanitize_filename(name)

    @cached_property
    def current_file_name(self) -> str:
        """Where the manual is now; `file_name` is where it belongs."""
        if self.recorded_file_name is None:
            return self.file_name
        return pathvalidate.sanitize_filename(self.recorded_file_name)

    def __str__(self) -> str:
        return f"{self.set_number} - {self.name} ({self.year})"

    @staticmethod
    def from_dict(data: object) -> "LegoSet | None":
        if not isinstance(data, dict):
            return None
        try:
            return LegoSet(
                number=data["number"],
                variant=data["variant"],
                name=data["name"],
                year=data["year"],
                recorded_file_name=data.get("file"),
            )
        except KeyError:
            return None

    def to_dict(self) -> dict[str, str]:
        return {
            "number": self.number,
            "variant": self.variant,
            "name": self.name,
            "year": self.year,
            "file": self.current_file_name,
        }
