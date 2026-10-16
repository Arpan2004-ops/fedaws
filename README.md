# FedMed

**A federated cloud platform for privacy-preserving medical image intelligence.**

Three hospitals train one pneumonia classifier on their combined experience
without a single X-ray leaving the site that owns it. Built on AWS Fargate,
Lambda and S3, sized to run a full demo for about one and a half cents.

Cloud computing course project. Team of three.

---

## What it does

Each hospital runs its own container with its own private data bucket. A central
aggregator sends out the current model, each site trains on its own patients, and
the aggregator averages the returned weights. Images never appear in a request.
The resulting model is served through a public API and a live dashboard.

| | |
|---|---|
| **Federated learning** | Flower, FedAvg over three sites, ten rounds |
| **Dataset** | PneumoniaMNIST (MedMNIST v2 / Kermany et al., Cell 2018) at 64 pixels, Dirichlet(0.5) split |
| **Privacy** | Data locality by construction, server-side clipping and Gaussian noise, pinned TLS, hash-only inference audit |
| **Compute** | ECS Fargate one-off tasks, no cluster nodes, no idle cost |
| **Serving** | FastAPI on Lambda behind an HTTP API Gateway |
| **Dashboard** | React on an S3 static website |
| **Infrastructure** | Terraform, targeted at an AWS Academy Learner Lab |

## Results

Measured by `scripts/run_experiments.py`, ten rounds or epochs throughout.

| Configuration | Final accuracy | Best round | vs pooled |
|---|---|---|---|
| All data pooled on one server | 89.4% | 89.7% | baseline |
| Federated, even split | 85.4% | 87.9% | -4.0 pts |
| Federated, realistic uneven split | 80.4% | 87.8% | -9.0 pts |
| Federated non-IID, light privacy noise | 87.0% | 87.0% | -2.4 pts |
| Federated non-IID, heavy privacy noise | 67.9% | 67.9% | -21.4 pts |

The four-point gap between pooled and evenly-split federated training is the cost
of the architecture itself. The further five points is the cost of the hospitals
being genuinely different from one another.

**On the privacy budget:** the accountant reports an epsilon in the thousands at
the default noise level, which is not a meaningful formal guarantee. With three
sites all participating in every round there is no subsampling amplification to
collect, and noise strong enough to buy a tight budget costs twenty to thirty
accuracy points. The platform reports its exact parameters and the resulting
number rather than calling itself private. See
[docs/threat-model.md](docs/threat-model.md).

---

## Quick start

```bash
python -m venv .venv
.venv/Scripts/python.exe -m pip install -r requirements-dev.txt   # Windows
# source .venv/bin/activate && pip install -r requirements-dev.txt  # macOS, Linux

python scripts/partition_data.py     # download and split the dataset
python -m pytest                     # 43 tests
python scripts/run_local.py --rounds 10 --dp
```

Ten rounds finish in about thirty seconds on a laptop CPU. Then the same thing in
containers:

```bash
docker compose up --build --abort-on-container-exit --exit-code-from fl-server
```

Without those two flags the command never returns: the inference API is a server
that does not exit, so compose stays attached long after the rounds finish.

Deploying to AWS is [docs/runbook.md](docs/runbook.md), start to finish.

---

## Layout

```
common/fedmed/      shared library: model, data, storage, metrics, privacy accounting
hospital_node/      the client that trains on one site's data and never sends images
fl_server/          the aggregator: FedAvg, differential privacy, checkpointing
inference_api/      FastAPI application, packaged for Lambda
dashboard/          React console, hand-drawn SVG charts, no charting dependency
infra/              Terraform for the whole stack
scripts/            partition, run, sweep, deploy, teardown
tests/              43 tests, including one asserting predictions persist nothing
docs/               architecture, threat model, cost, runbook, demo script
```

## Documentation

| | |
|---|---|
| [PROJECT_OVERVIEW.md](PROJECT_OVERVIEW.md) | **Master manual**: architecture, algorithms, cost, threat model, operations |
| [docs/architecture.md](docs/architecture.md) | How it fits together, and why each choice was made |
| [docs/threat-model.md](docs/threat-model.md) | What is protected, what is not, and why |
| [docs/cost.md](docs/cost.md) | Under three dollars, and what the alternatives would have cost |
| [docs/runbook.md](docs/runbook.md) | Deployment, operation, and what to do when it breaks |
| [docs/demo-script.md](docs/demo-script.md) | The eight-minute presentation |

## Common commands

```bash
make help              # every target
make local             # federation as plain processes
make compose           # federation as containers
make experiments       # the evaluation table and figures
make test

./scripts/push_images.sh    # build and push to ECR
./scripts/upload_data.sh    # one shard per bucket
./scripts/start_run.sh      # one training run on Fargate
./scripts/stop_run.sh       # stop everything. Run this before closing the lab
./scripts/deploy_web.sh     # publish the dashboard
```

---

## Two things to know before running it on AWS

**Stop your tasks before closing the lab.** An AWS Academy session expires after
four hours, but a Fargate task started inside it keeps running and keeps billing
after the console has logged you out. `./scripts/stop_run.sh` is the last command
of every session.

**Apply Terraform in two phases.** The Lambda function needs an image that only
exists once the registries have been created and pushed to.
`terraform apply -target=aws_ecr_repository.this` first, then push, then a full
apply. The runbook walks through it.

---

## Not a medical device

A teaching demonstration built on a public, de-identified research dataset. No
output should inform a clinical decision.
