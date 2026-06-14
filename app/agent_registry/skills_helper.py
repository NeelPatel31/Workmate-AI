import yaml
import logging
from pathlib import Path
from typing import Optional

from ..utils.constants import SKILL_DIR, LOCAL_SKILLS_DIR

logger = logging.getLogger(__name__)

SKILL_MANIFEST = "SKILL.md"


def get_skill_path(skill_name: str) -> str:
    """Return the container-side path for a skill."""
    return f"{SKILL_DIR}/{skill_name}"


def _parse_frontmatter(skill_md_path: Path) -> Optional[dict]:
    """Parse YAML frontmatter from a SKILL.md file.

    Expects the file to start with '---', followed by YAML content,
    and closed by another '---'.  Returns the parsed dict or None on failure.
    """
    try:
        text = skill_md_path.read_text(encoding="utf-8")
    except OSError as exc:
        logger.warning("Could not read %s: %s", skill_md_path, exc)
        return None

    text = text.strip()
    if not text.startswith("---"):
        logger.warning("No frontmatter found in %s", skill_md_path)
        return None

    # Find the closing '---'
    end_idx = text.find("---", 3)
    if end_idx == -1:
        logger.warning("Unclosed frontmatter in %s", skill_md_path)
        return None

    yaml_block = text[3:end_idx]
    try:
        data = yaml.safe_load(yaml_block)
    except yaml.YAMLError as exc:
        logger.warning("Invalid YAML in %s: %s", skill_md_path, exc)
        return None

    if not isinstance(data, dict):
        logger.warning("Frontmatter is not a mapping in %s", skill_md_path)
        return None

    return data


def _escape_xml(value: str) -> str:
    """Escape special XML characters in a string."""
    return (
        value
        .replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
        .replace("'", "&apos;")
    )


def _skill_to_xml(frontmatter: dict, container_path: str) -> Optional[str]:
    """Convert a parsed skill frontmatter dict into an XML string.

    Required fields: name, description.
    Path is always included (derived from SKILL_DIR + skill name).
    Optional fields are included when present: license, compatibility,
    metadata (key-value pairs), allowed-tools.
    """
    name = frontmatter.get("name")
    description = frontmatter.get("description")

    if not name or not description:
        logger.warning(
            "Skill missing required field(s) – name: %s, description: %s",
            name,
            bool(description),
        )
        return None

    lines = [
        "<skill>",
        f"  <name>{_escape_xml(str(name))}</name>",
        f"  <description>{_escape_xml(str(description))}</description>",
        f"  <path>{_escape_xml(container_path)}</path>",
    ]

    # Optional fields
    license_val = frontmatter.get("license")
    if license_val:
        lines.append(f"  <license>{_escape_xml(str(license_val))}</license>")

    compatibility = frontmatter.get("compatibility")
    if compatibility:
        lines.append(
            f"  <compatibility>{_escape_xml(str(compatibility))}</compatibility>"
        )

    allowed_tools = frontmatter.get("allowed-tools")
    if allowed_tools:
        lines.append(
            f"  <allowed-tools>{_escape_xml(str(allowed_tools))}</allowed-tools>"
        )

    metadata = frontmatter.get("metadata")
    if isinstance(metadata, dict) and metadata:
        lines.append("  <metadata>")
        for key, value in metadata.items():
            safe_key = _escape_xml(str(key))
            safe_val = _escape_xml(str(value))
            lines.append(f"    <{safe_key}>{safe_val}</{safe_key}>")
        lines.append("  </metadata>")

    lines.append("</skill>")
    return "\n".join(lines)


def get_skills_xml() -> str:
    """Scan the local skills directory and return all skills as an XML string.

    Each skill directory is expected to contain a SKILL.md with YAML
    frontmatter (per the Agent Skills specification).  The returned string
    is a newline-joined concatenation of individual ``<skill>`` blocks.

    Returns an empty string if no valid skills are found.
    """
    skills_dir = Path(LOCAL_SKILLS_DIR)

    if not skills_dir.is_dir():
        logger.warning("Skills directory does not exist: %s", skills_dir)
        return ""

    xml_blocks: list[str] = []

    for child in sorted(skills_dir.iterdir()):
        if not child.is_dir():
            continue

        manifest = child / SKILL_MANIFEST
        if not manifest.is_file():
            logger.debug("No %s in %s – skipping", SKILL_MANIFEST, child.name)
            continue

        frontmatter = _parse_frontmatter(manifest)
        if frontmatter is None:
            continue

        container_path = get_skill_path(child.name)
        xml = _skill_to_xml(frontmatter, container_path)
        if xml is not None:
            xml_blocks.append(xml)

    return "\n".join(xml_blocks)

CURRENTLY_AVAILABE_SKILLS = get_skills_xml()