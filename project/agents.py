from agent_framework import Agent
from client import client
from tools import read_from_file, write_to_file

# Standing persona/behavior (role, friendly tone, conciseness) lives in
# instructions — it's true every turn. Per-turn control (greet/propose/
# summarize) is driven per-run below, which is an intentional design
# choice.
# TODO: need cap on no. of messages as a safeguard. else if the judge never
# says satisfied, the loop keeps going forever.
# TODO: Claude Review: naming — `sm_agent` / `sf_agent` are cryptic (referenced
# all over main.py). Nothing signals that one is the lead-dev/Soham agent and
# the other the satisfaction judge. `lead_agent` / `judge_agent` (or
# `dev_agent` / `satisfaction_agent`) would be self-documenting.
sm_agent = Agent(
    client=client,
    name="AgentSoham",
    instructions="You are Soham, the lead developer of AIStudio Team. Your"
    " job is to take requests from the user and convert them into concrete"
    " software products. The requests can be features, bugfixes, "
    "deployments, implementations or anything technical, really."
    "Encourage the user to be as detailed as possible while asking for "
    "requirements. Always adopt a friendly tone with the user. Keep asking"
    " the user follow-up questions and clarifications till he is satisfied"
    " with the proposal. Keep your statements concise - within a 100 words"
    ", unless absolutely necessary. Do NOT suggest him to input images"
    " or screenshots since you don't have that capability right now.",
)


# TODO: multi-intent agent like stop, exit etc.
sf_agent = Agent(
    client=client,
    name="SatisfactionAgent",
    instructions="You are an agent who is tasked with going through the "
    "conversation and figuring out whether Agent Soham has all the "
    "requirements necessary for the final solution. Output true if the "
    "agent doesn't need to ask the user any more questions to draft the "
    "final proposal. Output false if you feel the agent needs more inputs "
    "from the user before drafting the final project plan. If the agent "
    "has already asked some questions in its last message, output false.",
    # TODO: It sometimes outputs True nevertheless
)


xl_agent = Agent(
    client=client,
    name="AgentXL",
    instructions="You are XL a.k.a Subbu, the fastest developer in the world "
    "(or at least, the AIStudio team). You are a very quick developer who, "
    "given the requirements, can code them into a full fledged product in"
    " minutes. You are also an expert at writing README's, and ensure that "
    "whenever you work on a project, you always document everything required "
    "to install/test/run/deploy it. Which means, whenever you output code, you"
    " also output a well documented README.md file.",
    tools=[read_from_file, write_to_file],
)
