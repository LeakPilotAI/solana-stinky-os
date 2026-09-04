# Operator-box soak (not proven in CI)

Genesis must stay alive for hours. This procedure is the proof. Do not claim a
duration unless this box actually ran it.

## After pull

```powershell
cd D:\Work\Project-Genesis
git fetch origin
git reset --hard origin/main
git checkout -f -B main origin/main
powershell -NoProfile -ExecutionPolicy Bypass -File .\stop-stinky.ps1
powershell -NoProfile -ExecutionPolicy Bypass -File .\APPLY-launcher.ps1
```

Double-click **Genesis**. Do not start ATLAS on Genesis ports.

## Watch (every 15–30 min)

```powershell
cd D:\Work\Project-Genesis
curl.exe -s -w " api %{http_code} %{time_total}`n" -m 5 http://127.0.0.1:8010/health
curl.exe -s -w " el  %{http_code} %{time_total}`n" -m 5 http://127.0.0.1:8002/health
curl.exe -s -o NUL -w " cc  %{http_code} %{time_total}`n" -m 8 http://127.0.0.1:8010/v1/command-center
docker inspect stinky-redis --format "redis status={{.State.Status}} restarts={{.RestartCount}} oom={{.State.OOMKilled}}"
docker exec stinky-redis redis-cli INFO persistence | findstr /i "loading rdb"
docker exec stinky-redis redis-cli INFO memory | findstr /i "used_memory_human maxmemory"
docker exec stinky-redis redis-cli XLEN stinky.events
Get-Content logs\api.log -Tail 20
Get-Content logs\entities.log -Tail 10
```

Healthy: api time_total well under 1s, redis restarts stay 0, XLEN around 20k or less, no `LOADING`, no `Error 22`, no `non-checked-in connection`.

## Durations

Record start time. Check at 30m, 1h, 4h, 8h, 12h, 24h.

A red TopBar is a symptom. Paste `/health` ms and redis restart count first.

## Stop

Double-click **Stop Genesis**. Volumes stay. ATLAS is not targeted.
