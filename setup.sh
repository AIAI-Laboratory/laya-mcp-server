#!/usr/bin/env bash
set -euo pipefail
cd -- "$(dirname -- "${BASH_SOURCE[0]}")"
if [[ $EUID -eq 0 ]]; then echo 'Run ./setup.sh as your normal user, not sudo ./setup.sh.' >&2; exit 1; fi
register_only=0
reset=0
args=()
while [[ $# -gt 0 ]]; do
  case "$1" in
    --reset) reset=1; shift ;;
    --register-only) register_only=1; shift ;;
    --dry-run) register_only=1; args+=("--dry-run"); shift ;;
    --targets) [[ $# -ge 2 ]] || { echo '--targets requires a value' >&2; exit 2; }; args+=("--targets" "$2"); shift 2 ;;
    -h|--help) echo 'Usage: ./setup.sh [--reset | --register-only] [--targets auto|all|codex,claude,opencode] [--dry-run]'; exit 0 ;;
    *) echo "Unknown option: $1" >&2; exit 2 ;;
  esac
done
if [[ $reset == 1 && $register_only == 1 ]]; then echo "--reset cannot be combined with --register-only/--dry-run" >&2; exit 2; fi
command -v uv >/dev/null || { echo 'Install uv first: https://docs.astral.sh/uv/getting-started/installation/' >&2; exit 1; }
register_clients() {
  export UV_CACHE_DIR="$PWD/data/setup-cache"
  export UV_PYTHON_INSTALL_DIR="$PWD/data/setup-python"
  uv run --no-project --with tomlkit==0.15.1 --with json5==0.15.0 python scripts/register_global.py "${args[@]}"
}
if [[ $register_only == 1 ]]; then register_clients; exit 0; fi
[[ -f .env ]] || cp .env.example .env
sudo -v
sudo systemctl enable --now docker
if [[ $reset == 1 ]]; then python3 scripts/reset_local.py; fi
mkdir -p data/models reports
export LOCAL_UID="$(id -u)" LOCAL_GID="$(id -g)" LAYA_VERSION="$(cat VERSION)"
compose() { sudo --preserve-env=LOCAL_UID,LOCAL_GID,LAYA_VERSION docker compose --env-file .env "$@"; }
compose config --quiet
# Build before disturbing an older running deployment.
if [[ $reset == 1 ]]; then compose build --no-cache; else compose build; fi
legacy=laya-local-cpu
migrate=0
if sudo docker inspect "$legacy" > /dev/null 2>&1; then
  sudo docker inspect "$legacy" | python3 scripts/check_legacy_container.py "$PWD/data"
  # Restore the predecessor bind path temporarily so rollback can restart it.
  python3 - <<'COMPAT'
from pathlib import Path
root = Path.cwd().resolve()
old = root.parent / "laya-local"
if not old.exists() and not old.is_symlink():
    old.symlink_to(root, target_is_directory=True)
COMPAT
  migrate=1
  sudo docker update --restart=no "$legacy" >/dev/null
  sudo docker stop "$legacy" >/dev/null
fi
if ! compose up -d --wait --wait-timeout 900; then
  if [[ $migrate == 1 ]]; then
    compose stop || true
    sudo docker update --restart=always "$legacy" >/dev/null
    sudo docker start "$legacy" >/dev/null
  fi
  exit 1
fi
if ! compose exec -T laya python /app/scripts/verify_mcp.py | tee reports/mcp-verification.json; then
  if [[ $migrate == 1 ]]; then
    compose stop || true
    sudo docker update --restart=always "$legacy" >/dev/null
    sudo docker start "$legacy" >/dev/null
  fi
  exit 1
fi
if [[ $migrate == 1 ]]; then
  sudo docker rm "$legacy" >/dev/null
  python3 - <<'CLEANUP'
from pathlib import Path
root = Path.cwd().resolve()
legacy_link = root.parent / "laya-local"
if legacy_link.is_symlink() and legacy_link.resolve() == root:
    legacy_link.unlink()
CLEANUP
fi
# Restart only this service, then verify the same HTTP/MCP paths again.
compose restart laya
compose up -d --wait --wait-timeout 900
compose exec -T laya python /app/scripts/verify_mcp.py | tee reports/restart-verification.json
# The new image logs to stdout only; remove only the old application's log files after success.
python3 - <<'LOG_CLEANUP'
from pathlib import Path
folder=Path("data/logs")
if folder.is_dir() and not folder.is_symlink():
    for file in folder.glob("requests.jsonl*"):
        if file.is_file() and not file.is_symlink(): file.unlink()
    if not any(folder.iterdir()): folder.rmdir()
LOG_CLEANUP
sudo docker inspect --format '{{json .HostConfig.RestartPolicy}}' "$(compose ps -q laya)" | tee reports/restart-policy.json
compose exec -T laya cat /app/build-packages.txt > reports/build-packages.txt
register_clients
set -a; source .env; set +a
echo "Ready: Swagger http://127.0.0.1:$LAYA_PORT/docs | MCP http://127.0.0.1:$LAYA_PORT/mcp"
