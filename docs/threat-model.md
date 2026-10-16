# Threat model

What this platform actually defends against, what it does not, and why. The
useful part of a privacy claim is the boundary, so the gaps are stated as plainly
as the mitigations.

## Assets

| Asset | Why it matters |
|---|---|
| Chest X-rays held by each hospital | The regulated data. Re-identifiable in principle, and the thing the whole design exists to keep in place |
| Weight updates sent each round | Derived from patient data. A gradient can leak information about the examples that produced it |
| The global model | Can memorise training examples and is exposed publicly through the API |
| Prediction requests | An uploaded X-ray belongs to a patient, and the fact that a query was made is itself information |

## Adversaries

**A1. A curious operator with console access.** Can list buckets, read objects,
read logs. In a Learner Lab this is every member of the team.

**A2. A compromised or dishonest hospital node.** Runs the real protocol but
inspects everything that reaches it.

**A3. A network observer** between hospital and aggregator.

**A4. A member of the public** with the API and dashboard URLs.

**A5. An honest-but-curious aggregator.** Follows the protocol and studies the
individual updates it receives.

## What holds

### Images never traverse the network

Structural, not a matter of policy. The hospital process reads its shard into
memory and the only outbound calls it makes are Flower's, which carry a parameter
list and a metrics dictionary built explicitly in `fit` and `evaluate`. There is
no code path from pixels to the wire. Against A2 and A3.

### There is no pooled image store

Each hospital gets its own bucket. No location in the account holds more than one
site's images, so no single breach exposes the combined dataset. The aggregator
never gets a bucket name for hospital data, and its test set ships inside its own
image so it has no reason to ask for one. Against A1.

### The training channel is encrypted and pinned

TLS on the gRPC channel with a self-signed CA. The hospitals pin `ca.crt`, so an
impostor cannot present its own certificate for the aggregator even though
nothing here is publicly trusted. The certificate is issued for
`fl-server.fedmed.local`, which is why Cloud Map is a prerequisite rather than a
convenience. Against A3.

### Inbound access is closed

The aggregator's security group admits port 8080 only from the hospital security
group. The hospital group admits nothing. Both sit in public subnets with public
IPs, which is a cost decision, and neither is reachable from the internet.
Against A4.

### Uploaded images are never persisted

`/predict` decodes into memory, classifies, and discards. The audit table records
a SHA-256 of the bytes, a timestamp and the predicted label. That proves a given
image was submitted if someone later presents the same file, and cannot be
inverted into the image. A test asserts that a prediction leaves the filesystem
byte-identical. Against A1 and A4.

### Published checkpoints are noised

Each client update is clipped to a fixed L2 norm and Gaussian noise is added to
the aggregate before anything is written to S3. Someone who downloads every
checkpoint from the versioned bucket is reading noised parameters. Against A1.

## What does not hold

### The differential-privacy budget is loose, and saying otherwise would be false

The accountant reports an epsilon for the noise multiplier and round count in
use. At the default setting it is in the thousands, which is not a meaningful
formal guarantee.

The reason is structural rather than a tuning mistake. Differential privacy in
federated learning gets most of its strength from subsampling amplification:
selecting a small random fraction of clients each round means any individual site
participates rarely, and the accountant credits that. With three hospitals all
participating in every round the sampling rate is one and there is no
amplification to collect. Reaching a single-digit epsilon would need a noise
multiplier that, as `artifacts/experiments.md` measures, costs twenty to thirty
accuracy points and produces a model not worth serving.

The honest claim is therefore narrow. Clipping and noise measurably blunt how
much any single patient's record can influence the published weights, and the
platform reports its exact parameters and the resulting budget instead of
labelling itself private. The fix is more participating sites, which is the
regime the technique was designed for. It is not a bigger number in the epsilon
column.

The dashboard says this in the interface, not only in this file.

### The aggregator sees individual updates

Against A5, nothing here helps. The server receives each hospital's parameters
separately, and gradient-inversion research has reconstructed recognisable
training images from updates in some settings. Secure aggregation is the answer:
under SecAgg+ the server can decrypt only the sum, never any individual
contribution. Flower implements it. It was left out to keep the protocol
inspectable for a teaching project, and it is the single most valuable addition.

Two things reduce the exposure without removing it. Each hospital sends weights
after a full local epoch over hundreds or thousands of images rather than a
single-batch gradient, which is a much harder starting point for inversion. And
clipping bounds how far any one update can move.

### Per-hospital IAM isolation is described, not enforced

The intended design gives each hospital task a role that can read only its own
bucket. An AWS Academy Learner Lab cannot create IAM roles, so every task runs as
the shared `LabRole` and could in principle read another hospital's bucket. What
is actually enforced is bucket separation, a bucket policy denying non-TLS
access, and the absence of any code path that would do it.

This is a real gap and it should be named as such in the report. On an account
that permits IAM, three task roles with a bucket-scoped read policy each would
close it, and the Terraform change is roughly twenty lines.

### The dashboard is plain HTTP with no authentication

An S3 website endpoint does not support HTTPS, and there is no login. Anyone with
the URL sees the training metrics and can call `/predict`. Acceptable only
because the page holds no credentials and the dataset is public research data.
A real deployment needs CloudFront for TLS and an authenticated identity, which
also gives the audit trail a subject worth recording.

### The model itself can leak

Membership-inference attacks ask whether a particular record was in the training
set, and a model that generalises imperfectly can answer. The noise helps and
does not eliminate this. No membership-inference evaluation was run, so no claim
is made either way.

### Terraform state holds the private key

With `tls_enabled = true` the certificate and key are read from disk and stored
in SSM, and they pass through Terraform state, which is a local file in this
project. Fine for a course; a real deployment uses an encrypted S3 backend with
a lock table, or creates the parameters out of band and references them by ARN.

## Summary

| Threat | Status |
|---|---|
| Raw images cross the network | Prevented by construction |
| One breach exposes the pooled dataset | Prevented, no pooled store exists |
| Traffic interception or impersonation | Prevented by pinned TLS |
| Public reaches the training plane | Prevented by security groups |
| Uploaded scans persisted | Prevented, hash-only audit |
| Checkpoints reveal individuals | Reduced by clipping and noise, budget is loose |
| Aggregator inspects one site's update | **Not addressed.** Needs secure aggregation |
| One hospital reads another's bucket | **Not enforced** under Learner Lab IAM |
| Dashboard confidentiality | **Not addressed.** Plain HTTP, no auth |
| Membership inference on the model | **Not evaluated** |
