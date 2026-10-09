"""Remove only this checkout's Laya deployment before an explicit clean setup."""
import json
import os
from pathlib import Path
import shutil
import subprocess

root=Path(__file__).resolve().parents[1]
def docker(*args,check=True):
    return subprocess.run(["sudo","docker",*args],check=check,text=True,capture_output=True)

# Preflight all candidates before deleting anything.
containers=[]
for name in ["laya-local-cpu","laya-mcp-server","laya-mcp-server-cpu"]:
    result=docker("inspect",name,check=False)
    if result.returncode:continue
    container=json.loads(result.stdout)[0]
    project=container.get("Config",{}).get("Labels",{}).get("com.docker.compose.project")
    if project not in {"laya-local","laya-mcp-server"}:raise SystemExit(f"Refusing unrelated container: {name}")
    sources=[Path(m["Source"]) for m in container.get("Mounts",[]) if m.get("Destination")=="/data"]
    if not any(x.resolve()==(root/"data").resolve() or x==root.parent/"laya-local/data" for x in sources):
        raise SystemExit(f"Refusing container with unrelated data mount: {name}")
    containers.append(name)
for name in containers:
    docker("rm","-f",name);print("Removed container:",name,flush=True)
for name in ["laya-local_default","laya-mcp-server_default"]:
    result=docker("network","inspect",name,check=False)
    if result.returncode:continue
    network=json.loads(result.stdout)[0]
    if network.get("Labels",{}).get("com.docker.compose.project") in {"laya-local","laya-mcp-server"} and not network.get("Containers"):
        docker("network","rm",name);print("Removed network:",name,flush=True)
for image in ["laya-local:0.3.26-cpu","laya-mcp-server:"+(root/"VERSION").read_text().strip()+"-cpu"]:
    if docker("image","inspect",image,check=False).returncode==0:
        result=docker("image","rm",image,check=False)
        print("Removed image:" if result.returncode==0 else "Retained image (still referenced):",image,flush=True)
# No global Docker prune or MCP client configuration changes.
for name in ["data","reports","backups"]:
    folder=root/name
    if folder.is_symlink():raise SystemExit(f"Refusing to delete symlink: {folder}")
    if folder.exists():shutil.rmtree(folder)
old=root.parent/"laya-local"
if old.is_symlink() and old.resolve()==root:old.unlink()
print("Cleaned Laya runtime, model/setup cache, reports and backups. Source/.env and client configuration retained.",flush=True)
