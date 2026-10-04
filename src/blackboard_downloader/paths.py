"""Safe, stable export paths and atomic JSON persistence."""

import hashlib
import json
import re
import tempfile
from html import unescape
from pathlib import Path

from .errors import BlackboardError


def safe_name(value: str, *, max_bytes: int = 180) -> str:
    name = re.sub(r'[<>:"/\\|?*\x00-\x1f\x7f]', "_", unescape(value))
    name = name.strip().rstrip(". ") or "untitled"
    if re.fullmatch(r"(?i)(CON|PRN|AUX|NUL|COM[1-9]|LPT[1-9])(\..*)?", name):
        name = "_" + name
    while len(name.encode("utf-8")) > max_bytes:
        name = name[:-1]
    return name


class PathRegistry:
    """Remember identities so homonyms and subset reruns do not overwrite files."""

    def __init__(self, output: Path):
        self.output = output.resolve()
        self.output.mkdir(parents=True, exist_ok=True)
        self.registry = self.output / ".blackboard-paths.json"
        self.check(self.registry)
        try:
            self.paths = (
                json.loads(self.registry.read_text(encoding="utf-8"))
                if self.registry.exists()
                else {}
            )
        except (ValueError, UnicodeError):
            raise BlackboardError(
                "The export path registry is not valid JSON."
            ) from None
        if not isinstance(self.paths, dict):
            raise BlackboardError("The export path registry must contain an object.")
        for parent, slots in self.paths.items():
            if not isinstance(parent, str) or not isinstance(slots, dict):
                raise BlackboardError("Invalid export path registry entry.")
            self.check(self.output / parent)
            for name, owner in slots.items():
                if (
                    not isinstance(name, str)
                    or not isinstance(owner, str)
                    or safe_name(name) != name
                ):
                    raise BlackboardError(
                        "Invalid filename in the export path registry."
                    )

        self._owners = {
            parent: {owner: name for name, owner in slots.items()}
            for parent, slots in self.paths.items()
        }
        self._occupied: dict[str, set[str]] = {}

    def check(self, path: Path) -> None:
        if not path.resolve().is_relative_to(self.output):
            raise BlackboardError("An export path escapes the output directory.")
        current = path
        while current != self.output:
            if current.is_symlink() or (
                hasattr(current, "is_junction") and current.is_junction()
            ):
                raise BlackboardError("An export path contains a symbolic link.")
            if current == current.parent:
                raise BlackboardError("An export path escapes the output directory.")
            current = current.parent

    def known(self, parent: Path, identity: str) -> Path | None:
        self.check(parent)
        owner = hashlib.sha256(identity.encode()).hexdigest()
        key = parent.relative_to(self.output).as_posix()
        name = self._owners.get(key, {}).get(owner)
        if name is None:
            return None
        path = parent / name
        self.check(path)
        return path

    def allocate(self, parent: Path, title: str, identity: str) -> Path:
        self.check(parent)
        existing = self.known(parent, identity)
        if existing is not None:
            return existing
        key = parent.relative_to(self.output).as_posix()
        slots = self.paths.setdefault(key, {})
        owner = hashlib.sha256(identity.encode()).hexdigest()
        name = safe_name(title)
        if key not in self._occupied:
            occupied = {saved.casefold() for saved in slots}
            if parent.exists():
                occupied.update(child.name.casefold() for child in parent.iterdir())
            if parent == self.output:
                occupied.update({"report.json", ".blackboard-paths.json", "courses"})
            self._occupied[key] = occupied
        occupied = self._occupied[key]
        counter = 0
        original = Path(name)
        while name.casefold() in occupied:
            counter += 1
            suffix = f" [{owner[:10]}{f'-{counter}' if counter > 1 else ''}]"
            extension = (
                safe_name(original.suffix, max_bytes=32) if original.suffix else ""
            )
            name = safe_name(original.stem, max_bytes=120) + suffix + extension
        slots[name] = owner
        self._owners.setdefault(key, {})[owner] = name
        occupied.add(name.casefold())
        path = parent / name
        self.check(path)
        return path

    def write_json(self, path: Path, data: dict) -> None:
        self.check(path)
        path.parent.mkdir(parents=True, exist_ok=True)
        temporary = None
        try:
            with tempfile.NamedTemporaryFile(
                mode="w",
                encoding="utf-8",
                dir=path.parent,
                prefix=".bb-",
                suffix=".part",
                delete=False,
            ) as target:
                temporary = Path(target.name)
                json.dump(data, target, ensure_ascii=False, indent=2)
                target.write("\n")
            temporary.replace(path)
        finally:
            if temporary is not None:
                temporary.unlink(missing_ok=True)

    def save(self) -> None:
        self.write_json(self.registry, self.paths)
