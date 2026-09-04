import hashlib
import json
from dataclasses import dataclass
from typing import Any

import boto3
from botocore.client import BaseClient
from botocore.exceptions import ClientError

from stormcloud.config import Settings, get_settings


@dataclass(frozen=True)
class StoredObject:
    bucket: str
    key: str
    sha256: str
    size: int
    content_type: str


class ObjectStore:
    def __init__(self, settings: Settings | None = None, client: BaseClient | None = None) -> None:
        self.settings = settings or get_settings()
        self.client = client or boto3.client(
            "s3",
            endpoint_url=self.settings.s3_endpoint_url,
            aws_access_key_id=self.settings.s3_access_key,
            aws_secret_access_key=self.settings.s3_secret_key.get_secret_value(),
            region_name=self.settings.s3_region,
        )

    @property
    def buckets(self) -> tuple[str, str, str]:
        return (
            self.settings.s3_bucket_raw,
            self.settings.s3_bucket_normalized,
            self.settings.s3_bucket_derived,
        )

    def ensure_buckets(self) -> None:
        for bucket in self.buckets:
            try:
                self.client.head_bucket(Bucket=bucket)
            except ClientError:
                self.client.create_bucket(Bucket=bucket)
                self.client.put_bucket_versioning(
                    Bucket=bucket, VersioningConfiguration={"Status": "Enabled"}
                )

    def put_bytes(
        self, bucket: str, namespace: str, data: bytes, content_type: str
    ) -> StoredObject:
        digest = hashlib.sha256(data).hexdigest()
        key = f"{namespace}/{digest[:2]}/{digest}"
        try:
            self.client.head_object(Bucket=bucket, Key=key)
        except ClientError:
            self.client.put_object(
                Bucket=bucket,
                Key=key,
                Body=data,
                ContentType=content_type,
                Metadata={"sha256": digest},
            )
        return StoredObject(bucket, key, digest, len(data), content_type)

    def put_json(self, bucket: str, namespace: str, value: Any) -> StoredObject:
        data = json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()
        return self.put_bytes(bucket, namespace, data, "application/json")

    def get_bytes(self, bucket: str, key: str) -> bytes:
        return self.client.get_object(Bucket=bucket, Key=key)["Body"].read()

    def get_json(self, bucket: str, key: str) -> Any:
        return json.loads(self.get_bytes(bucket, key))

    def presigned_get(self, bucket: str, key: str, expires: int = 300) -> str:
        return self.client.generate_presigned_url(
            "get_object", Params={"Bucket": bucket, "Key": key}, ExpiresIn=expires
        )
