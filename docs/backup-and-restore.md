# Backup and restore

Stormcloud has two durable stores: PostgreSQL is authoritative for metadata and
references, while MinIO holds immutable source and derived objects. Back up both
as one recovery set.

## Create a recovery set

Run these commands from the repository root on the Docker host:

```sh
docker compose --profile full stop api pipeline-controller fetch-worker nlp-worker \
  llm-worker embedding-worker graph-worker mailer
./scripts/backup-postgres.sh
./scripts/backup-minio.sh
docker compose --profile full start api pipeline-controller fetch-worker nlp-worker \
  llm-worker embedding-worker graph-worker mailer
```

Stopping writers gives the database dump and object mirror a consistent boundary.
The scripts create timestamped paths under ignored `backups/` by default and
refuse to overwrite an existing backup. PostgreSQL uses a compressed custom-format
dump. The MinIO backup contains all three buckets and a format/version manifest.
Neither script prints credentials.

Copy each database dump and matching MinIO directory together to encrypted storage
on a different machine. Apply retention, access control, and encryption in that
backup destination. A backup on the same Docker volume is not disaster recovery.

## Restore safely

Restore into an isolated staging host first. Configure its `.env`, start only the
infrastructure services, and initialize empty buckets:

```sh
docker compose --profile infra up -d
docker compose --profile init run --rm init-buckets
./scripts/restore-postgres.sh backups/postgres/stormcloud-YYYYMMDDTHHMMSSZ.dump \
  --confirm stormcloud
./scripts/restore-minio.sh backups/minio/stormcloud-YYYYMMDDTHHMMSSZ \
  --confirm stormcloud
```

Both restore scripts require the exact confirmation target `stormcloud`.
PostgreSQL restore uses one transaction and replaces archived database objects.
MinIO restore overwrites matching keys but deliberately does not delete unrelated
keys. Do not point either command at a production Compose project while application
containers are writing.

After restoring, verify migrations, object references, and service readiness:

```sh
docker compose --profile init run --rm migrate
docker compose --profile full up -d
curl --fail http://127.0.0.1:8080/health/ready
docker compose ps
```

Exercise login, document retrieval, and at least one historical evidence artifact
before declaring the restore usable. Restore drills should be scheduled and timed;
an untested backup is only a hypothesis.

## MinIO client image

The mirror scripts pin their `minio/mc` image in the script. The Docker network
must be named `stormcloud`, which is already explicit in `compose.yaml`. Override
`STORMCLOUD_S3_ACCESS_KEY` and `STORMCLOUD_S3_SECRET_KEY` in the process
environment if the credentials are not in the local `.env`.

## Production notes

- Keep database credentials, object-store keys, and encryption keys out of backups,
  logs, source control, and Vercel.
- Encrypt recovery sets before copying them outside the trusted host.
- Prefer immutable/versioned remote backup storage and alert on failed jobs.
- Choose a backup interval from the acceptable recovery-point objective.
- Rotate credentials after any restore to a less-trusted environment.
