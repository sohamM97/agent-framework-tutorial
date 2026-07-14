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
