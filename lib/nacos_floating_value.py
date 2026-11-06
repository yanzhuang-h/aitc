import hashlib
import json
import logging
import os
import threading
from urllib import error, parse, request

from lib.floating_value import FLOATING_VALUE_PATH, replace_floating_value_records
from lib.road_state import ROAD_STATE_PATH, replace_road_state_config
from phase_check import (
    INTERSECTION_CONFIG_PATH,
    replace_intersection_result_config,
)
from time_schedule.nacos_schedule_config import (
    MANIFEST_PATH,
    SCHEDULE_DIR,
    apply_time_schedule_config,
    save_time_schedule_manifest,
    validate_time_schedule_config,
    validate_time_schedule_manifest,
)


LOGGER = logging.getLogger(__name__)


class NacosFloatingValueSync:
    def __init__(self, path=FLOATING_VALUE_PATH):
        self.path = path
        self.server_url = os.getenv(
            "NACOS_SERVER_URL", "http://124.174.23.231:8848"
        ).rstrip("/")
        self.username = os.getenv("NACOS_USERNAME", "nacos")
        self.password = os.getenv("NACOS_PASSWORD", "")
        self.namespace = os.getenv("NACOS_NAMESPACE", "public")
        self.data_id = os.getenv("NACOS_DATA_ID", "floating_value.json")
        self.group = os.getenv("NACOS_GROUP", "DEFAULT_GROUP")
        self.poll_interval = max(float(os.getenv("NACOS_POLL_INTERVAL", "5")), 1.0)
        self.timeout = max(float(os.getenv("NACOS_TIMEOUT", "5")), 1.0)
        self.check_rules = os.getenv("NACOS_CHECK_RULES", "true").lower() not in {
            "0", "false", "no"
        }
        self._access_token = None
        self._remote_md5 = None
        self._stop_event = threading.Event()
        self._thread = None
        self.config_name = "floating-value"
        self.thread_name = "nacos-floating-value-sync"

    @property
    def configured(self):
        return bool(self.server_url and self.username and self.password)

    def start(self):
        if not self.configured:
            LOGGER.warning(
                "Nacos %s sync is disabled: NACOS_PASSWORD is not set",
                self.config_name,
            )
            return False
        if self._thread and self._thread.is_alive():
            return True

        self._stop_event.clear()
        self._thread = threading.Thread(
            target=self._run,
            name=self.thread_name,
            daemon=True,
        )
        self._thread.start()
        return True

    def stop(self):
        self._stop_event.set()
        if self._thread and self._thread.is_alive():
            self._thread.join(timeout=self.timeout + 1)

    def sync_once(self):
        if not self.configured:
            raise RuntimeError("NACOS_PASSWORD is not set")

        response = self._get_config()
        content = response.get("content")
        if not isinstance(content, str):
            raise ValueError("Nacos response does not contain configuration content")

        remote_md5 = response.get("md5") or hashlib.md5(
            content.encode("utf-8")
        ).hexdigest()
        if remote_md5 == self._remote_md5:
            return False

        records = json.loads(content)
        replace_floating_value_records(
            records,
            path=self.path,
            check_rules=self.check_rules,
        )
        self._remote_md5 = remote_md5
        LOGGER.info(
            "Nacos configuration %s/%s synchronized to %s (md5=%s)",
            self.group,
            self.data_id,
            self.path,
            remote_md5,
        )
        return True

    def _run(self):
        while not self._stop_event.is_set():
            try:
                self.sync_once()
            except Exception as exc:
                LOGGER.error(
                    "Failed to synchronize %s configuration from Nacos: %s",
                    self.config_name,
                    exc,
                )
            self._stop_event.wait(self.poll_interval)

    def _login(self):
        body = parse.urlencode({
            "username": self.username,
            "password": self.password,
        }).encode("utf-8")
        payload = self._request_json(
            "/nacos/v3/auth/user/login",
            method="POST",
            data=body,
        )
        token = payload.get("accessToken")
        if isinstance(payload.get("data"), dict):
            token = payload["data"].get("accessToken") or token
        if not token:
            raise ValueError("Nacos login response does not contain an access token")
        self._access_token = token

    def _get_config(self, retry_login=True, data_id=None):
        if not self._access_token:
            self._login()

        selected_data_id = data_id or self.data_id
        query = parse.urlencode({
            "dataId": selected_data_id,
            "groupName": self.group,
            "namespaceId": self.namespace,
            "accessToken": self._access_token,
        })
        try:
            payload = self._request_json(f"/nacos/v3/client/cs/config?{query}")
        except error.HTTPError as exc:
            if exc.code not in {401, 403} or not retry_login:
                raise
            self._access_token = None
            self._login()
            return self._get_config(retry_login=False, data_id=selected_data_id)

        if payload.get("code") in {401, 403} and retry_login:
            self._access_token = None
            self._login()
            return self._get_config(retry_login=False, data_id=selected_data_id)
        if payload.get("code") not in {None, 0, 200}:
            raise ValueError(f"Nacos returned error: {payload.get('message') or payload}")
        data = payload.get("data")
        return data if isinstance(data, dict) else payload

    def _request_json(self, path, method="GET", data=None):
        req = request.Request(
            f"{self.server_url}{path}",
            data=data,
            method=method,
            headers={"Content-Type": "application/x-www-form-urlencoded"},
        )
        with request.urlopen(req, timeout=self.timeout) as response:
            return json.loads(response.read().decode("utf-8"))


