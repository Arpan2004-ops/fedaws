# Runbook

Everything needed to take this from a fresh clone to a working cloud demo, and
to shut it down again without leaking credit.

Read the two rules at the bottom before your first lab session.

---

## 0. Prerequisites

| Tool | Why | Check |
|---|---|---|
| Python 3.10 or newer | Everything | `python --version` |
| Docker Desktop | Builds the three images | `docker --version` |
| Node 18 or newer | Builds the dashboard | `node --version` |
| AWS CLI v2 | Every cloud script | `aws --version` |
| Terraform 1.5 or newer | The infrastructure | `terraform --version` |
| Git Bash, WSL or a Unix shell | The `.sh` scripts | |

On Windows, run the shell scripts from Git Bash. They already work around the
path rewriting that otherwise corrupts OpenSSL subjects and ECS ARNs.

Two Windows PowerShell habits worth knowing, because both produce errors that
look like the project is broken when it is not:

- `&&` does not chain commands in Windows PowerShell 5.1. `cd dashboard && npm run dev`
  fails with "the token '&&' is not a valid statement separator". Run the two
  commands on separate lines, or use `;` between them.
- `python` on its own may resolve to the Microsoft Store stub rather than this
  project's virtualenv. Call the interpreter directly as `.venv/Scripts/python.exe`.

---

## 1. Local first

Get it working on a laptop before spending a cent. This takes about ten minutes.

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt  # macOS, Linux

python scripts/partition_data.py
python -m pytest
python scripts/run_local.py --rounds 10 --dp
```

You should see three hospitals connect, ten rounds complete in about half a
minute, and accuracy climb into the high eighties. Checkpoints land in
`artifacts/global/` and metrics in `artifacts/metrics.json`.

Then the same thing in containers, which is what actually gets deployed:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from fl-server
```

The two extra flags matter. A plain `docker compose up` stays attached forever,
because the inference API is a web server that never exits, so the terminal looks
frozen long after training has finished. These flags stop the whole stack the
moment the aggregator completes its rounds and hand the prompt back.

To keep the API running afterwards so the dashboard has something to talk to,
start it on its own instead:

```bash
docker compose up -d inference-api
```

and stop it with `docker compose down` when you are done.

And the numbers for the report:

```bash
python scripts/train_centralized.py --epochs 10
python scripts/run_experiments.py
```

That last one takes about ten minutes and writes `artifacts/experiments.md`
plus two figures.

---

## 2. Point the CLI at your lab account

An AWS Academy Learner Lab issues temporary credentials that expire when the
session does. From the lab page, open **AWS Details**, then **AWS CLI**, and copy
the block into `~/.aws/credentials`. It contains an `aws_session_token` as well
as the key pair; all three are needed.

```bash
aws sts get-caller-identity
```

This must succeed before anything below will work. When a script fails with an
expired-token error, come back here rather than debugging the script.

---

## 3. Create the registries first

The inference Lambda cannot be created before its image exists, and the image
cannot be pushed before the registry exists. So the first apply creates only the
registries.

```bash
terraform -chdir=infra init
terraform -chdir=infra apply -target=aws_ecr_repository.this
```

---

## 4. Build and push the images

```bash
./scripts/push_images.sh
```

Three images, roughly a gigabyte each because of PyTorch. The first push takes
ten to fifteen minutes on a normal connection; later pushes only send changed
layers and take under a minute.

The images are built for `linux/amd64` explicitly. On an Apple Silicon laptop the
default build would produce arm64 images, and the Fargate task definition pinned
to X86_64 would fail at startup with an unhelpful exec format error.

---

## 5. Create the rest of the stack

```bash
terraform -chdir=infra apply
```

About two minutes. It creates the ECS cluster, both task definitions, the
security groups, the Cloud Map namespace, five buckets, two DynamoDB tables, the
Lambda function, the API Gateway and the log groups.

```bash
terraform -chdir=infra output
```

Note `api_url` and `website_url`.

### Optionally, turn on TLS

```bash
./scripts/gen_certs.sh
terraform -chdir=infra apply -var tls_enabled=true
```

The certificate is issued for `fl-server.fedmed.local`, so this needs
`enable_cloud_map = true`, which is the default. Terraform refuses the
combination at plan time rather than letting it fail during a demo.

---

## 6. Upload the shards

```bash
./scripts/upload_data.sh
```

One shard per bucket, about seventeen megabytes in total. This is the only moment
in the project where image data moves anywhere.

---

## 7. Run a federation

```bash
./scripts/start_run.sh --follow
```

The script starts the aggregator, waits for it to reach RUNNING, registers its
private IP in Cloud Map, then starts the three hospitals. Ten rounds take three
to four minutes including task startup. Every task exits on its own.

