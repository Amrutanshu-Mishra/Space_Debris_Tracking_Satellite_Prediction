# k8s/

**Not on the demo path.** The live demo runs on `docker-compose` (see root
`docker-compose.yml`). These manifests exist purely as a scalability
artifact — evidence that the architecture isn't a docker-compose-only toy —
and are not deployed, tested, or exercised during the hackathon.

- `deployment-api.yaml`, `deployment-worker.yaml`, `deployment-web.yaml` —
  Deployments for the three custom images.
- `service-api.yaml`, `service-web.yaml` — ClusterIP Services.
- `ingress.yaml` — one host, `/api/*` to the API and everything else to the
  web bundle, mirroring the nginx proxy on the Compose path.
- `hpa-api.yaml` — HorizontalPodAutoscaler for the API on CPU utilisation.
- `cronjob-screening.yaml` — the worker's 6-hourly refresh+screen cycle,
  expressed as a Kubernetes CronJob instead of Celery Beat (an alternative
  scheduling story for a real deployment, not used in the demo where Celery
  Beat inside the worker container owns the schedule).

None of these reference real image registries or secrets — placeholders
only, named to make the intent obvious to a judge skimming the repo.
