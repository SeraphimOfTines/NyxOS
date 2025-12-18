import logging
import asyncio
from aiohttp import web
import json
import os
import config

logger = logging.getLogger('NyxAPI')

BASE_DIR = os.path.dirname(os.path.abspath(__file__))
PALETTE_LAYOUT_FILE = os.path.join(BASE_DIR, "palette_layout.json")
PRESETS_FILE = os.path.join(BASE_DIR, "presets.json")

import memory_manager

class NyxAPI:
    def __init__(self, bot_client):
        self.bot = bot_client
        self.app = web.Application()
        self.port = config.CONTROL_API_PORT
        self.api_key = config.CONTROL_API_KEY
        
        # Middleware / Auth
        self.app.middlewares.append(self.auth_middleware)
        
        # Routes
        self.app.router.add_get('/api/status', self.handle_status)
        self.app.router.add_get('/api/bars', self.handle_get_bars)
        self.app.router.add_post('/api/global/update', self.handle_global_update)
        self.app.router.add_post('/api/global/state', self.handle_global_state)
        self.app.router.add_post('/api/bar/{channel_id}/update', self.handle_bar_update)
        self.app.router.add_get('/api/emojis', self.handle_get_emojis)
        self.app.router.add_post('/api/emojis/sync', self.handle_sync_emojis)
        
        # Persistence Routes
        self.app.router.add_get('/api/palette', self.handle_get_palette)
        self.app.router.add_post('/api/palette', self.handle_save_palette)
        self.app.router.add_get('/api/presets', self.handle_get_presets)
        self.app.router.add_post('/api/presets', self.handle_save_presets)
        
        # Static Files
        emojis_path = os.path.join(BASE_DIR, "emojis")
        if os.path.exists(emojis_path):
            self.app.router.add_static('/emojis', emojis_path)
        
        self.runner = None
        self.site = None

    async def auth_middleware(self, app, handler):
        async def middleware_handler(request):
            # CORS Headers
            headers = {
                'Access-Control-Allow-Origin': '*',
                'Access-Control-Allow-Methods': '*',
                'Access-Control-Allow-Headers': '*',
            }

            if request.method == 'OPTIONS':
                return web.Response(headers=headers)

            # Auth check
            provided_key = request.headers.get('x-api-key')
            if provided_key != self.api_key:
                return web.json_response({'error': 'Unauthorized'}, status=401, headers=headers)

            try:
                response = await handler(request)
                # Add CORS headers to response
                for key, value in headers.items():
                    response.headers[key] = value
                return response
            except Exception as e:
                logger.error(f"Request Error: {e}")
                return web.json_response({'error': str(e)}, status=500, headers=headers)
                
        return middleware_handler

    async def start(self):
        """Starts the web server."""
        self.runner = web.AppRunner(self.app, access_log=None)
        await self.runner.setup()
        # Listen on 0.0.0.0 to allow remote connections (protected by Key)
        self.site = web.TCPSite(self.runner, '0.0.0.0', self.port)
        await self.site.start()
        logger.info(f"NyxAPI Server started on port {self.port}")

    async def stop(self):
        """Stops the web server."""
        if self.site:
            await self.runner.cleanup()

    # --- Handlers ---

    async def handle_status(self, request):
        """Returns bot health and status."""
        return web.json_response({
            'status': 'online',
            'latency': round(self.bot.latency * 1000, 2),
            'user': str(self.bot.user),
            'id': self.bot.user.id
        })

    async def handle_get_emojis(self, request):
        """Returns a list of all custom emojis visible to the bot, filtered by Guild ID, merged with local storage."""
        emojis_data = []
        
        # 1. Fetch Discord Emojis
        for emoji in self.bot.emojis:
            # Filter: Only allow emojis from the configured Temple Guild
            if emoji.guild.id != config.TEMPLE_GUILD_ID:
                continue

            # Format: <a:Name:ID> or <:Name:ID>
            animated_tag = "a" if emoji.animated else ""
            full_str = f"<{animated_tag}:{emoji.name}:{emoji.id}>"
            
            emojis_data.append({
                "name": emoji.name,
                "id": str(emoji.id),
                "string": full_str,
                "animated": emoji.animated,
                "url": str(emoji.url),
                "source": "discord"
            })
            
        # 2. Fetch Local Emojis (from emoji_db.json or filesystem)
        local_db_path = os.path.join(BASE_DIR, "emoji_db.json")
        if os.path.exists(local_db_path):
            try:
                with open(local_db_path, "r") as f:
                    local_map = json.load(f)
                    
                # Get list of files in emojis/ dir to verify existence
                emojis_dir = os.path.join(BASE_DIR, "emojis")
                if os.path.exists(emojis_dir):
                    local_files = os.listdir(emojis_dir)
                    
                    for name, discord_str in local_map.items():
                        # Check if we already have this name from Discord (Discord takes precedence for live URL)
                        if any(e['name'] == name for e in emojis_data):
                            continue
                            
                        # Find matching file
                        fname = None
                        for ext in [".png", ".gif", ".jpg", ".jpeg", ".webp"]:
                            if f"{name}{ext}" in local_files:
                                fname = f"{name}{ext}"
                                break
                        
                        if fname:
                            # Construct URL to our static file server
                            # Host needs to be relative or absolute. Relative is safest for proxy/LAN.
                            # We can just return the filename and let frontend handle base URL
                            # Or return a full path relative to API root
                            url = f"/emojis/{fname}"
                            
                            emojis_data.append({
                                "name": name,
                                "id": name, # Use name as ID for local
                                "string": discord_str,
                                "animated": fname.endswith(".gif"),
                                "url": url,
                                "source": "local"
                            })
            except Exception as e:
                logger.error(f"Failed to load local emojis: {e}")
            
        return web.json_response({'emojis': emojis_data, 'count': len(emojis_data)})

    async def handle_sync_emojis(self, request):
        """
        Scans all available emojis (Discord + Local) and adds any that are missing
        from the palette_layout.json to the 'hidden' category.
        """
        try:
            # 1. Get current palette
            if os.path.exists(PALETTE_LAYOUT_FILE):
                with open(PALETTE_LAYOUT_FILE, "r") as f:
                    palette = json.load(f)
            else:
                palette = {"categories": {"Yami":[],"Calyptra":[],"Riven":[],"SΛTVRN":[],"Other":[]}, "hidden": [], "use_counts": {}}

            # Flatten current palette to a set of names for fast lookup
            existing_names = set(palette["hidden"])
            for cat_list in palette["categories"].values():
                existing_names.update(cat_list)

            # 2. Get All Available Emojis (Reuse logic by calling internal helper if we refactored, 
            # or just repeat simple fetch since we need names)
            
            # Fetch Discord Emojis
            discord_names = []
            for emoji in self.bot.emojis:
                if emoji.guild.id != config.TEMPLE_GUILD_ID: continue
                discord_names.append(emoji.name)

            # Fetch Local Emojis
            local_db_path = os.path.join(BASE_DIR, "emoji_db.json")
            if os.path.exists(local_db_path):
                 with open(local_db_path, "r") as f:
                    local_map = json.load(f)
                    discord_names.extend(local_map.keys())

            # 3. Add Missing to Hidden
            added_count = 0
            for name in discord_names:
                if name not in existing_names:
                    palette["hidden"].append(name)
                    existing_names.add(name) # Prevent dups if local and discord match
                    added_count += 1
            
            # 4. Save
            if added_count > 0:
                with open(PALETTE_LAYOUT_FILE, "w") as f:
                    json.dump(palette, f, indent=4)
            
            return web.json_response({'status': 'success', 'added': added_count})
            
        except Exception as e:
            logger.error(f"Sync Error: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_bars(self, request):
        """Returns a list of all active status bars."""
        bars_data = []
        global_content = ""

        # 1. Try to get Master Bar content directly from DB first (Source of Truth)
        try:
            global_content = memory_manager.get_master_bar()
        except:
            pass

        # 2. Optimization: Using internal cache where possible to avoid API spam
        for channel_id, message_id in self.bot.active_bars.items():
            channel = self.bot.get_channel(channel_id)
            if not channel:
                continue
            
            category = channel.category.name if channel.category else "Uncategorized"
            
            # Fallback: Try to get content from cache to populate initial state if DB failed
            if not global_content:
                try:
                    msg = self.bot.get_message(message_id)
                    if not msg:
                        try:
                            msg = await channel.fetch_message(message_id)
                        except:
                            pass
                    
                    if msg:
                        global_content = msg.content
                except:
                    pass

            bars_data.append({
                'channel_id': str(channel_id),
                'channel_name': channel.name,
                'category': category,
                'message_id': str(message_id)
            })

        return web.json_response({
            'bars': bars_data, 
            'count': len(bars_data),
            'global_content': global_content
        })

    async def handle_global_update(self, request):
        """Updates the text content of ALL bars (Master Bar propagation)."""
        try:
            data = await request.json()
            new_content = data.get('content')
            
            if not new_content:
                return web.json_response({'error': 'Missing content'}, status=400)
                
            # Call the existing function in NyxOS.py
            if hasattr(self.bot, 'global_update_bars'):
                 await self.bot.global_update_bars(new_content)
                 return web.json_response({'status': 'success', 'updated_content': new_content})
            else:
                 return web.json_response({'error': 'Bot function not found'}, status=500)

        except Exception as e:
            logger.error(f"API Error: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_global_state(self, request):
        """Sleep/Idle/Awake all bars."""
        try:
            data = await request.json()
            action = data.get('action') # 'sleep', 'idle', 'awake'
            
            if action == 'sleep':
                if hasattr(self.bot, 'sleep_all_bars'):
                    await self.bot.sleep_all_bars() 
            elif action == 'idle':
                if hasattr(self.bot, 'idle_all_bars'):
                    await self.bot.idle_all_bars()
            elif action == 'awake':
                 if hasattr(self.bot, 'awake_all_bars'):
                    await self.bot.awake_all_bars()
            else:
                return web.json_response({'error': 'Invalid action'}, status=400)
                
            return web.json_response({'status': 'success', 'action': action})
        except Exception as e:
            logger.error(f"API Error: {e}")
            return web.json_response({'error': str(e)}, status=500)

    async def handle_bar_update(self, request):
        """Updates a specific bar."""
        # To be implemented for granular control
        return web.json_response({'status': 'not_implemented_yet'})

    # --- Persistence Handlers ---

    async def handle_get_palette(self, request):
        if os.path.exists(PALETTE_LAYOUT_FILE):
            try:
                with open(PALETTE_LAYOUT_FILE, "r") as f:
                    data = json.load(f)
                return web.json_response(data)
            except Exception as e:
                return web.json_response({'error': f"Failed to load palette: {e}"}, status=500)
        return web.json_response({"categories": {"Yami":[],"Calyptra":[],"Riven":[],"SΛTVRN":[],"Other":[]}, "hidden": [], "use_counts": {}})

    async def handle_save_palette(self, request):
        try:
            data = await request.json()
            with open(PALETTE_LAYOUT_FILE, "w") as f:
                json.dump(data, f, indent=4)
            return web.json_response({'status': 'saved'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)

    async def handle_get_presets(self, request):
        if os.path.exists(PRESETS_FILE):
            try:
                with open(PRESETS_FILE, "r") as f:
                    data = json.load(f)
                return web.json_response(data)
            except Exception as e:
                return web.json_response({'error': f"Failed to load presets: {e}"}, status=500)
        return web.json_response({})

    async def handle_save_presets(self, request):
        try:
            data = await request.json()
            with open(PRESETS_FILE, "w") as f:
                json.dump(data, f, indent=4)
            return web.json_response({'status': 'saved'})
        except Exception as e:
            return web.json_response({'error': str(e)}, status=500)
