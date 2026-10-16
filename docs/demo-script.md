# Demo script

Eight minutes, three speakers. The structure is deliberate: show the problem
before the solution, and show the honest limitation before someone asks about it.

## Twenty minutes before

Do all of this before the room fills. Nothing here should happen live.

```bash
aws sts get-caller-identity          # credentials still valid
terraform -chdir=infra output        # note api_url and website_url
aws ecs list-tasks --cluster fedmed  # must be empty
curl -s $API_URL/health              # warms the Lambda, avoiding a cold start
```

Open four tabs: the dashboard, the ECS console on the cluster, the S3 console on
the models bucket, and a terminal. Leave a previous run's results loaded in the
dashboard so there is something on screen while the live run starts.

---

## 1. The problem (1 minute, speaker A)

Open the dashboard and scroll to the hospital cards.

> Three hospitals. Hospital A has three and a half thousand X-rays, seventy-four
> percent pneumonia. Hospital C has three hundred, fifteen percent pneumonia.
> None of them has enough data to train a good model alone, and none of them is
> allowed to send images to the others.
>
> Everything you see about these hospitals came from metadata. No image in any of
> those three collections will move during this demo.

Point at the class-balance bars. The visual contrast is the argument.

---

## 2. Start the run (1 minute, speaker B)

```bash
./scripts/start_run.sh
```

Switch to the ECS console while it runs.

> One command starts four Fargate tasks: an aggregator and three hospitals. The
> script starts the aggregator first, waits for it, reads its private IP off the
> task's network interface, and publishes it in Cloud Map, because a one-off task
> does not register itself the way a long-running service does. Then the
> hospitals connect by name over TLS.
>
> These are one-off tasks, not services. When the tenth round finishes, all four
> exit and the billing stops. A whole run costs about one and a half cents.

Show the four tasks appearing in the console.

---

## 3. Watch it learn (2 minutes, speaker A)

Back to the dashboard. It polls every five seconds, so the chart grows live.

> The blue line is the global model on a test set that belongs to no hospital.
> The other three are each site's accuracy on its own patients.
>
> Hospital B sits high the whole time. That is not a good model, it is a site
> whose data is ninety-six percent pneumonia, so predicting pneumonia every time
> scores well locally. Hospital C, the small site with mostly normal scans, is
> the hard one. Watch the blue line pull them together.
>
> The dashed line is what one model reaches when it is allowed to pool all three
> datasets. The gap between the dashed line and the blue line is the entire price
> of this architecture. Ten rounds, non-IID split, no privacy noise: about nine
> points. With light noise, about two.

If a round is slow, cut to the CloudWatch log and show a hospital's line:
`local training done: loss ... accuracy ... on 3419 images`.

---

## 4. Prove nothing leaked (1 minute, speaker B)

```bash
aws logs tail /ecs/fedmed --since 5m --filter-pattern hospital
```

> This is everything a hospital node said out loud for an entire run. Image
> counts, loss, accuracy, timings. Weight arrays went over the wire; pixels did
> not. The hospital process has no code path from an image to the network.
>
> And there is no bucket in this account holding more than one hospital's data.
> The aggregator's test set is baked into its own container image, so it needs no
> read permission on a hospital bucket at all.

Show the S3 console: three separate data buckets, and the versioned models bucket
with one object per round.

---

## 5. The limitation, stated first (1 minute, speaker C)

Point at the privacy panel. Do not skip this. It is the strongest part of the
project and it will be the first question if you leave it out.

> We clip every update and add Gaussian noise, and the dashboard reports the
> resulting epsilon. It is in the thousands, which is not a meaningful formal
> guarantee, and we would rather say so than print a green tick.
>
> The reason is structural. Differential privacy in federated learning gets its
> strength from sampling a small fraction of participants each round. With three
> hospitals all participating every round, there is no amplification to collect.
> Getting to a single-digit epsilon needs noise that costs us thirty accuracy
> points, and we measured that.
>
> The fix is fifty hospitals, not a smaller number on this screen.

If you have `artifacts/experiments.md` open, show the noise sweep row by row.

---

## 6. Use the model (1 minute, speaker C)

Drag an X-ray onto the dashboard's upload area.

> This is the federated model, served from Lambda, loaded from the checkpoint the
> run just wrote. The image was decoded in memory, classified, and discarded. The
> audit table holds a SHA-256 of the bytes and the predicted label. That proves a
> query happened without storing anything the image could be rebuilt from.

---

## 7. Shut it down (1 minute, speaker B)

```bash
./scripts/stop_run.sh
aws ecs list-tasks --cluster fedmed
```

> Empty. Nothing is running and nothing is billing.
>
> The alternative architecture, EKS with a NAT Gateway and a load balancer, would
> have cost about a hundred and twenty dollars a month sitting idle. This has cost
> us under three dollars for the entire project, and most of that was container
> registry storage.

Show the Cost Explorer view filtered to `Project = fedmed`.

---

## Questions to expect

**Why not just anonymise and pool the images?** De-identification is not the same
as anonymisation for imaging data. Chest films carry burned-in text, and a face
can be reconstructed from head CT. More practically, hospitals are usually barred
from sharing by contract and jurisdiction regardless of the technique.

**Why is federated accuracy lower?** Two reasons, and we measured them
separately. Averaging models trained on different distributions is lossy, worth
about four points here even with an even split. The uneven split costs another
five.

**What stops the aggregator inspecting one hospital's update?** Nothing in this
build, and that is the largest gap. Secure aggregation, SecAgg+, lets the server
decrypt only the sum. Flower supports it; we left it out to keep the protocol
inspectable.

**Is this Kubernetes?** ECS, not Kubernetes, and for a cost reason we can defend.
An EKS control plane is seventy-three dollars a month before any workload. The
concepts map directly: a task definition is a pod spec, awsvpc gives each task
its own network interface.

**How would you add a fourth hospital?** One id in a Terraform list and one entry
in the launch loop. No new image, no new task definition, no code change.

**Is this a medical device?** No, and the dashboard says so on screen. It is a
teaching demonstration on a public research dataset.
