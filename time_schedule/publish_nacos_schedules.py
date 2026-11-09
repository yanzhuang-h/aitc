import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import parse, request
from urllib.error import HTTPError

from time_schedule.nacos_schedule_config import (
    MANIFEST_PATH,
    build_time_schedule_configs,
    save_time_schedule_manifest,
    validate_time_schedule_manifest,
)


class NacosSchedulePublisher:
    def __init__(self):
        self.server_url = os.getenv(
            "NACOS_SERVER_URL", "http://124.174.23.231:8080"
        ).rstrip("/")
        self.console_url = os.getenv(
            "NACOS_CONSOLE_URL", "http://124.174.23.231:8080"
        ).rstrip("/")
        self.username = os.getenv("NACOS_USERNAME", "nacos")
        self.password = os.getenv("NACOS_PASSWORD", "")
        self.namespace = os.getenv("NACOS_NAMESPACE", "public")
        self.group = os.getenv("NACOS_GROUP", "DEFAULT_GROUP")
        self.timeout = max(float(os.getenv("NACOS_TIMEOUT", "10")), 1.0)
        self.access_token = None

    def login(self):
        if not self.password:
            raise RuntimeError("NACOS_PASSWORD is not set")
        body = parse.urlencode({
            "username": self.username,
            "password": self.password,
        }).encode("utf-8")
        req = request.Request(
            f"{self.server_url}/nacos/v3/auth/user/login",
            data=body,
            method="POST",
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        token = payload.get("accessToken")
        if isinstance(payload.get("data"), dict):
            token = payload["data"].get("accessToken") or token
        if not token:
            raise ValueError("Nacos login response does not contain an access token")
        self.access_token = token

    def _headers(self):
        return {
            "Authorization": f"Bearer {self.access_token}",
            "accessToken": self.access_token,
        }

    def publish(self, data_id, content, description):
        if not self.access_token:
            self.login()
        query = parse.urlencode({"username": self.username})
        body = parse.urlencode({
            "dataId": data_id,
            "groupName": self.group,
            "namespaceId": self.namespace,
            "content": content,
            "type": "json",
            "desc": description,
            "configTags": "time_schedule",
            "appName": "AITC",
        }).encode("utf-8")
        req = request.Request(
            f"{self.console_url}/v3/console/cs/config?{query}",
            data=body,
            method="POST",
            headers={
                **self._headers(),
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") not in {None, 0, 200} or payload.get("data") is False:
            raise ValueError(payload.get("message") or str(payload))
        return True

    def fetch_config(self, data_id):
        """读取 Nacos 上的配置内容；不存在时返回 None。"""
        if not self.access_token:
            self.login()
        query = parse.urlencode({
            "dataId": data_id,
            "groupName": self.group,
            "namespaceId": self.namespace,
        })
        req = request.Request(
            f"{self.console_url}/v3/console/cs/config?{query}",
            headers=self._headers(),
        )
        try:
            with request.urlopen(req, timeout=self.timeout) as response:
                payload = json.loads(response.read().decode("utf-8"))
        except HTTPError as error:
            if error.code == 404:
                return None
            raise

        if payload.get("code") not in {None, 0, 200}:
            return None
        data = payload.get("data")
        if isinstance(data, dict) and isinstance(data.get("content"), str):
            return data["content"]
        return None


def _normalized(content):
    try:
        return json.dumps(
            json.loads(content),
            ensure_ascii=False,
            sort_keys=True,
        )
    except (TypeError, ValueError):
        return content


def build_merged_manifest(publisher, local_manifest, configs, selected):
    """把本地清单与 Nacos 现有清单合并：同名覆盖，异名保留。"""
    remote_manifest = None
    remote_content = publisher.fetch_config("time_schedule_manifest.json")
    if remote_content:
        try:
            remote_manifest = validate_time_schedule_manifest(
                json.loads(remote_content)
            )
        except (TypeError, ValueError):
            remote_manifest = None

    items = dict(remote_manifest["items"]) if remote_manifest else {}
    for cross_id, local_item in local_manifest["items"].items():
        if cross_id not in items:
            items[cross_id] = dict(local_item)

    changed = []
    for cross_id in sorted(selected):
        local_item = local_manifest["items"][cross_id]
        data_id = local_item["data_id"]
        local_content = json.dumps(
            configs[data_id], ensure_ascii=False, indent=2
        )

        remote_config = publisher.fetch_config(data_id)
        remote_version = items.get(cross_id, {}).get("version", 0)
        if remote_config is None or _normalized(remote_config) != _normalized(local_content):
            version = max(local_item["version"], remote_version) + 1
            changed.append(cross_id)
        else:
            version = max(local_item["version"], remote_version)

        items[cross_id] = {"data_id": data_id, "version": version}

    base_version = max(
        local_manifest["version"],
        remote_manifest["version"] if remote_manifest else 1,
    )
    merged_version = base_version + (1 if changed else 0)
    merged = validate_time_schedule_manifest({
        "schema_version": 1,
        "version": merged_version,
        "items": items,
    })
    return merged, changed


def main(argv=None):
    parser = argparse.ArgumentParser(
        description="Publish per-intersection time schedules and manifest to Nacos."
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=4,
        help="Number of concurrent route publications.",
    )
    parser.add_argument(
        "--only",
        action="append",
        default=[],
        help="Publish only this Cross ID; may be specified more than once.",
    )
    args = parser.parse_args(argv)

    configs = build_time_schedule_configs()
    with open(MANIFEST_PATH, "r", encoding="utf-8-sig") as manifest_file:
        manifest = validate_time_schedule_manifest(json.load(manifest_file))

    expected_ids = set(manifest["items"])
    config_ids = {
        data_id.removeprefix("time_schedule_").removesuffix(".json")
        for data_id in configs
    }
    if expected_ids != config_ids:
        raise ValueError("local manifest items do not match local schedule configs")

    selected = set(args.only) if args.only else expected_ids
    unknown = selected - expected_ids
    if unknown:
        raise ValueError(f"unknown Cross IDs: {sorted(unknown)}")

    publisher = NacosSchedulePublisher()
    publisher.login()

    merged_manifest, changed = build_merged_manifest(
        publisher, manifest, configs, selected
    )

    failures = []
    with ThreadPoolExecutor(max_workers=max(args.workers, 1)) as executor:
        futures = {}
        for cross_id in sorted(selected):
            data_id = manifest["items"][cross_id]["data_id"]
            content = json.dumps(configs[data_id], ensure_ascii=False, indent=2)
            future = executor.submit(
                publisher.publish,
                data_id,
                content,
                f"路口 {cross_id} 工作日与周末时间表",
            )
            futures[future] = cross_id

        for future in as_completed(futures):
            cross_id = futures[future]
            try:
                future.result()
                print(f"published {cross_id}")
            except Exception as exc:
                failures.append(f"{cross_id}: {exc}")

    if failures:
        raise RuntimeError(
            "route publication failed; manifest was not published: "
            + "; ".join(failures)
        )

    publisher.publish(
        "time_schedule_manifest.json",
        json.dumps(merged_manifest, ensure_ascii=False, indent=2),
        "路口时间表版本清单；修改路口配置后最后更新此文件",
    )
    save_time_schedule_manifest(merged_manifest)
    print(
        f"published manifest version {merged_manifest['version']} "
        f"after {len(selected)} route configs "
        f"(changed {len(changed)}, kept {len(merged_manifest['items']) - len(selected)})"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
