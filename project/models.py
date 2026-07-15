from typing import Literal

from pydantic import BaseModel


class RequirementsReady(BaseModel):
    # TODO: Claude Review: consider adding a `reasoning: str` field before
    # `ready` to give the model room to think — usually improves accuracy.
    ready: bool


class ProjectDetails(BaseModel):
    project_name: str
    proposal: str


class CodeReviewOutput(BaseModel):
    success: bool = True
    lgtm: bool
    comments: str
    review_path: str


# The payload we hand the driver whenever we need a human turn. It carries only
# `kind` so the ONE response_handler below can tell a requirements answer apart
# from a yes/no confirmation.
# Claude: the prompt TEXT used to live here (the driver printed it). It doesn't
# anymore — Soham's words are now streamed live as workflow output (see
# stream_soham), so the driver just needs to know a human turn is pending and how
# to route the answer.
# SOHAM: This can be either dataclass or pydantic model.
class UserPrompt(BaseModel):
    kind: Literal["requirements", "confirm"]


class ProjectRequirements(BaseModel):
    project_idea: str
    additional_remarks: str = ""
