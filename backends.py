from __future__ import annotations

from pathlib import Path

import numpy as np
from ai_edge_litert.interpreter import Interpreter

from core import Assets, classify, initialise, load_assets, preprocess


class ServerBackend:
    def __init__(self, model_dir: str | Path) -> None:
        d = Path(model_dir)
        self.assets: Assets = load_assets(d)
        initialise(self.assets)
        self.interpreter = Interpreter(model_path=str(d / "encoder_float32.tflite"))
        self.interpreter.allocate_tensors()
        details = self.interpreter.get_input_details()[0]
        self._input_idx = details["index"]
        self._output_idx = self.interpreter.get_output_details()[0]["index"]

    def infer(self, frame: np.ndarray) -> dict:
        pre = preprocess(frame)
        self.interpreter.set_tensor(self._input_idx, pre)
        self.interpreter.invoke()
        emb: np.ndarray = self.interpreter.get_tensor(self._output_idx)[0].copy()
        if not np.isfinite(emb).all():
            return {"prediction": "unknown", "distances": [], "margin": 0.0}
        return classify(emb, self.assets.prototypes)
