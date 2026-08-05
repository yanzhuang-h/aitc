import argparse
import json
import os
from concurrent.futures import ThreadPoolExecutor, as_completed
from urllib import parse, request

from time_schedule.nacos_schedule_config import (
    MANIFEST_PATH,
    build_time_schedule_configs,
    validate_time_schedule_manifest,
)


class NacosSchedulePublisher:
    def __init__(self):
        self.server_url = os.getenv(
            "NACOS_SERVER_URL", "http://124.174.23.231:8848"
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
        data = payload.get("data") if isinstance(payload.get("data"), dict) else {}
        self.access_token = data.get("accessToken") or payload.get("accessToken")
        if not self.access_token:
            raise ValueError("Nacos login response does not contain an access token")

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
                "Authorization": f"Bearer {self.access_token}",
                "accessToken": self.access_token,
                "Content-Type": "application/x-www-form-urlencoded",
            },
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            payload = json.loads(response.read().decode("utf-8"))
        if payload.get("code") not in {None, 0, 200} or payload.get("data") is False:
            raise ValueError(payload.get("message") or str(payload))
        return True


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
        json.dumps(manifest, ensure_ascii=False, indent=2),
        "路口时间表版本清单；修改路口配置后最后更新此文件",
    )
    print(
        f"published manifest version {manifest['version']} "
        f"after {len(selected)} route configs"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
