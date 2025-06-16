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
        if resp.status_code == 409:
            return
        resp.raise_for_status()

    def get_printer_temperatures(self) -> Dict[str, TemperatureReading]:
        resp = requests.get(f"{self.base_url}/api/printer",
                            headers=self.headers,
                            timeout=10)
        resp.raise_for_status()
        state = TemperatureReadings(**resp.json())
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
    
    def get_printer_state(self) -> PrinterState:
        temperature_readings = self.get_printer_temperatures()
        printer_temps: PrinterTemperatures = PrinterTemperatures(
            nozzle_actual=temperature_readings.get("tool0").actual if "tool0" in temperature_readings else None,
            nozzle_target=temperature_readings.get("tool0").target if "tool0" in temperature_readings else None,
            bed_actual=temperature_readings.get("bed").actual if "bed" in temperature_readings else None,
            bed_target=temperature_readings.get("bed").target if "bed" in temperature_readings else None
        )
        printer_state = PrinterState(
            jobInfoResponse=self.get_job_info(),
            temperatureReadings=printer_temps
        )
        return printer_state
