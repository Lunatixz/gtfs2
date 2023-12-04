"""The GTFS integration."""
from __future__ import annotations

import logging
from homeassistant.config_entries import ConfigEntry
from homeassistant.core import HomeAssistant, ServiceCall

from datetime import timedelta

from .const import DOMAIN, PLATFORMS, DEFAULT_PATH, DEFAULT_REFRESH_INTERVAL
from homeassistant.const import CONF_HOST
from .coordinator import GTFSUpdateCoordinator
import voluptuous as vol
from .gtfs_helper import get_gtfs
from .gtfs_rt_helper import get_gtfs_rt_trip

_LOGGER = logging.getLogger(__name__)

async def async_migrate_entry(hass, config_entry: ConfigEntry) -> bool:
    """Migrate old entry."""
    _LOGGER.warning("Migrating from version %s", config_entry.version)

    if config_entry.version == 1:

        new_data = {**config_entry.data}
        new_data['extract_from'] = 'url'
        new_data.pop('refresh_interval')
        
        new_options = {**config_entry.options}
        new_options['real_time'] = False
        new_options['refresh_interval'] = 15
        new_options['api_key'] = ""
        new_options['x_api_key'] = ""
        new_options['offset'] = 0
        new_data.pop('offset')
        
        config_entry.version = 5
        hass.config_entries.async_update_entry(config_entry, data=new_data)
        hass.config_entries.async_update_entry(config_entry, options=new_options)
    
    if config_entry.version == 2:

        new_options = {**config_entry.options}
        new_data = {**config_entry.data}
        new_options['real_time'] = False
        new_options['api_key'] = ""
        new_options['x_api_key'] = ""
        new_options['offset'] = 0
        new_data.pop('offset')

        config_entry.version = 5
        hass.config_entries.async_update_entry(config_entry, options=new_options)  
        hass.config_entries.async_update_entry(config_entry, data=new_data)        

    if config_entry.version == 3:

        new_options = {**config_entry.options}
        new_data = {**config_entry.data}
        new_options['api_key'] = ""
        new_options['x_api_key'] = ""
        new_options['offset'] = 0
        new_data.pop('offset')

        config_entry.version = 5
        hass.config_entries.async_update_entry(config_entry, options=new_options)  
        hass.config_entries.async_update_entry(config_entry, data=new_data)
        
    if config_entry.version == 4:

        new_options = {**config_entry.options}
        new_data = {**config_entry.data}
        new_options['offset'] = 0
        new_data.pop('offset')

        config_entry.version = 5
        hass.config_entries.async_update_entry(config_entry, data=new_data)
        hass.config_entries.async_update_entry(config_entry, options=new_options)          

    _LOGGER.warning("Migration to version %s successful", config_entry.version)

    return True

async def async_setup_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Set up GTFS from a config entry."""

    hass.data.setdefault(DOMAIN, {})

    coordinator = GTFSUpdateCoordinator(hass, entry)

    #await coordinator.async_config_entry_first_refresh()
    
    if not coordinator.last_update_success:
        raise ConfigEntryNotReady
    
    hass.data[DOMAIN][entry.entry_id] = {
        "coordinator": coordinator,
    }
    
    entry.async_on_unload(entry.add_update_listener(update_listener))
      
    await hass.config_entries.async_forward_entry_setups(entry, PLATFORMS)

    return True


async def async_unload_entry(hass: HomeAssistant, entry: ConfigEntry) -> bool:
    """Unload a config entry."""
    if unload_ok := await hass.config_entries.async_unload_platforms(entry, PLATFORMS):
        hass.data[DOMAIN].pop(entry.entry_id)

    return unload_ok
    
async def async_remove_entry(hass: HomeAssistant, entry: ConfigEntry) -> None:
    """Remove a config entry."""
    await hass.async_add_executor_job(_remove_token_file, hass, entry.data[CONF_HOST])
    if DOMAIN in hass.data:
        hass.data[DOMAIN].pop(entry.entry_id, None)
        if not hass.data[DOMAIN]:
            hass.data.pop(DOMAIN)    

def setup(hass, config):
    """Setup the service component."""

    def update_gtfs(call):
        """My GTFS service."""
        _LOGGER.debug("Updating GTFS with: %s", call.data)
        get_gtfs(hass, DEFAULT_PATH, call.data, True)
        return True
        
    def download_gtfs_rt_trip(call: ServiceCall):
        """My GTFS service."""
        _LOGGER.debug("Updating GTFS with: %s", call.data)
        _LOGGER.debug("Updating GTFS with entity: %s", dir(call))
        _LOGGER.debug("Updating GTFS with entity2: %s", dir(call.context))
        _LOGGER.debug("Updating GTFS with entity3: %s", call.return_response)
        _LOGGER.debug("Updating GTFS with entity4: %s", call.service)
        
       
        get_gtfs_rt_trip(hass, DEFAULT_PATH, call.data)
        return True        

    hass.services.register(
        DOMAIN, "update_gtfs", update_gtfs)
    hass.services.register(
        DOMAIN, "download_gtfs_rt_trip", download_gtfs_rt_trip)        
    return True

async def update_listener(hass: HomeAssistant, entry: ConfigEntry):
    """Handle options update."""
    hass.data[DOMAIN][entry.entry_id]['coordinator'].update_interval = timedelta(minutes=1)

    return True