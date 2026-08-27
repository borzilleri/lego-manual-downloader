from dataclasses import dataclass

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

    @property
    def file_name(self) -> str:
        return pathvalidate.sanitize_filename(f"{self.number}-{self.variant} {self.name} ({self.year}).pdf")
