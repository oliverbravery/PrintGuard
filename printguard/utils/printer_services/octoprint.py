from typing import Dict
import requests
from ...models import (FileInfo, JobInfoResponse,
                       TemperatureReadings, TemperatureReading,
                       PrinterState, PrinterTemperatures)


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
        if resp.status_code == 204:
            return
        resp.raise_for_status()

    def pause_job(self) -> None:
        resp = requests.post(
            f"{self.base_url}/api/job",
            headers=self.headers,
            timeout=10,
            json={"command": "pause"}
        )
        if resp.status_code == 204:
            return
        resp.raise_for_status()

    def get_printer_temperatures(self) -> Dict[str, TemperatureReading]:
        resp = requests.get(f"{self.base_url}/api/printer",
                            headers=self.headers,
                            timeout=10)
        if resp.status_code == 409:
            return {}
        resp.raise_for_status()
        state = TemperatureReadings(**resp.json())
        return state.temperature

    def percent_complete(self) -> float:
        return self.get_job_info().progress.completion * 100

    def current_file(self) -> FileInfo:
        return self.get_job_info().job["file"]

    def nozzle_and_bed_temps(self) -> Dict[str, float]:
        temps = self.get_printer_temperatures()
        if not temps:
            return {
                "nozzle_actual": 0.0,
                "nozzle_target": 0.0,
                "bed_actual": 0.0,
                "bed_target": 0.0,
            }
        tool0 = temps.get("tool0")
        bed   = temps.get("bed")
        return {
            "nozzle_actual": tool0.actual if tool0 else 0.0,
            "nozzle_target": tool0.target if tool0 else 0.0,
            "bed_actual"   : bed.actual if bed else 0.0,
            "bed_target"   : bed.target if bed else 0.0,
        }

    def get_printer_state(self) -> PrinterState:
        temperature_readings = self.get_printer_temperatures()
        tool0_temp = temperature_readings.get("tool0") if temperature_readings else None
        bed_temp = temperature_readings.get("bed") if temperature_readings else None
        printer_temps: PrinterTemperatures = PrinterTemperatures(
            nozzle_actual=tool0_temp.actual if tool0_temp else None,
            nozzle_target=tool0_temp.target if tool0_temp else None,
            bed_actual=bed_temp.actual if bed_temp else None,
            bed_target=bed_temp.target if bed_temp else None
        )
        try:
            job_info = self.get_job_info()
        except Exception:
            job_info = None
        printer_state = PrinterState(
            jobInfoResponse=job_info,
            temperatureReading=printer_temps
        )
        return printer_state