Watch it from another terminal if you did not pass `--follow`:

```bash
aws logs tail /ecs/fedmed --follow --since 5m
aws ecs list-tasks --cluster fedmed --desired-status RUNNING
```

Per-run overrides, useful for showing the privacy trade-off live:

```bash
ROUNDS=20 DP_NOISE=0.5 ./scripts/start_run.sh
```

---

## 8. Publish the dashboard

```bash
./scripts/deploy_web.sh
```

It bakes the API URL into the bundle, copies in the partition manifest and the
centralised baseline, builds, and syncs to the website bucket. Open the
`website_url` output.

---

## 9. Stop everything

```bash
./scripts/stop_run.sh
```

**Run this at the end of every session**, even when the run finished on its own.
It also catches tasks left behind by an earlier session.

After the final demo:

```bash
./scripts/teardown.sh
```

---

## The two rules

**Stop your tasks before you close the lab.** A Learner Lab session expires after
four hours, but a Fargate task started inside it keeps running and keeps billing
after the console has logged you out. `stop_run.sh` is the last command of every
session.

**Never leave an ECS service with a desired count above zero.** This project
creates none, deliberately. If you add one, it will restart the aggregator
forever.

---

## When something goes wrong

**`ExpiredToken` or `InvalidClientTokenId`.** The lab session ended. Repeat
step 2.

**A task stops immediately with `CannotPullContainerError`.** The image is not in
ECR yet, or it was built for the wrong architecture. Re-run
`./scripts/push_images.sh`.

**Hospitals log `server not ready` and retry.** Normal for the first ten to
twenty seconds. If it continues past thirty attempts, the aggregator died. Check
its log stream:

```bash
aws logs tail /ecs/fedmed --since 10m --filter-pattern server
```

**The run hangs with the server waiting for hospitals.** FedAvg waits for all
three. Check whether a hospital task stopped, and read its stop reason:

```bash
aws ecs describe-tasks --cluster fedmed --tasks <task-arn> \
  --query 'tasks[0].{status:lastStatus,reason:stoppedReason}'
```

**`/predict` returns 503.** No checkpoint has been written yet. Run a federation
first, or wait for round one to finish.

**The first `/predict` after an idle period takes ten seconds.** A Lambda cold
start unpacking PyTorch. Call `/health` a moment before the demo to warm it.

**Terraform cannot delete a security group.** A task is still holding a network
interface. Run `stop_run.sh`, wait a minute, and destroy again. `teardown.sh`
already does this.

**`terraform apply` fails creating IAM.** It should not; the stack creates no
roles. If it does, `lab_role_arn` is pointing at something that does not exist.
Check `aws iam get-role --role-name LabRole`.

**Docker Desktop will not start on Windows, with an error naming a `.sock` file.**
The dialog says something like:

```
starting services: initializing Secrets Engine: listening on
unix://C:/Users/<you>/AppData/Local/docker-secrets-engine/engine.sock:
remove ...: The file cannot be accessed by the system.
```

Docker Desktop was killed without shutting down cleanly and left orphaned Unix
socket files behind. Windows cannot open, rename or delete them, so Docker
cannot replace them on the next start, and neither can Explorer or `del`.

Do **not** click "Reset to factory defaults" in that dialog. It deletes every
image and volume, which can be tens of gigabytes.

The fix is to rename the parent directories, which is a metadata operation that
never touches the unreadable files. Quit Docker Desktop, then run this in
PowerShell:

```powershell
Add-Type -TypeDefinition 'using System;using System.Runtime.InteropServices;public class R{[DllImport("kernel32.dll",CharSet=CharSet.Unicode,SetLastError=true)]static extern bool MoveFileExW(string a,string b,int f);public static string Go(string a,string b){return MoveFileExW(a,b,0)?"OK":("error "+Marshal.GetLastWin32Error());}}'
$s = Get-Date -Format 'yyyyMMddHHmmss'
foreach ($d in @("$env:LOCALAPPDATA\Docker
un", "$env:LOCALAPPDATA\docker-secrets-engine")) {
  if (Test-Path -LiteralPath $d) { "$d -> $([R]::Go($d, "$d.orphaned-$s"))" }
}
```

Then start Docker Desktop again. It recreates both directories cleanly. The
renamed copies can be left where they are; they are empty of anything useful and
Windows will not delete them either.

`Move-Item` and `Remove-Item` are not substitutes here. `Move-Item` silently
falls back to copy-then-delete when a rename fails, which recreates the same
broken files at the destination and leaves the originals in place.

**Cloud Map is not permitted in your lab.** Apply with
`-var enable_cloud_map=false -var tls_enabled=false`. Hospitals then dial the
aggregator's IP directly. Say so in the report; it is a real reduction in the
security posture, not a detail.
