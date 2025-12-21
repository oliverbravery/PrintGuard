from fastapi import APIRouter
from .inference import router as inference_router
from .health import router as health_router
from .rtc import router as rtc_router
from .push import router as push_router
from .cloudflare import router as cloudflare_router
from .ngrok import router as ngrok_router
from .tunnel import router as tunnel_router
from .printer import router as printer_router
from .crypto import router as crypto_router
from ..crypto_utils import EncryptedRoute

router = APIRouter(route_class=EncryptedRoute)

router.include_router(inference_router)
router.include_router(health_router)
router.include_router(rtc_router, prefix="/rtc", tags=["rtc"])
router.include_router(push_router, prefix="/push", tags=["push"])
router.include_router(cloudflare_router, prefix="/cloudflare", tags=["cloudflare"])
router.include_router(ngrok_router, prefix="/ngrok", tags=["ngrok"])
router.include_router(tunnel_router, prefix="/tunnel", tags=["tunnel"])
router.include_router(printer_router)
router.include_router(crypto_router)
