from typing import Dict
import requests
from ...models import (FileInfo, JobInfoResponse, PrinterState,
                       TemperatureReading)


class OctoPrintClient:
    def __init__(self, base_url: str, api_key: str):
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }

    def get_job_info(self) -> JobInfoResponse:
        resp = requests.get(f"{self.base_url}/api/job",
                            headers=self.headers,
                            timeout=10)
        resp.raise_for_status()
        return JobInfoResponse(**resp.json())

    def cancel_job(self) -> None:
        resp = requests.post(
            f"{self.base_url}/api/job",
            headers=self.headers,
            timeout=10,
            json={"command": "cancel"}
        )
        resp.raise_for_status()

    def get_printer_temperatures(self) -> Dict[str, TemperatureReading]:
        resp = requests.get(f"{self.base_url}/api/printer",
                            headers=self.headers,
                            timeout=10)
        resp.raise_for_status()
        state = PrinterState(**resp.json())
        return state.temperature

    def percent_complete(self) -> float:
        return self.get_job_info().progress.completion * 100

    def current_file(self) -> FileInfo:
        return self.get_job_info().job["file"]

    def nozzle_and_bed_temps(self) -> Dict[str, float]:
        temps = self.get_printer_temperatures()
        tool0 = temps.get("tool0")
        bed   = temps.get("bed")
        return {
            "nozzle_actual": tool0.actual,
            "nozzle_target": tool0.target,
            "bed_actual"   : bed.actual,
            "bed_target"   : bed.target,
        }
