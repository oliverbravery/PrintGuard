from typing import Dict, Set, Optional
import logging
from aiortc import MediaStreamTrack, RTCPeerConnection
from .webrtc import VideoProcessor
from ..core.models import FeedSettings

logger = logging.getLogger(__name__)

class SourceStream:
    """Represents a single media source and its subscribers."""
    def __init__(
        self, 
        source_id: str, 
        track: MediaStreamTrack, 
        processor: VideoProcessor,
        pc: Optional[RTCPeerConnection] = None,
        device_name: str = "Camera",
        settings: Optional[FeedSettings] = None
    ):
        self.source_id = source_id
        self.track = track
        self.processor = processor
        self.pc = pc
        self.device_name = device_name
        self.settings = settings or FeedSettings()
        self.subscribers: Set[RTCPeerConnection] = set()
        self.aliases: Set[str] = {source_id}

class StreamManager:
    """Manages shared media tracks and WebRTC sessions."""
    def __init__(self):
        self._sources: Dict[str, SourceStream] = {}

    def register_source(
        self, 
        source_id: str, 
        track: MediaStreamTrack, 
        processor: VideoProcessor,
        pc: Optional[RTCPeerConnection] = None,
        device_name: str = "Camera",
        settings: Optional[FeedSettings] = None
    ):
        """Register a new media source."""
        if source_id in self._sources:
            logger.warning(f"Source {source_id} already registered, overwriting.")
        
        self._sources[source_id] = SourceStream(
            source_id, track, processor, pc, device_name, settings
        )
        logger.info(f"Source {source_id} registered successfully.")

    def list_sources(self) -> list[SourceStream]:
        """List all unique sources (excluding duplicates from aliases)."""
        seen_ids = set()
        unique_sources = []
        for source in self._sources.values():
            if id(source) not in seen_ids:
                unique_sources.append(source)
                seen_ids.add(id(source))
        return unique_sources

    def add_alias(self, source_id: str, alias_id: str):
        """Add an alias for an existing source."""
        source = self._sources.get(source_id)
        if source:
            self._sources[alias_id] = source
            source.aliases.add(alias_id)
            logger.info(f"Alias {alias_id} registered for source {source_id}.")
        else:
            logger.error(f"Cannot add alias: Source {source_id} not found.")

    def get_source(self, source_id: str) -> Optional[SourceStream]:
        """Get an existing source by ID."""
        return self._sources.get(source_id)

    def add_subscriber(self, source_id: str, pc: RTCPeerConnection):
        """Add a subscriber to a source."""
        source = self._sources.get(source_id)
        if not source:
            logger.error(f"Cannot add subscriber: Source {source_id} not found.")
            return
        source.subscribers.add(pc)
        logger.debug(f"Added subscriber to source {source_id}. Total: {len(source.subscribers)}")

        @pc.on("connectionstatechanged")
        async def on_state_change():
            if pc.connectionState in ["closed", "failed"]:
                await self.remove_subscriber(source_id, pc)

    async def remove_subscriber(self, source_id: str, pc: RTCPeerConnection):
        """Remove a subscriber and cleanup if it was the last one."""
        source = self._sources.get(source_id)
        if not source:
            return
        source.subscribers.discard(pc)
        logger.debug(f"Removed subscriber from source {source_id}. Remaining: {len(source.subscribers)}")
        if not source.subscribers:
            await self.close_source(source_id)

    async def close_source(self, source_id: str):
        """Close a source and stop its processor."""
        source = self._sources.get(source_id)
        if source:
            logger.info(f"Closing source {source_id} (and its {len(source.aliases)-1} aliases) as it has no subscribers.")
            for alias in list(source.aliases):
                self._sources.pop(alias, None)
            source.processor._running = False
            if source.pc:
                await source.pc.close()

stream_manager = StreamManager()