class NacosIntersectionResultConfigSync(NacosFloatingValueSync):
    def __init__(self, path=INTERSECTION_CONFIG_PATH):
        super().__init__(path=path)
        self.data_id = os.getenv(
            "NACOS_INTERSECTION_CONFIG_DATA_ID",
            "intersection_result_config.json",
        )
        self.config_name = "intersection-result"
        self.thread_name = "nacos-intersection-result-sync"

    def sync_once(self):
        if not self.configured:
            raise RuntimeError("NACOS_PASSWORD is not set")

        response = self._get_config()
        content = response.get("content")
        if not isinstance(content, str):
            raise ValueError("Nacos response does not contain configuration content")

        remote_md5 = response.get("md5") or hashlib.md5(
            content.encode("utf-8")
        ).hexdigest()
        if remote_md5 == self._remote_md5:
            return False

        config = json.loads(content)
        replace_intersection_result_config(config, path=self.path)
        self._remote_md5 = remote_md5
        LOGGER.info(
            "Nacos configuration %s/%s synchronized to %s (md5=%s)",
            self.group,
            self.data_id,
            self.path,
            remote_md5,
        )
        return True


class NacosRoadStateSync(NacosFloatingValueSync):
    def __init__(self, path=ROAD_STATE_PATH):
        super().__init__(path=path)
        self.data_id = os.getenv(
            "NACOS_ROAD_STATE_DATA_ID",
            "road_state.json",
        )
        self.config_name = "road-state"
        self.thread_name = "nacos-road-state-sync"

    def sync_once(self):
        if not self.configured:
            raise RuntimeError("NACOS_PASSWORD is not set")

        response = self._get_config()
        content = response.get("content")
        if not isinstance(content, str):
            raise ValueError("Nacos response does not contain configuration content")

        remote_md5 = response.get("md5") or hashlib.md5(
            content.encode("utf-8")
        ).hexdigest()
        if remote_md5 == self._remote_md5:
            return False

        config = json.loads(content)
        replace_road_state_config(config, path=self.path)
        self._remote_md5 = remote_md5
        LOGGER.info(
            "Nacos configuration %s/%s synchronized to %s (md5=%s)",
            self.group,
            self.data_id,
            self.path,
            remote_md5,
        )
        return True


class NacosTimeScheduleSync(NacosFloatingValueSync):
    def __init__(self, schedule_dir=SCHEDULE_DIR, manifest_path=MANIFEST_PATH):
        super().__init__(path=str(schedule_dir))
        self.manifest_path = str(manifest_path)
        self.data_id = os.getenv(
            "NACOS_TIME_SCHEDULE_MANIFEST_DATA_ID",
            "time_schedule_manifest.json",
        )
        self.config_name = "time-schedule"
        self.thread_name = "nacos-time-schedule-sync"
        self._versions = {}
        self._load_local_versions()

    def _load_local_versions(self):
        if not os.path.exists(self.manifest_path):
            return
        try:
            with open(self.manifest_path, "r", encoding="utf-8-sig") as file:
                manifest = validate_time_schedule_manifest(json.load(file))
            for cross_id, item in manifest["items"].items():
                workday_path = os.path.join(
                    self.path,
                    f"Time_schedule_{cross_id}.json",
                )
                if os.path.exists(workday_path):
                    self._versions[cross_id] = item["version"]
        except Exception as exc:
            LOGGER.warning("Local time schedule manifest was ignored: %s", exc)

    def sync_once(self):
        if not self.configured:
            raise RuntimeError("NACOS_PASSWORD is not set")

        response = self._get_config()
        content = response.get("content")
        if not isinstance(content, str):
            raise ValueError("Nacos response does not contain manifest content")

        remote_md5 = response.get("md5") or hashlib.md5(
            content.encode("utf-8")
        ).hexdigest()
        if remote_md5 == self._remote_md5:
            return False

        manifest = validate_time_schedule_manifest(json.loads(content))
        changed_count = 0
        failures = []
        for cross_id, item in manifest["items"].items():
            if self._versions.get(cross_id) == item["version"]:
                continue
            try:
                config_response = self._get_config(data_id=item["data_id"])
                config_content = config_response.get("content")
                if not isinstance(config_content, str):
                    raise ValueError("configuration content is missing")
                schedule = validate_time_schedule_config(
                    json.loads(config_content),
                    expected_cross_id=cross_id,
                )
                apply_time_schedule_config(schedule, schedule_dir=self.path)
                self._versions[cross_id] = item["version"]
                changed_count += 1
            except Exception as exc:
                failures.append(f"{cross_id}: {exc}")

        if failures:
            raise ValueError(
                "failed time schedule updates: " + "; ".join(failures[:10])
            )

        save_time_schedule_manifest(manifest, path=self.manifest_path)
        self._remote_md5 = remote_md5
        LOGGER.info(
            "Nacos time schedule manifest version %s synchronized; "
            "%s intersection configs updated",
            manifest["version"],
            changed_count,
        )
        return True
