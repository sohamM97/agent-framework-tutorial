from pathlib import Path
from typing import Annotated

from agent_framework import tool
from pydantic import Field

BASE_DIR = Path(__file__).parent


@tool(approval_mode="always_require")
def write_to_file(
    # TODO: is annotation required for the LLM? Or just for us?
    filename: Annotated[str, Field(description="The name of the file to create")],
    contents: Annotated[str, Field(description="The contents to write in the file")],
    filepath: Annotated[
        str, Field(description="The path at which to write the file")
    ] = "outputs",
) -> Path | str:
    try:
        file_loc = BASE_DIR / filepath / filename
        file_loc.parent.mkdir(parents=True, exist_ok=True)
        file_loc.write_text(contents)
        return file_loc
    except Exception as exc:
        return f"Failed to write file: {exc}"


@tool(approval_mode="always_require")
def read_from_file(
    file_location: Annotated[
        str, Field(description="The full location of the file to be read")
    ],
) -> str:
    try:
        return Path(file_location).read_text()
    except Exception as exc:
        return f"Failed to read file: {exc}"
