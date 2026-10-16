# Cost

The project has a hundred dollars of AWS Academy credit and needs to survive
several weeks of development plus a live demo. Every architectural choice in
`architecture.md` had cost as one of its inputs, so this file records what those
choices were worth.

## What the stack costs at rest

Nothing is running between demos. No ECS services, no load balancer, no NAT
Gateway, no EC2 instance, no provisioned database.

| Resource | Idle cost |
|---|---|
| ECS cluster | Free. It is a namespace, not a machine |
| Task definitions | Free |
| Cloud Map namespace | About $0.10 a month |
| S3 buckets | Storage only, under 20 MB total |
| DynamoDB, on demand | Storage only, a few kilobytes |
| Lambda | Free unless invoked |
| API Gateway | Free unless invoked |
| ECR | $0.10 per GB-month, about $0.30 for three images |
| CloudWatch Logs | Free under 5 GB |

Roughly **fifty cents a month** while nobody is using it.

## What a training run costs

Four tasks at 1 vCPU and 2 GB, in us-east-1, at $0.04048 per vCPU-hour and
$0.004445 per GB-hour:

```
per task-hour = 0.04048 + (2 x 0.004445) = 0.04937
four tasks    = 0.1975 per hour
```

A ten-round run takes about four minutes including task startup, so roughly
**1.3 cents per run**. Twenty runs during development is about **26 cents**.

## What the whole project should cost

| Line item | Estimate |
|---|---|
| Fargate, around 20 development and demo runs | $0.30 |
| ECR storage, three images for six weeks | $0.50 |
| S3 and DynamoDB | under $0.20 |
| Lambda and API Gateway | free tier |
| CloudWatch Logs and custom metrics | under $1.00 |
| Data transfer | under $0.50 |
| **Total** | **under $3** |

Record the real figure from Cost Explorer in the report rather than quoting this
table. The estimate is the argument; the invoice is the evidence.

## What the alternatives would have cost

This is the part worth putting in the report, because it is where the design
decisions become quantitative.

| Choice made | Alternative | Alternative's monthly cost |
|---|---|---|
| Fargate one-off tasks | EKS cluster | $73 for the control plane alone, before any node |
| Fargate one-off tasks | Three t3.medium EC2 instances, always on | About $90 |
| Lambda behind API Gateway | ECS service behind an Application Load Balancer | About $16 for the balancer, plus the task |
| Public subnets | Private subnets with a NAT Gateway | About $32, plus $0.045 per GB |
| S3 website | CloudFront distribution | Small, but adds 15 minutes to every deploy |
| On-demand DynamoDB | Provisioned capacity | A few dollars, and pointless at this volume |

Choosing EKS with a NAT Gateway and a load balancer, which is the conventional
production answer, would have cost about **$120 a month**. The credit would have
been gone before the first demo.

## Guard rails

**Set a budget alert on day one.** Billing, then Budgets, then a $10 monthly
budget with an alert at fifty percent. A Learner Lab that runs out of credit locks
you out of your own project, mid-project.

**Check for stragglers at the end of every session:**

```bash
aws ecs list-tasks --cluster fedmed
```

Anything listed is still billing. `./scripts/stop_run.sh` clears it.

**Tag everything.** The Terraform provider applies `Project = fedmed` to every
resource, so Cost Explorer can be filtered to exactly this stack. Group by tag
rather than by service when you screenshot the bill for the report.

**Log retention is seven days.** CloudWatch charges for stored logs indefinitely
otherwise, and nobody reads a demo log from three weeks ago.

**ECR expires untagged images after a day** and keeps only the five most recent
tagged ones. Every `push_images.sh` overwrites `:latest` and orphans the previous
layers, which would otherwise accumulate a gigabyte at a time.

## Where the money would actually go at scale

Worth a paragraph in the report, because the answer changes. At three hospitals
and 5,000 images, compute is free in practice and the bill is noise. At fifty
hospitals with full-resolution DICOM studies, the picture inverts: training tasks
need more memory and probably GPUs, per-round communication grows with model size
rather than dataset size, and the dominant cost becomes cross-region data
transfer between hospitals and the aggregator. That last one is an argument for
placing the aggregator in the region where most participants are, and for
compressing or quantising updates, neither of which matters at this scale.
