#!/usr/bin/env python3
"""Probe MCP, then atomically merge user-global configuration with rollback."""
import argparse
import datetime
import json
import os
from pathlib import Path
import shutil
import sys
import tempfile
import urllib.request
import tomlkit
import json5

ROOT = Path(__file__).resolve().parents[1]
TARGETS = ("codex", "claude", "opencode")

def endpoint():
    values = {}
    settings = ROOT / ".env" if (ROOT / ".env").exists() else ROOT / ".env.example"
    for line in settings.read_text().splitlines():
        if "=" in line and not line.lstrip().startswith("#"):
            k,v=line.split("=",1); values[k.strip()]=v.strip()
    port=int(values.get("LAYA_PORT", "30765"))
    if not 1024<=port<=65535: raise ValueError("Invalid LAYA_PORT")
    return f"http://127.0.0.1:{port}/mcp"

def probe(url):
    headers={"Content-Type":"application/json","Accept":"application/json, text/event-stream",
             "X-Laya-Caller":"global-installer","X-Laya-Task":"global-setup-check"}
    def rpc(method, params=None, request_id=None):
        body={"jsonrpc":"2.0","method":method}
        if params is not None:body["params"]=params
        if request_id is not None:body["id"]=request_id
        with urllib.request.urlopen(urllib.request.Request(url,data=json.dumps(body).encode(),headers=headers),timeout=45) as response:
            content=response.read()
            sid=response.headers.get("Mcp-Session-Id")
            if sid: headers["Mcp-Session-Id"]=sid
        if not content:return {}
        if content.lstrip().startswith(b"data:") or b"\ndata:" in content:
            messages=[json.loads(line[5:].strip()) for line in content.decode().splitlines() if line.startswith("data:")]
            data=next(x for x in messages if x.get("id")==request_id)
        else:data=json.loads(content)
        if "error" in data:raise RuntimeError(f"MCP {method} returned an error")
        return data.get("result",{})
    init=rpc("initialize",{"protocolVersion":"2025-03-26","capabilities":{},"clientInfo":{"name":"laya-global-installer","version":"1.0"}},1)
    headers["MCP-Protocol-Version"]=init["protocolVersion"]
    rpc("notifications/initialized")
    names={x["name"] for x in rpc("tools/list",{},2)["tools"]}
    if not {"laya_status","laya_classify"}<=names:raise RuntimeError("Required MCP tools missing")
    status=rpc("tools/call",{"name":"laya_status","arguments":{"caller":"global-installer","task":"setup-health"}},3)
    if status.get("isError"):raise RuntimeError("MCP health failed")
    result=rpc("tools/call",{"name":"laya_classify","arguments":{"text":"I was charged twice. Please refund the duplicate payment.","labels":{"billing":"Payment, invoice, refund","account":"Login and passwords"},"caller":"global-installer","task":"setup-inference"}},4)
    if result.get("isError"):raise RuntimeError("MCP inference failed")
    payload=result.get("structuredContent")
    if payload is None:payload=json.loads(next(x["text"] for x in result["content"] if x.get("type")=="text"))
    if payload.get("answers",{}).get("category",{}).get("choice")!="billing":raise RuntimeError("MCP sample answer failed")
    return {"url":url,"tools":sorted(names),"inference":"billing","protocol":init["protocolVersion"]}

def config_paths(home):
    # Honor global config roots; avoid accidentally treating a project override as global.
    if os.environ.get("OPENCODE_CONFIG"):
        raise RuntimeError("OPENCODE_CONFIG overrides a specific file; unset it for global setup")
    if os.environ.get("OPENCODE_CONFIG_DIR"):
        raise RuntimeError("OPENCODE_CONFIG_DIR is set; unset it for standard global setup")
    codex=Path(os.environ.get("CODEX_HOME",str(home/".codex"))) / "config.toml"
    claude_root=os.environ.get("CLAUDE_CONFIG_DIR")
    claude=Path(claude_root)/".claude.json" if claude_root else home/".claude.json"
    oc=Path(os.environ.get("XDG_CONFIG_HOME",str(home/".config")))/"opencode"
    opencode=oc/"opencode.jsonc" if (oc/"opencode.jsonc").exists() else oc/"opencode.json"
    if (oc/"opencode.jsonc").exists() and (oc/"opencode.json").exists():
        raise RuntimeError("Both OpenCode JSON and JSONC exist; consolidate before automatic setup")
    return {"codex":codex,"claude":claude,"opencode":opencode}

def plan_configs(paths, targets, url):
    changes=[]
    for name in targets:
        path=paths[name]
        before=path.read_text() if path.exists() else ""
        if name=="codex":
            doc=tomlkit.parse(before)
            entry={"url":url,"enabled":True,"startup_timeout_sec":30,"tool_timeout_sec":60,
                   "http_headers":{"X-Laya-Caller":"codex"}}
            servers=doc.setdefault("mcp_servers",{})
            if dict(servers.get("laya",{}))==entry:continue
            servers["laya"]=entry
            after=tomlkit.dumps(doc)
            tomlkit.parse(after)
        else:
            doc=json5.loads(before) if before else {}
            if not isinstance(doc,dict):raise ValueError(f"Expected object: {path}")
            key="mcpServers" if name=="claude" else "mcp"
            entry=({"type":"http","url":url,"headers":{"X-Laya-Caller":"claude-code"}} if name=="claude" else
                   {"type":"remote","url":url,"enabled":True,"oauth":False,"headers":{"X-Laya-Caller":"opencode"}})
            servers=doc.setdefault(key,{})
            if servers.get("laya")==entry:continue
            servers["laya"]=entry
            after=json.dumps(doc,ensure_ascii=False,indent=2)+"\n"
        changes.append((path,before if path.exists() else None,after))
    return changes

