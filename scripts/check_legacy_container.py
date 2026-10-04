"""Fail closed before migrating a container from the original local deployment."""
import json
import sys
from pathlib import Path

container=json.load(sys.stdin)[0]
if container.get("Config",{}).get("Labels",{}).get("com.docker.compose.project") != "laya-local":
    raise SystemExit("Refusing migration: legacy container does not belong to laya-local Compose project")
mounts=container.get("Mounts",[])
expected = Path(sys.argv[1]).resolve()
legacy_source = expected.parent.parent / "laya-local" / "data"
# The old Desktop alias may already have been removed. Accept only the known
# predecessor path beside this checkout, with its verified Compose ownership.
def matching_source(source):
    path = Path(source)
    return path.resolve() == expected or (path == legacy_source and not legacy_source.parent.exists())
if not any(m.get("Destination")=="/data" and matching_source(m.get("Source", "")) for m in mounts):
    raise SystemExit("Refusing migration: legacy data mount does not match this project")
print("Verified legacy project and data mount",file=sys.stderr)
