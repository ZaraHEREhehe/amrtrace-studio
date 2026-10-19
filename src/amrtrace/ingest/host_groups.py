# reads the host grouping file and tells the adapter which group an isolate's raw host value belongs to
import re
from dataclasses import dataclass
from pathlib import Path

import yaml

DEFAULT_HOST_GROUPS_FILE = Path(__file__).with_name("host_groups_v1.yaml")

# bracketed tags such as [NCBITaxon:9031] say nothing about the animal, so they are dropped before matching
_TAG = re.compile(r"\[[^\]]*\]")


class UnknownHost(ValueError):
    pass


class InvalidHostGroups(ValueError):
    pass


def normalise_host(value) -> str:
    if value is None:
        return ""
    return " ".join(_TAG.sub(" ", str(value)).split()).lower()


@dataclass(frozen=True)
class HostGroup:
    name: str
    animal: bool


@dataclass(frozen=True)
class HostGroups:
    version: str
    # normalised raw value to its group
    by_host: dict
    # normalised raw values that name no host
    not_recorded: frozenset

    def group_for(self, raw) -> HostGroup | None:
        key = normalise_host(raw)
        if key in self.not_recorded:
            return None
        group = self.by_host.get(key)
        # a host nobody has placed in a group yet is a gap in the file, so it is reported rather than guessed
        if group is None:
            raise UnknownHost(f"host {raw!r} is not in any group of {self.version}; add it to the host groups file")
        return group


def parse_host_groups(data) -> HostGroups:
    if not isinstance(data, dict) or not isinstance(data.get("groups"), dict):
        raise InvalidHostGroups("the file must be a mapping with host_groups_version, not_recorded and groups")
    version = data.get("host_groups_version")
    if not isinstance(version, str) or not version.strip():
        raise InvalidHostGroups("host_groups_version must be a non-empty string")
    not_recorded = frozenset(normalise_host(v) for v in data.get("not_recorded") or ())
    by_host = {}
    for name, body in data["groups"].items():
        if not isinstance(body, dict) or not isinstance(body.get("animal"), bool) or not body.get("hosts"):
            raise InvalidHostGroups(f"group {name!r} needs animal: true/false and a non-empty hosts list")
        group = HostGroup(str(name), body["animal"])
        for raw in body["hosts"]:
            key = normalise_host(raw)
            # one raw value in two places would make the grouping depend on file order
            if key in by_host or key in not_recorded:
                raise InvalidHostGroups(f"host {raw!r} is listed more than once")
            by_host[key] = group
    return HostGroups(version, by_host, not_recorded)


def load_host_groups(path: Path | str = DEFAULT_HOST_GROUPS_FILE) -> HostGroups:
    with open(path, encoding="utf-8") as handle:
        return parse_host_groups(yaml.safe_load(handle))