def atomic_write(path, text):
    path.parent.mkdir(parents=True,exist_ok=True)
    mode=path.stat().st_mode & 0o777 if path.exists() else 0o600
    fd,tmp=tempfile.mkstemp(dir=path.parent,prefix=".laya-")
    try:
        os.fchmod(fd,mode)
        with os.fdopen(fd,"w") as out:out.write(text)
        os.replace(tmp,path)
    finally:
        if os.path.exists(tmp):os.unlink(tmp)

def install(targets, dry_run=False):
    home=Path.home();paths=config_paths(home);url=endpoint()
    selected=list(TARGETS) if targets=="all" else ([n for n in TARGETS if shutil.which(n) or paths[n].exists()] if targets=="auto" else targets.split(","))
    if any(n not in TARGETS for n in selected):raise ValueError("Targets: auto, all, or codex,claude,opencode")
    checks=probe(url)
    changes=plan_configs(paths,selected,url)
    source=ROOT/"skills/laya-mcp-server"
    global_skill=home/".agents/skills/laya-mcp-server"
    links=[(global_skill,source)]
    if "claude" in selected:
        claude_skills=Path(os.environ.get("CLAUDE_CONFIG_DIR",str(home/".claude")))/"skills/laya-mcp-server"
        links.append((claude_skills,global_skill))
    pending=[]
    for link,target in links:
        if link.is_symlink() and link.resolve()==target.resolve():continue
        if link.exists() or link.is_symlink():raise RuntimeError(f"Skill path already belongs to another installation: {link}")
        pending.append((link,target))
    report={"targets":selected,"mcp":checks,"configs":{n:str(paths[n]) for n in selected},"changed":[str(x[0]) for x in changes],"skill":str(global_skill),"dry_run":dry_run}
    if dry_run:return report
    stamp=datetime.datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    backup=ROOT/"backups"/stamp
    if changes:
        backup.mkdir(parents=True,mode=0o700)
        os.chmod(backup.parent,0o700)
        manifest=[]
        for i,(path,before,after) in enumerate(changes):
            manifest.append({"path":str(path),"backup":f"{i}.bak" if before is not None else None})
            if before is not None:
                saved=backup/f"{i}.bak";saved.write_text(before);saved.chmod(0o600)
        (backup/"manifest.json").write_text(json.dumps(manifest,indent=2))
    written=[];created=[]
    try:
        for path,before,after in changes:atomic_write(path,after);written.append((path,before))
        for link,target in pending:
            link.parent.mkdir(parents=True,exist_ok=True);link.symlink_to(target,target_is_directory=True);created.append(link)
        # Read-back: no duplicate entry, correct endpoint, other entries were preserved by merge.
        assert not plan_configs(paths,selected,url), "Config read-back mismatch"
    except BaseException:
        for link in reversed(created):link.unlink()
        for path,before in reversed(written):
            if before is None:path.unlink()
            else:atomic_write(path,before)
        raise
    report["backup"]=str(backup) if changes else None
    (ROOT/"reports").mkdir(exist_ok=True)
    (ROOT/"reports/global-install.json").write_text(json.dumps(report,ensure_ascii=False,indent=2))
    return report

def remove_local_registration():
    home=Path.home();url=endpoint();removed=[]
    for name,path in config_paths(home).items():
        if not path.exists():continue
        before=path.read_text()
        doc=tomlkit.parse(before) if name=="codex" else json5.loads(before)
        key={"codex":"mcp_servers","claude":"mcpServers","opencode":"mcp"}[name]
        servers=doc.get(key,{})
        entry=servers.get("laya")
        if entry is None:continue
        if entry.get("url")!=url:raise RuntimeError(f"Refusing to remove unrelated laya endpoint in {path}")
        del servers["laya"]
        atomic_write(path,tomlkit.dumps(doc) if name=="codex" else json.dumps(doc,ensure_ascii=False,indent=2)+"\n")
        removed.append(str(path))
    source=(ROOT/"skills/laya-mcp-server").resolve()
    for base in [home/".claude/skills",home/".agents/skills"]:
        for name in ["laya-mcp-server","laya-local"]:
            link=base/name
            if link.is_symlink() and link.resolve()==source:
                link.unlink();removed.append(str(link))
    return {"removed":removed}

if __name__=="__main__":
    parser=argparse.ArgumentParser();parser.add_argument("--targets",default="auto");parser.add_argument("--dry-run",action="store_true");parser.add_argument("--remove-local",action="store_true")
    args=parser.parse_args()
    if os.geteuid()==0:parser.error("Run as your normal user, not sudo")
    try: print(json.dumps((remove_local_registration() if args.remove_local else install(args.targets,args.dry_run)),ensure_ascii=False,indent=2))
    except Exception as exc:
        print(f"Global setup stopped: {exc}",file=sys.stderr);sys.exit(1)
