from dataclasses import dataclass
from functools import cached_property

import pathvalidate


@dataclass(frozen=True)
class LegoSet:
    number: str
    variant: str
    name: str
    year: str

    @property
    def set_number(self) -> str:
        return f"{self.number}-{self.variant}"

    @cached_property
    def file_name(self) -> str:
        name = f"{self.set_number} {self.name} ({self.year}).pdf"
        return pathvalidate.sanitize_filename(name)

    def __str__(self) -> str:
        return f"{self.set_number} - {self.name} ({self.year})"
