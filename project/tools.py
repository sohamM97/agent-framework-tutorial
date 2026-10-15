from pathlib import Path
from typing import Annotated

from agent_framework import tool
from constants import BASE_DIR, OUTPUTS_DIR
from pydantic import Field


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


@tool(approval_mode="never_require")
def read_from_file(
    file_location: Annotated[
        str, Field(description="The full location of the file to be read")
    ],
) -> str:
    # TODO: keep this in a function
    target = Path(file_location).resolve()
    if not target.is_relative_to(OUTPUTS_DIR.resolve()):
        return f"Refused: {target} is outside the outputs directory"

    try:
        return target.read_text()
    except IsADirectoryError:
        return f"{target} is a directory"
    except Exception as exc:
        return f"Failed to read file: {exc}"


@tool(approval_mode="never_require")
def get_files_under_dir(
    directory_path: Annotated[
        str, Field(description="The full location of the directory to be read")
    ],
) -> str | list[Path]:
    target = Path(directory_path).resolve()
    if not target.is_relative_to(OUTPUTS_DIR.resolve()):
        return f"Refused: {target} is outside the outputs directory"

    return [p for p in target.rglob("*") if p.is_file()]
