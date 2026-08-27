# Moving this to AWS — notes for later

Written 2026-08-26. **Not a plan to execute now.** The project is live on Render and that
is the right place for it today. This is the reference for doing it later as a deliberate
learning exercise, because the skills it teaches are worth more than the hosting change.

## Why bother at all

Not cost — AWS will be *more* expensive than Render's $7/month. The reason is that Render
deliberately hides the infrastructure, and the hidden parts are exactly what AI/ML
engineering roles screen for:

| Skill | Render teaches you | AWS makes you learn it |
|---|---|---|
| IAM roles & least-privilege policies | nothing | yes |
| VPC, subnets, security groups | nothing | yes |
| Container registry (ECR), image tagging | nothing | yes |
| Task definitions, CPU/memory sizing, secret injection | nothing | yes |
| Load balancing, target groups, health checks | nothing | yes |
| **Infrastructure as code (Terraform / CDK)** | nothing | yes ← highest value |
| **Keyless CI/CD via GitHub OIDC** | nothing | yes ← second highest |
| CloudWatch logs, metrics, alarms | partly | yes |
| TLS certificates (ACM), DNS (Route 53) | nothing | yes |

The two bolded rows are the ones that change how a resume reads. "Deployed on Render" is a
deployment. "Provisioned with Terraform, deployed via GitHub OIDC to ECS Fargate" is
infrastructure engineering.

## Which service

**ECS Fargate** — runs your container without you managing servers. Closest AWS analogue
to what Render does, and the version with real resume weight.

Ruled out:
- **App Runner** — the true Render clone, but closed to new customers.
- **Lambda / serverless** — this app holds a writable SQLite file and has a heavy ML
  dependency set (OR-Tools, Prophet, scikit-learn). Wrong shape.
- **Elastic Beanstalk** — works, but it's the "hides the infrastructure" option again, so
  it teaches the least of the three.
- **EC2 / Lightsail raw VM** — cheapest, but then you are patching an OS and renewing
  certificates forever, and you learn sysadmin rather than cloud architecture.

## Rough cost — verify before committing

AWS restructured its free tier recently; treat these as ballpark and re-check current
pricing for the target region before spending anything.

| Shape | Approx / month | Note |
|---|---|---|
| Fargate + Application Load Balancer | **$25–30** | The ALB alone is ~$16 and dominates the bill |
| Fargate + public IP, Cloudflare in front for TLS | ~$10 | Skips the ALB; loses the load-balancer talking point |
| Lightsail VM | $5–10 | Cheapest, least to talk about |

Storage: SQLite on a container filesystem is ephemeral. Either mount EFS (adds cost and
SQLite locking caveats) or — better long term — migrate to RDS/Postgres, which also
retires the "production is SQLite" caveat currently in the README.

## Rough effort

- **4–6 hours** to get it running by clicking through the console.
- **1–3 days** to do it properly with Terraform and OIDC — *and doing it properly is the
  entire point*. A console-clicked deployment teaches almost nothing and can't be shown to
  anyone.

## Sane order of work

1. Containerise cleanly and confirm the image builds with the full ML dependency set
   (this is where heavy Python deployments usually fail first).
2. Push to **ECR**.
3. Terraform: VPC, subnets, security groups, ECS cluster, task definition, service.
4. **ALB** in front, **ACM** certificate, health check on `/health`.
5. **GitHub OIDC** role so Actions can deploy with no long-lived AWS keys.
6. CloudWatch log group, plus one alarm worth having.
7. Decide on storage: EFS mount vs. migrating to RDS Postgres.
8. Cut over DNS **only once it works**.

## The one rule

**Keep Render running the whole time.** Build the AWS version alongside it and switch only
when it's genuinely working. The Render URL is on a resume — it does not go down for an
experiment.

## What to say afterwards

> "Containerised a FastAPI ML service and deployed it to AWS ECS Fargate behind an
> Application Load Balancer, with infrastructure defined in Terraform and keyless
> deployments from GitHub Actions via OIDC."

That sentence is the deliverable. The hosting change is incidental.
