# Architecture

## The problem

Three hospitals each hold chest X-rays. Any one of them has too few images to
train a good pneumonia classifier alone, and none of them may hand its images to
the others or to a central server. The platform's job is to produce one model
that has learned from all three datasets without any image ever leaving the site
that owns it.

## The shape of the system

```
                    ┌───────────────────── AWS us-east-1 ─────────────────────┐
                    │                                                          │
 Hospital A ──┐     │  ECS Fargate cluster "fedmed"                            │
 own bucket   │     │                                                          │
 own task     ├─────┼─▶ ┌────────────────┐                                     │
              │ TLS │   │  fl-server     │──── checkpoint per round ──▶ S3     │
 Hospital B ──┤ gRPC│   │  FedAvg        │──── round metrics ─────────▶ DynamoDB│
              │     │   │  + clip/noise  │──── logs and metrics ──────▶ CloudWatch
 Hospital C ──┘     │   └────────────────┘                                     │
                    │        ▲ registered in Cloud Map as                      │
                    │          fl-server.fedmed.local                          │
                    │                                                          │
                    │  API Gateway ─▶ Lambda "inference-api" ─▶ reads S3, DynamoDB
                    │        GET /health  GET /model  GET /rounds  POST /predict│
                    │                                                          │
                    │  S3 static website ─▶ React dashboard                     │
                    └──────────────────────────────────────────────────────────┘
```

## Components

| Component | Runs on | Responsibility |
|---|---|---|
| Hospital node | Fargate task, 1 vCPU / 2 GB | Reads one shard from its own bucket, trains locally, returns weights and scalar metrics |
| Aggregation server | Fargate task, 1 vCPU / 2 GB | FedAvg across the three updates, applies clipping and noise, evaluates on a held-out test set, writes checkpoints and metrics |
| Inference API | Lambda container image behind an HTTP API | Serves the current global model and the round history |
| Dashboard | S3 static website | Operator view: convergence, per-site distributions, privacy budget, live prediction |
| Storage | 5 S3 buckets, 2 DynamoDB tables | Three private data buckets, one versioned model bucket, one website bucket; round history and prediction audit trail |
| Secrets | SSM Parameter Store | The self-signed CA, aggregator certificate and private key |

## How one training run works

1. `start_run.sh` launches the aggregator as a one-off Fargate task.
2. It waits for the task to reach RUNNING, reads its private IP from the task's
   network interface, and registers that IP in Cloud Map under
   `fl-server.fedmed.local`.
3. It launches three hospital tasks, each with a different `HOSPITAL_ID` and
   `DATA_BUCKET`, pointing at that DNS name.
4. Each hospital downloads its own shard into task-local ephemeral storage,
   holds back fifteen percent for validation, and connects over TLS.
5. For each of ten rounds: the server sends the current global weights, each
   hospital trains one local epoch, the server clips each update to a fixed L2
   norm, averages them weighted by sample count, adds Gaussian noise, evaluates
   the result on its own test set, and writes a checkpoint and a metrics row.
6. After the last round every task exits. Nothing keeps running, and nothing
   keeps billing.

## Decisions worth defending

**Fargate rather than EKS.** An EKS control plane costs roughly seventy-three
dollars a month before a single workload runs, which would consume most of a
hundred-dollar course credit while idle. Fargate bills per task-second, so the
entire four-task training run costs about twenty cents an hour and nothing at
rest. The orchestration concepts carry over: a task definition is a pod spec, the
ECS scheduler places tasks, and the awsvpc network mode gives every task its own
elastic network interface exactly as a pod gets its own address.

**One-off tasks rather than ECS services.** A service maintains a desired count,
so it would restart the aggregator forever after the run finished and bill
overnight. Training is a job, not a server, so it is launched as a job.

**Lambda rather than a load-balanced container for inference.** The API is idle
except during a demo. An Application Load Balancer costs about sixteen dollars a
month whether or not it serves a request. Lambda scales to zero and stays inside
the free tier at demo volumes. The cost is a cold start of several seconds while
the PyTorch runtime unpacks, which is why the function is given two gigabytes of
memory: Lambda scales CPU with memory, so the extra memory buys a faster start.

**Public subnets rather than a NAT Gateway.** Tasks need outbound access to ECR,
S3 and CloudWatch. A NAT Gateway is about thirty-two dollars a month plus data
charges. Public subnets with public IPs cost nothing, and the security groups
close inbound access: the aggregator accepts port 8080 only from the hospital
security group, and the hospitals accept nothing at all.

**Cloud Map rather than passing an IP.** TLS validation needs a stable hostname
and a Fargate task's IP changes on every run. A one-off task does not register
itself the way a service does, so the launch script registers the IP manually
against a Cloud Map service. Set `enable_cloud_map = false` if the lab account
blocks the service; the hospitals then dial the IP directly and TLS has to be
turned off, which the launch script refuses to do silently.

**GroupNorm rather than BatchNorm.** BatchNorm carries running mean and variance
buffers computed on each hospital's own class distribution. Averaging those
across sites whose pneumonia rates range from fifteen to ninety-six percent
degrades the model, and the integer `num_batches_tracked` buffer does not survive
a weighted average cleanly. GroupNorm is stateless, so the parameter list Flower
exchanges contains only learnable weights. A test asserts this.

**The test set ships inside the aggregator's image.** It is not private hospital
data, and baking it in means the aggregator needs no read permission on any data
bucket at all. That is what makes the isolation claim structural rather than a
matter of trusting the code.

## Scaling to a fourth hospital

Add an id to `hospital_ids` in Terraform, which creates the bucket, then add it
to the loop in `start_run.sh`. There is no new task definition, no new image and
no code change, because a hospital is distinguished only by two environment
variables. The aggregator's `NUM_HOSPITALS` has to match, since FedAvg waits for
every participant before closing a round.

## What is deliberately not here

- **Secure aggregation.** The server sees each hospital's individual update. A
  protocol such as SecAgg+ would let it see only the sum. Flower supports this;
  it was left out to keep the moving parts inspectable, and it is the first thing
  a follow-up should add.
- **Client-level differential privacy at the hospital.** Noise is added centrally,
  which protects against someone reading the published checkpoints but not
  against the aggregator itself.
- **Real DICOM ingestion.** The dataset arrives as de-identified NumPy arrays.
  A production system would need a de-identification stage before any pixel data
  was written anywhere.

See [threat-model.md](threat-model.md) for what each of these gaps actually means.
