from typing import Dict
import requests
from ...models import (FileInfo, JobInfoResponse,
                       TemperatureReadings, TemperatureReading,
                       PrinterState, PrinterTemperatures)


class OctoPrintClient:
    """
    A client for interacting with OctoPrint's REST API.
    
    This class provides methods to control and monitor 3D printers through
    OctoPrint's web interface, including job management, temperature monitoring,
    and printer state retrieval.
    
    Attributes:
        base_url (str): The base URL of the OctoPrint instance
        headers (dict): HTTP headers including API key for authentication
    """
    
    def __init__(self, base_url: str, api_key: str):
        """
        Initialize the OctoPrint client.
        
        Args:
            base_url (str): The base URL of the OctoPrint instance (e.g., 'http://octopi.local')
            api_key (str): The API key for authentication with OctoPrint
        """
        self.base_url = base_url.rstrip("/")
        self.headers = {
            "X-Api-Key": api_key,
            "Content-Type": "application/json"
        }

    def get_job_info(self) -> JobInfoResponse:
        """
        Retrieve information about the current print job.
        
        Returns:
            JobInfoResponse: Complete job information including progress, file details,
                           and print statistics
            
        Raises:
            requests.HTTPError: If the API request fails
            requests.Timeout: If the request times out
        """
        resp = requests.get(f"{self.base_url}/api/job",
                            headers=self.headers,
                            timeout=10)
        resp.raise_for_status()
        return JobInfoResponse(**resp.json())

    def cancel_job(self) -> None:
        """
        Cancel the currently running print job.
        
        This will immediately stop the current print job and return the printer
        to an idle state.
        
        Raises:
            requests.HTTPError: If the API request fails
            requests.Timeout: If the request times out
        """
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
        """
        Pause the currently running print job.
        
        This will temporarily halt the current print job, allowing it to be
        resumed later.
        
        Raises:
            requests.HTTPError: If the API request fails
            requests.Timeout: If the request times out
        """
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
        """
        Retrieve current temperature readings from all printer components.
        
        Returns:
            Dict[str, TemperatureReading]: Dictionary mapping component names
                                         (e.g., 'tool0', 'bed') to their temperature readings.
                                         Returns empty dict if printer is not operational.
            
        Raises:
            requests.HTTPError: If the API request fails (except for 409 conflicts)
            requests.Timeout: If the request times out
        """
        resp = requests.get(f"{self.base_url}/api/printer",
                            headers=self.headers,
                            timeout=10)
        if resp.status_code == 409:
            return {}
        resp.raise_for_status()
        state = TemperatureReadings(**resp.json())
        return state.temperature

    def percent_complete(self) -> float:
        """
        Get the completion percentage of the current print job.
        
        Returns:
            float: Completion percentage (0.0 to 100.0)
            
        Raises:
            requests.HTTPError: If the API request fails
            requests.Timeout: If the request times out
        """
        return self.get_job_info().progress.completion * 100

    def current_file(self) -> FileInfo:
        """
        Get information about the currently loaded file.
        
        Returns:
            FileInfo: Details about the file being printed, including name,
                     size, and other metadata
            
        Raises:
            requests.HTTPError: If the API request fails
            requests.Timeout: If the request times out
        """
        return self.get_job_info().job["file"]

    def nozzle_and_bed_temps(self) -> Dict[str, float]:
        """
        Get simplified temperature readings for nozzle and bed.
        
        This method provides a simplified interface to temperature data,
        returning both actual and target temperatures for the primary nozzle
        and heated bed.
        
        Returns:
            Dict[str, float]: Dictionary with keys:
                - 'nozzle_actual': Current nozzle temperature
                - 'nozzle_target': Target nozzle temperature  
                - 'bed_actual': Current bed temperature
                - 'bed_target': Target bed temperature
                Returns 0.0 for all values if temperatures are unavailable.
        """
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
        """
        Get comprehensive printer state information.
        
        This method combines job information and temperature readings into
        a unified printer state object, providing a complete snapshot of
        the printer's current status.
        
        Returns:
            PrinterState: Complete printer state including job information
                         and temperature readings. Job info may be None if
                         retrieval fails.
                         
        Note:
            If job information retrieval fails, the jobInfoResponse field
            will be None, but temperature data will still be included if available.
        """
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
