import os
import structlog
from pathlib import Path

logger = structlog.get_logger()


def apply_identity_lane(lane: str):
    """
    Applies the SSH/Git environment variables for a given identity lane (ADR-002, 3.1).
    Mutates os.environ for the duration of the process.
    """
    # Base paths
    config_dir = Path.home() / ".config" / "dev-space"

    if lane == "agent":
        agent_gh = config_dir / "agent-gh"
        agent_gh.mkdir(parents=True, exist_ok=True)

        # Agent identity context
        os.environ["GH_CONFIG_DIR"] = str(agent_gh)
        os.environ["GIT_AUTHOR_NAME"] = "Agent Dev-Space"
        os.environ["GIT_AUTHOR_EMAIL"] = "agent@dev-space.local"
        os.environ["GIT_COMMITTER_NAME"] = "Agent Dev-Space"
        os.environ["GIT_COMMITTER_EMAIL"] = "agent@dev-space.local"

        # In a real environment, we would point this to an agent-specific SSH key
        # os.environ["GIT_SSH_COMMAND"] = "ssh -i ~/.ssh/id_rsa_agent -o IdentitiesOnly=yes"
        logger.debug("Applied 'agent' identity lane.")

    elif lane == "human":
        # Keep host defaults or explicitly define human config directory if needed
        # We assume the default ~/.config/gh is the human lane.
        logger.debug("Applied 'human' identity lane.")

    else:
        logger.warning(f"Unknown lane '{lane}', falling back to default environment.")
