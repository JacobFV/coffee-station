from __future__ import annotations

from dataclasses import dataclass
from importlib import resources
from pathlib import Path


@dataclass(frozen=True)
class Skill:
    name: str
    description: str
    body: str
    path: str

    def index_line(self) -> str:
        return f"- {self.name}: {self.description}"

    def prompt_block(self) -> str:
        return f"## Skill: {self.name}\nDescription: {self.description}\n\n{self.body.strip()}"


class SkillLibrary:
    def __init__(self, root: Path | None = None) -> None:
        self.root = root
        self._skills = self._load()

    def list(self) -> list[Skill]:
        return sorted(self._skills.values(), key=lambda skill: skill.name)

    def get(self, name: str) -> Skill | None:
        return self._skills.get(name)

    def activate_for_text(self, text: str, explicit: list[str] | None = None, limit: int = 3) -> list[Skill]:
        explicit = explicit or []
        selected: list[Skill] = []
        for name in explicit:
            skill = self.get(name)
            if skill and skill not in selected:
                selected.append(skill)
        lowered = text.lower()
        scored: list[tuple[int, Skill]] = []
        for skill in self.list():
            if skill in selected:
                continue
            score = 0
            terms = {skill.name.replace("-", " "), *skill.name.split("-")}
            terms.update(word.strip(".,:;()[]").lower() for word in skill.description.split())
            for term in terms:
                if len(term) >= 4 and term in lowered:
                    score += 1
            if score:
                scored.append((score, skill))
        for _score, skill in sorted(scored, key=lambda item: item[0], reverse=True):
            if len(selected) >= limit:
                break
            selected.append(skill)
        return selected[:limit]

    def _load(self) -> dict[str, Skill]:
        if self.root is not None:
            return self._load_from_path(self.root)
        package_root = resources.files("coffee_station").joinpath("skills")
        skills: dict[str, Skill] = {}
        for child in package_root.iterdir():
            if child.is_dir() and child.joinpath("SKILL.md").is_file():
                skill = self._load_skill_text(child.name, child.joinpath("SKILL.md").read_text())
                skills[skill.name] = skill
        return skills

    def _load_from_path(self, root: Path) -> dict[str, Skill]:
        skills: dict[str, Skill] = {}
        for skill_file in root.glob("*/SKILL.md"):
            skill = self._load_skill_text(skill_file.parent.name, skill_file.read_text())
            skills[skill.name] = skill
        return skills

    @staticmethod
    def _load_skill_text(path_name: str, text: str) -> Skill:
        metadata: dict[str, str] = {}
        body = text
        if text.startswith("---"):
            parts = text.split("---", 2)
            if len(parts) == 3:
                raw_frontmatter = parts[1]
                body = parts[2]
                for line in raw_frontmatter.splitlines():
                    if ":" not in line:
                        continue
                    key, value = line.split(":", 1)
                    metadata[key.strip()] = value.strip().strip('"').strip("'")
        name = metadata.get("name", path_name)
        description = metadata.get("description", "")
        if not name or not description:
            raise ValueError(f"skill {path_name} must define name and description frontmatter")
        return Skill(name=name, description=description, body=body, path=path_name)
