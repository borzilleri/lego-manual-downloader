import pathvalidate
from dataclasses import dataclass


@dataclass(frozen=True)
class LegoSet:
    number: str
    name: str
    year: str

    @property
    def file_name(self) -> str:
        return pathvalidate.sanitize_filename(
            f"{self.number} {self.name} ({self.year}).pdf"
        )
